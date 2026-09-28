"""Ordem 032 — destino frio contra o protocolo S3 de verdade (MinIO efêmero).

Roda só com ``PYTEST_MINIO=1 scripts/pytest.sh``: o wrapper sobe um MinIO na
lab (sem porta publicada, sem dado real), com a credencial do gravador presa à
política de ``docs/ops/auditlog-cold-writer-policy.json`` — a mesma que vai
para a AWS — e o derruba ao fim. Sem ``AUDIT_LOG_COLD_S3_TEST_ENDPOINT`` (no
CI) a classe é pulada; com ele definido e o MinIO fora do ar, ela FALHA.

"Credencial que só grava" é afirmação até alguém provar o vermelho (ordem
020): aqui ela falha ao apagar, e o Object Lock recusa a remoção até ao root.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import uuid
from unittest import skipUnless

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from dateutil.relativedelta import relativedelta
from django.test import TestCase, override_settings

from apps.core import cold_storage, partitioning
from apps.core import cold_storage_backends as csb
from apps.core.tests.cold_s3_fixtures import BUCKET, exporta_de_verdade
from apps.core.tests.test_cold_storage import TEST_KEY

_MINIO = os.environ.get("AUDIT_LOG_COLD_S3_TEST_ENDPOINT", "")


def _cliente_minio(chave: str, segredo: str):
    return boto3.client(
        "s3",
        endpoint_url=_MINIO,
        region_name="sa-east-1",
        aws_access_key_id=os.environ[chave],
        aws_secret_access_key=os.environ[segredo],
        config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 2}),
    )


@skipUnless(_MINIO, "MinIO da lab ausente: rode com PYTEST_MINIO=1 scripts/pytest.sh (ordem 032)")
@override_settings(BACKUP_ENCRYPTION_KEY=TEST_KEY)
class MinioDestinoFrioTests(TestCase):
    def setUp(self):
        self.gravador = _cliente_minio(
            "AUDIT_LOG_COLD_S3_TEST_WRITER_KEY", "AUDIT_LOG_COLD_S3_TEST_WRITER_SECRET"
        )
        self.root = _cliente_minio(
            "AUDIT_LOG_COLD_S3_TEST_ROOT_KEY", "AUDIT_LOG_COLD_S3_TEST_ROOT_SECRET"
        )
        # O MinIO não aceita a classe GLACIER; o resto é o backend de produção,
        # com a credencial de produção (a política de docs/ops/).
        self.backend = csb.S3ColdStorageBackend(
            bucket=BUCKET, client=self.gravador, storage_class="STANDARD"
        )

    def _exporta(self):
        receipt = exporta_de_verdade(self.backend)
        bucket, key, versions = csb.parse_s3_location(receipt.stored_location)
        return receipt, key, versions["versionId"]

    def test_exporta_verifica_drila_e_so_entao_dropa(self):
        receipt, key, version = self._exporta()
        self.assertTrue(receipt.verified)
        head = self.gravador.head_object(Bucket=BUCKET, Key=key, VersionId=version)
        self.assertEqual(head["ObjectLockMode"], "COMPLIANCE")
        self.assertGreaterEqual(
            head["ObjectLockRetainUntilDate"],
            dt.datetime.now(dt.UTC) + relativedelta(months=240) - dt.timedelta(days=1),
        )

        drill = cold_storage.drill_cold_copy(receipt.stored_location, backend=self.backend)
        self.assertEqual((drill.status, drill.row_count), ("ok", 1))

        partitioning.drop_partition(receipt.partition_name, cold_export_receipt=receipt)
        self.assertFalse(partitioning.partition_exists(receipt.partition_name))

    def test_credencial_do_gravador_nao_apaga(self):
        _, key, version = self._exporta()
        for kwargs in ({}, {"VersionId": version}):
            with self.subTest(**kwargs), self.assertRaises(ClientError) as ctx:
                self.gravador.delete_object(Bucket=BUCKET, Key=key, **kwargs)
            self.assertEqual(ctx.exception.response["Error"]["Code"], "AccessDenied")

    def test_compliance_recusa_ate_o_root(self):
        _, key, version = self._exporta()
        tentativas = {
            "apagar a versão": lambda: self.root.delete_object(
                Bucket=BUCKET, Key=key, VersionId=version, BypassGovernanceRetention=True
            ),
            "encurtar a trava": lambda: self.root.put_object_retention(
                Bucket=BUCKET,
                Key=key,
                VersionId=version,
                Retention={
                    "Mode": "COMPLIANCE",
                    "RetainUntilDate": dt.datetime.now(dt.UTC) + dt.timedelta(days=1),
                },
            ),
            "rebaixar para governance": lambda: self.root.put_object_retention(
                Bucket=BUCKET,
                Key=key,
                VersionId=version,
                Retention={
                    "Mode": "GOVERNANCE",
                    "RetainUntilDate": dt.datetime.now(dt.UTC) + relativedelta(months=241),
                },
                BypassGovernanceRetention=True,
            ),
        }
        for nome, tentativa in tentativas.items():
            with self.subTest(nome), self.assertRaises(ClientError):
                tentativa()
        self.gravador.head_object(Bucket=BUCKET, Key=key, VersionId=version)

    def test_bucket_sem_object_lock_e_recusado(self):
        """Com o root, para isolar a causa: o gravador nem tem direito nesse
        bucket, e a recusa tem de vir da falta de lock, não da política."""
        backend = csb.S3ColdStorageBackend(
            bucket=f"{BUCKET}-sem-lock", client=self.root, storage_class="STANDARD"
        )
        with self.assertRaisesRegex(cold_storage.ColdExportError, "ObjectLockConfiguration"):
            exporta_de_verdade(backend)

    def test_objeto_gravado_sem_lock_nao_passa_na_conferencia(self):
        key = f"core_auditlog/sem-lock-{uuid.uuid4().hex}.jsonl.gpg"
        resp = self.gravador.put_object(Bucket=BUCKET, Key=key, Body=b"cifrado\n")
        location = f"s3://{BUCKET}/{key}?versionId={resp['VersionId']}&manifestVersionId=x"
        with self.assertRaisesRegex(csb.ColdStorageError, "COMPLIANCE"):
            self.backend.verify_stored(location, hashlib.sha256(b"cifrado\n").hexdigest())

    def test_drill_reprova_manifesto_adulterado_no_bucket(self):
        receipt, key, version = self._exporta()
        _, _, versions = csb.parse_s3_location(receipt.stored_location)
        manifest_key = key.replace(".jsonl.gpg", ".manifest.json")
        manifesto = json.loads(
            self.gravador.get_object(
                Bucket=BUCKET, Key=manifest_key, VersionId=versions["manifestVersionId"]
            )["Body"].read()
        )
        manifesto["row_count"] = 7
        falso = self.gravador.put_object(
            Bucket=BUCKET,
            Key=manifest_key,
            Body=json.dumps(manifesto).encode(),
            ObjectLockMode="COMPLIANCE",
            ObjectLockRetainUntilDate=dt.datetime.now(dt.UTC) + dt.timedelta(days=1),
        )
        adulterada = (
            f"s3://{BUCKET}/{key}?versionId={version}&manifestVersionId={falso['VersionId']}"
        )
        with self.assertRaisesRegex(cold_storage.ColdDrillError, "row_count"):
            cold_storage.drill_cold_copy(adulterada, backend=self.backend)
        # A versão original do manifesto continua lá, travada: sobrescrever cria
        # versão nova, não apaga a antiga.
        ok = cold_storage.drill_cold_copy(receipt.stored_location, backend=self.backend)
        self.assertEqual(ok.status, "ok")
