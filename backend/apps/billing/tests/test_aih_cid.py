"""
AI-R2 — CID-10 governado na AIH (FK core.CID10Code).

O ``cid_principal`` da AIH era texto livre; agora há FK governada
(``cid10`` → core.CID10Code) + flag ``cid_unmatched``, reconciliada pela property
``cid_principal_code`` (mesmo molde de emr.MedicalHistory). A remessa SISAIH passa
a emitir o código reconciliado; o signal cross-schema bloqueia apagar um CID10Code
referenciado por uma AIH.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models.deletion import ProtectedError

from apps.billing.services.sus_remessa import gerar_remessa_aih
from apps.core.models import CID10Code

from .test_aih import AihTestBase

BASE = "/api/v1/billing"


# ─── Property de reconciliação ────────────────────────────────────────────────


class TestCidReconciliation(AihTestBase):
    def test_cid_code_reconciles_to_governed_fk(self):
        cid = CID10Code.objects.create(code="J189", description="Pneumonia não especificada")
        comp = self._competencia()
        aih = self._aih(comp, numero="2026070100001")
        aih.cid_principal_code = "J189"
        aih.save(update_fields=["cid10", "cid_principal", "cid_unmatched"])
        aih.refresh_from_db()
        assert aih.cid10_id == cid.id
        assert aih.cid_principal == ""  # texto legado limpo quando reconciliado
        assert aih.cid_unmatched is False
        assert aih.cid_principal_code == "J189"  # getter resolve pela FK

    def test_cid_code_unmatched_keeps_text(self):
        comp = self._competencia()
        aih = self._aih(comp, numero="2026070100002")
        aih.cid_principal_code = "X999"  # não existe no catálogo
        aih.save(update_fields=["cid10", "cid_principal", "cid_unmatched"])
        aih.refresh_from_db()
        assert aih.cid10_id is None
        assert aih.cid_principal == "X999"
        assert aih.cid_unmatched is True
        assert aih.cid_principal_code == "X999"

    def test_cid_code_empty_clears(self):
        CID10Code.objects.create(code="J189", description="Pneumonia")
        comp = self._competencia()
        aih = self._aih(comp, numero="2026070100003")
        aih.cid_principal_code = "J189"
        aih.save(update_fields=["cid10", "cid_principal", "cid_unmatched"])
        aih.cid_principal_code = ""
        aih.save(update_fields=["cid10", "cid_principal", "cid_unmatched"])
        aih.refresh_from_db()
        assert aih.cid10_id is None
        assert aih.cid_principal == ""
        assert aih.cid_unmatched is False


# ─── Remessa usa o código reconciliado ────────────────────────────────────────


class TestRemessaUsesReconciledCid(AihTestBase):
    def test_remessa_line_uses_reconciled_cid_code(self):
        CID10Code.objects.create(code="J189", description="Pneumonia")
        comp = self._competencia()
        adm = self._admission()
        aih = self._aih(comp, numero="2026070100004", admission=adm)
        # Reconcilia via FK e limpa o texto legado — a remessa deve emitir o code
        # da FK, provando que não depende mais do CharField cru.
        aih.cid_principal_code = "J189"
        aih.save(update_fields=["cid10", "cid_principal", "cid_unmatched"])
        assert aih.cid_principal == ""
        remessa = gerar_remessa_aih(comp)
        assert "J189" in remessa


# ─── Proteção cross-schema de delete ──────────────────────────────────────────


class TestCidDeleteProtection(AihTestBase):
    def test_delete_blocked_when_referenced_by_aih(self):
        cid = CID10Code.objects.create(code="J189", description="Pneumonia")
        comp = self._competencia()
        aih = self._aih(comp, numero="2026070100005")
        aih.cid_principal_code = "J189"
        aih.save(update_fields=["cid10", "cid_principal", "cid_unmatched"])
        with self.assertRaises(ProtectedError) as ctx, transaction.atomic():
            cid.delete()
        assert "AihAutorizacao" in str(ctx.exception)
        assert CID10Code.objects.filter(pk=cid.pk).exists()


# ─── API ──────────────────────────────────────────────────────────────────────


class TestAihCidAPI(AihTestBase):
    def test_patch_cid_code_reconciles(self):
        CID10Code.objects.create(code="J189", description="Pneumonia")
        comp = self._competencia()
        aih = self._aih(comp, numero="2026070100006")
        resp = self._client(self.writer).patch(
            f"{BASE}/aih-autorizacoes/{aih.id}/",
            {"cid_principal_code": "J189"},
            format="json",
        )
        assert resp.status_code == 200, resp.content
        assert resp.data["cid10"] is not None
        assert resp.data["cid_unmatched"] is False
        aih.refresh_from_db()
        assert aih.cid10_id is not None

    def test_patch_unmatched_cid_flags_unmatched(self):
        comp = self._competencia()
        aih = self._aih(comp, numero="2026070100007")
        resp = self._client(self.writer).patch(
            f"{BASE}/aih-autorizacoes/{aih.id}/",
            {"cid_principal_code": "X999"},
            format="json",
        )
        assert resp.status_code == 200, resp.content
        assert resp.data["cid_unmatched"] is True
        assert resp.data["cid10"] is None
