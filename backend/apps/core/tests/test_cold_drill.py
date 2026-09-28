"""Ordem 032 — drill da cópia fria: baixa, decifra e confere contra o manifesto.

O Glacier devolve o objeto de forma assíncrona (Expedited 1–5 min, Standard
3–5 h): o drill nasce com o ciclo — pede a restauração, reconhece a espera e só
confere quando o objeto voltou. O MinIO não emula a classe GLACIER
(``InvalidStorageClass``, medido na lab), então esse ciclo se prova com o
``Stubber``, servindo o conteúdo cifrado REAL de um export de verdade.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

from botocore.stub import Stubber
from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.core import cold_drill
from apps.core import cold_storage_backends as csb
from apps.core.tests.cold_s3_fixtures import (
    AGORA,
    BUCKET,
    Guarda,
    cliente_falso,
    corpo,
    exporta_de_verdade,
)
from apps.core.tests.test_cold_storage import TEST_KEY


@override_settings(BACKUP_ENCRYPTION_KEY=TEST_KEY)
class DrillGlacierCicloTests(TestCase):
    """O Glacier devolve o objeto de forma assíncrona. O drill tem de nascer
    com o ciclo: pede a restauração, reconhece a espera, e só confere quando o
    objeto voltou — senão passa no alvo local e quebra no dia em que valer."""

    LOCATION = f"s3://{BUCKET}/core_auditlog/p.jsonl.gpg?versionId=v1&manifestVersionId=m1"

    def setUp(self):
        self.client = cliente_falso()
        self.stub = Stubber(self.client)
        self.backend = csb.S3ColdStorageBackend(
            bucket=BUCKET, client=self.client, clock=lambda: AGORA
        )
        guarda = Guarda()
        receipt = exporta_de_verdade(guarda)
        payload = Path(receipt.stored_location)
        self.cifrado = payload.read_bytes()
        self.manifesto = payload.with_name(
            payload.name.replace(".jsonl.gpg", ".manifest.json")
        ).read_bytes()

    def _head(self, restore: str | None):
        resp = {"StorageClass": "GLACIER", "VersionId": "v1"}
        if restore is not None:
            resp["Restore"] = restore
        self.stub.add_response(
            "head_object",
            resp,
            {"Bucket": BUCKET, "Key": "core_auditlog/p.jsonl.gpg", "VersionId": "v1"},
        )

    def test_objeto_no_glacier_pede_restauracao_e_fica_pendente(self):
        self._head(restore=None)
        self.stub.add_response(
            "restore_object",
            {},
            {
                "Bucket": BUCKET,
                "Key": "core_auditlog/p.jsonl.gpg",
                "VersionId": "v1",
                "RestoreRequest": {"Days": 7, "GlacierJobParameters": {"Tier": "Standard"}},
            },
        )
        with self.stub:
            result = cold_drill.drill_cold_copy(self.LOCATION, backend=self.backend)
        self.stub.assert_no_pending_responses()
        self.assertEqual(result.status, "pending")
        self.assertIn("restauração pedida", result.detail)

    def test_restauracao_em_andamento_nao_pede_de_novo(self):
        self._head(restore='ongoing-request="true"')
        with self.stub:
            result = cold_drill.drill_cold_copy(self.LOCATION, backend=self.backend)
        self.stub.assert_no_pending_responses()
        self.assertEqual(result.status, "pending")
        self.assertIn("em andamento", result.detail)

    def test_restauracao_pronta_baixa_decifra_e_confere(self):
        self._head(restore='ongoing-request="false", expiry-date="Fri, 02 Oct 2026 00:00:00 GMT"')
        self.stub.add_response(
            "get_object",
            {"Body": corpo(self.cifrado)},
            {"Bucket": BUCKET, "Key": "core_auditlog/p.jsonl.gpg", "VersionId": "v1"},
        )
        self.stub.add_response(
            "get_object",
            {"Body": corpo(self.manifesto)},
            {"Bucket": BUCKET, "Key": "core_auditlog/p.manifest.json", "VersionId": "m1"},
        )
        with self.stub:
            result = cold_drill.drill_cold_copy(self.LOCATION, backend=self.backend)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.row_count, 1)


@override_settings(BACKUP_ENCRYPTION_KEY=TEST_KEY)
class DrillLocalTests(TestCase):
    """O mesmo drill vale para o alvo local — e sabe REPROVAR (controle
    negativo da 020: verificação que nunca viu vermelho é cerimônia)."""

    def setUp(self):
        self.guarda = Guarda()
        self.receipt = exporta_de_verdade(self.guarda)
        self.payload = Path(self.receipt.stored_location)
        self.manifest = self.payload.with_name(
            self.payload.name.replace(".jsonl.gpg", ".manifest.json")
        )

    def _drill(self):
        return cold_drill.drill_cold_copy(self.receipt.stored_location, backend=self.guarda.local)

    def test_copia_integra_passa(self):
        result = self._drill()
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.row_count, 1)

    def test_contagem_do_manifesto_divergente_e_recusada(self):
        manifesto = json.loads(self.manifest.read_text())
        manifesto["row_count"] = 2
        self.manifest.write_text(json.dumps(manifesto))
        with self.assertRaisesRegex(cold_drill.ColdDrillError, "row_count"):
            self._drill()

    def test_cifrado_adulterado_e_recusado(self):
        self.payload.write_bytes(self.payload.read_bytes() + b"x")
        with self.assertRaisesRegex(cold_drill.ColdDrillError, "sha256_cipher"):
            self._drill()

    def test_claro_divergente_do_manifesto_e_recusado(self):
        manifesto = json.loads(self.manifest.read_text())
        manifesto["sha256_plain"] = "0" * 64
        self.manifest.write_text(json.dumps(manifesto))
        with self.assertRaisesRegex(cold_drill.ColdDrillError, "sha256_plain"):
            self._drill()

    def test_comando_de_drill(self):
        out = io.StringIO()
        call_command("drill_audit_cold_copy", self.receipt.stored_location, stdout=out)
        self.assertIn("OK", out.getvalue())
