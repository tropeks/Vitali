"""Ordem 032 — backend S3 do destino frio: parâmetros exatos, sem rede.

A 020 fixou o destino (decisão do Capitão): S3 Glacier Flexible em São Paulo,
um objeto por partição com o manifesto como objeto próprio, cifrado por nós
antes de subir, Object Lock em modo compliance pelo prazo, e credencial que só
grava. Aqui o ``Stubber`` do botocore confere cada chamada contra o modelo real
da API. O protocolo de verdade se prova no MinIO da lab
(``test_cold_storage_minio.py``); o drill, em ``test_cold_drill.py``.
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from botocore.stub import ANY, Stubber
from dateutil.relativedelta import relativedelta
from django.test import SimpleTestCase, override_settings

from apps.core import cold_storage_backends as csb
from apps.core import cold_storage_s3 as s3b
from apps.core.tests.cold_s3_fixtures import (
    AGORA,
    BUCKET,
    TRAVA_ATE,
    arquivos,
    b64_sha256,
    cliente_falso,
)


class S3StoreParametrosTests(SimpleTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cold-s3-"))
        self.client = cliente_falso()
        self.stub = Stubber(self.client)
        self.backend = s3b.S3ColdStorageBackend(
            bucket=BUCKET, client=self.client, clock=lambda: AGORA
        )

    def test_payload_sobe_em_glacier_com_lock_compliance_de_240_meses_e_checksum(self):
        payload, manifest = arquivos(self.tmp)
        self.stub.add_response(
            "put_object",
            {"VersionId": "v-payload"},
            {
                "Bucket": BUCKET,
                "Key": "core_auditlog/part_x.jsonl.gpg",
                "Body": ANY,
                "StorageClass": "GLACIER",
                "ObjectLockMode": "COMPLIANCE",
                "ObjectLockRetainUntilDate": TRAVA_ATE,
                "ChecksumAlgorithm": "SHA256",
                "ChecksumSHA256": b64_sha256(payload.read_bytes()),
            },
        )
        # O manifesto fica em STANDARD: conferível sem pedir restauração, e
        # travado pelo mesmo prazo.
        self.stub.add_response(
            "put_object",
            {"VersionId": "v-manifest"},
            {
                "Bucket": BUCKET,
                "Key": "core_auditlog/part_x.manifest.json",
                "Body": ANY,
                "StorageClass": "STANDARD",
                "ObjectLockMode": "COMPLIANCE",
                "ObjectLockRetainUntilDate": TRAVA_ATE,
                "ChecksumAlgorithm": "SHA256",
                "ChecksumSHA256": b64_sha256(manifest.read_bytes()),
            },
        )
        with self.stub:
            location = self.backend.store(
                payload_path=payload, manifest_path=manifest, key_prefix="part_x"
            )
        self.stub.assert_no_pending_responses()
        self.assertEqual(
            location,
            f"s3://{BUCKET}/core_auditlog/part_x.jsonl.gpg"
            "?versionId=v-payload&manifestVersionId=v-manifest",
        )

    def test_bucket_sem_versao_e_recusado(self):
        """Sem ``VersionId`` na resposta o bucket não é versionado — e sem
        versionamento não existe Object Lock."""
        payload, manifest = arquivos(self.tmp)
        self.stub.add_response("put_object", {}, None)
        with self.stub, self.assertRaisesRegex(csb.ColdStorageError, "VersionId"):
            self.backend.store(payload_path=payload, manifest_path=manifest, key_prefix="p")

    def test_recusa_do_s3_vira_erro_que_nomeia_o_passo(self):
        payload, manifest = arquivos(self.tmp)
        self.stub.add_client_error(
            "put_object", "InvalidRequest", "Bucket is missing ObjectLockConfiguration"
        )
        with self.stub, self.assertRaisesRegex(csb.ColdStorageError, "ObjectLockConfiguration"):
            self.backend.store(payload_path=payload, manifest_path=manifest, key_prefix="p")


class S3VerifyStoredTests(SimpleTestCase):
    LOCATION = f"s3://{BUCKET}/core_auditlog/p.jsonl.gpg?versionId=v1&manifestVersionId=m1"
    SHA_HEX = hashlib.sha256(b"cifrado\n").hexdigest()

    def setUp(self):
        self.client = cliente_falso()
        self.stub = Stubber(self.client)
        self.backend = s3b.S3ColdStorageBackend(
            bucket=BUCKET, client=self.client, clock=lambda: AGORA
        )

    def _head(self, **over):
        resp = {
            "ChecksumSHA256": b64_sha256(b"cifrado\n"),
            "ObjectLockMode": "COMPLIANCE",
            "ObjectLockRetainUntilDate": TRAVA_ATE,
            "VersionId": "v1",
        }
        resp.update(over)
        return {k: v for k, v in resp.items() if v is not None}

    def _espera_head(self, resposta):
        self.stub.add_response(
            "head_object",
            resposta,
            {
                "Bucket": BUCKET,
                "Key": "core_auditlog/p.jsonl.gpg",
                "VersionId": "v1",
                "ChecksumMode": "ENABLED",
            },
        )

    def _espera_head_do_manifesto(self, resposta):
        self.stub.add_response(
            "head_object",
            resposta,
            {
                "Bucket": BUCKET,
                "Key": "core_auditlog/p.manifest.json",
                "VersionId": "m1",
                "ChecksumMode": "ENABLED",
            },
        )

    def test_objeto_certo_passa(self):
        self._espera_head(self._head())
        self._espera_head_do_manifesto(self._head(VersionId="m1"))
        with self.stub:
            self.backend.verify_stored(self.LOCATION, self.SHA_HEX)
        self.stub.assert_no_pending_responses()

    def test_manifesto_sem_lock_e_recusado(self):
        """Revisão da 032: o drill não prova a cópia sem o manifesto, então ele
        passa pela mesma conferência antes do DROP."""
        self._espera_head(self._head())
        self._espera_head_do_manifesto(
            self._head(VersionId="m1", ObjectLockMode=None, ObjectLockRetainUntilDate=None)
        )
        with self.stub, self.assertRaisesRegex(csb.ColdStorageError, "manifest.*COMPLIANCE"):
            self.backend.verify_stored(self.LOCATION, self.SHA_HEX)

    def test_manifesto_com_trava_curta_e_recusado(self):
        self._espera_head(self._head())
        self._espera_head_do_manifesto(
            self._head(VersionId="m1", ObjectLockRetainUntilDate=AGORA + relativedelta(months=1))
        )
        with self.stub, self.assertRaisesRegex(csb.ColdStorageError, "manifest.*retain"):
            self.backend.verify_stored(self.LOCATION, self.SHA_HEX)

    def test_manifesto_sem_checksum_e_recusado(self):
        self._espera_head(self._head())
        self._espera_head_do_manifesto(self._head(VersionId="m1", ChecksumSHA256=None))
        with self.stub, self.assertRaisesRegex(csb.ColdStorageError, "manifest.*SHA-256"):
            self.backend.verify_stored(self.LOCATION, self.SHA_HEX)

    def test_checksum_diferente_e_recusado(self):
        self._espera_head(self._head(ChecksumSHA256=b64_sha256(b"outro")))
        with self.stub, self.assertRaisesRegex(csb.ColdStorageError, "sha256"):
            self.backend.verify_stored(self.LOCATION, self.SHA_HEX)

    def test_objeto_sem_lock_e_recusado(self):
        """Medido no MinIO: PUT sem os parâmetros de lock PASSA num bucket com
        lock e sem retenção padrão. Só a conferência pega."""
        self._espera_head(self._head(ObjectLockMode=None, ObjectLockRetainUntilDate=None))
        with self.stub, self.assertRaisesRegex(csb.ColdStorageError, "COMPLIANCE"):
            self.backend.verify_stored(self.LOCATION, self.SHA_HEX)

    def test_lock_em_governance_e_recusado(self):
        self._espera_head(self._head(ObjectLockMode="GOVERNANCE"))
        with self.stub, self.assertRaisesRegex(csb.ColdStorageError, "COMPLIANCE"):
            self.backend.verify_stored(self.LOCATION, self.SHA_HEX)

    def test_trava_mais_curta_que_o_prazo_e_recusada(self):
        self._espera_head(self._head(ObjectLockRetainUntilDate=AGORA + relativedelta(months=12)))
        with self.stub, self.assertRaisesRegex(csb.ColdStorageError, "retain"):
            self.backend.verify_stored(self.LOCATION, self.SHA_HEX)


class EscolhaDoBackendTests(SimpleTestCase):
    def test_padrao_continua_local(self):
        self.assertIsInstance(csb.get_cold_storage_backend(), csb.LocalDiskColdStorageBackend)

    @override_settings(AUDIT_LOG_COLD_STORAGE_BACKEND="s3", AUDIT_LOG_COLD_S3_BUCKET="")
    def test_s3_sem_bucket_recusa_nomeando_a_setting(self):
        with self.assertRaisesRegex(csb.ColdStorageError, "AUDIT_LOG_COLD_S3_BUCKET"):
            csb.get_cold_storage_backend()

    @override_settings(AUDIT_LOG_COLD_STORAGE_BACKEND="ftp")
    def test_backend_desconhecido_recusa(self):
        with self.assertRaisesRegex(csb.ColdStorageError, "ftp"):
            csb.get_cold_storage_backend()

    @override_settings(
        AUDIT_LOG_COLD_STORAGE_BACKEND="s3",
        AUDIT_LOG_COLD_S3_BUCKET=BUCKET,
        AUDIT_LOG_COLD_S3_REGION="sa-east-1",
        AUDIT_LOG_COLD_S3_ENDPOINT_URL="",
        AUDIT_LOG_COLD_S3_STORAGE_CLASS="GLACIER",
        AUDIT_LOG_COLD_LOCK_MONTHS=240,
    )
    def test_s3_pelas_settings(self):
        backend = csb.get_cold_storage_backend()
        self.assertIsInstance(backend, s3b.S3ColdStorageBackend)
        self.assertEqual(backend.bucket, BUCKET)
        self.assertEqual(backend.storage_class, "GLACIER")
        self.assertEqual(backend.lock_months, 240)
        self.assertEqual(backend.client.meta.region_name, "sa-east-1")

    @override_settings(AUDIT_LOG_COLD_LOCK_MONTHS=0)
    def test_trava_de_zero_meses_recusa(self):
        with self.assertRaisesRegex(csb.ColdStorageError, "AUDIT_LOG_COLD_LOCK_MONTHS"):
            s3b.S3ColdStorageBackend(bucket=BUCKET, client=cliente_falso())
