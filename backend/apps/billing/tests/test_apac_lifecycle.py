"""
APAC-simetria — situação/reconciliação + CID-10 governado da APAC (S3).

Porta para a APAC o padrão validado na AIH (AI-R1/AI-R2): situação
(``solicitada`` → ``autorizada``/``rejeitada``), reconciliação do número oficial
de 13 dígitos, e CID-10 governado (FK core.CID10Code) com reconciliação pela
property ``cid_principal_code``. A remessa APAC passa a emitir o código
reconciliado; o signal cross-schema bloqueia apagar CID referenciado por APAC.

RBAC herda ``_SusPermissionMixin``: reconciliar/rejeitar são escritas → ``sus.write``.
"""

from __future__ import annotations

from datetime import date

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models.deletion import ProtectedError

from apps.billing.services import apac_lifecycle
from apps.billing.services.sus_remessa import gerar_remessa_apac
from apps.billing.sus_models import ApacAutorizacao
from apps.core.models import CID10Code

from .test_sus_remessa import SusRemessaTestBase

BASE = "/api/v1/billing"


# ─── Reconciliação / situação ─────────────────────────────────────────────────


class TestApacReconciliarService(SusRemessaTestBase):
    def test_default_situacao_is_solicitada(self):
        comp = self._competencia()
        apac = self._apac(comp, numero="2026070200001")
        assert apac.situacao == ApacAutorizacao.Situacao.SOLICITADA

    def test_reconciliar_sets_official_and_autoriza(self):
        comp = self._competencia()
        apac = self._apac(comp, numero="2026070200001")
        out = apac_lifecycle.reconciliar_numero_oficial(
            apac=apac, numero_oficial="9999999999999", data_autorizacao=date(2026, 7, 21)
        )
        assert out.numero_apac == "9999999999999"
        assert out.situacao == ApacAutorizacao.Situacao.AUTORIZADA
        assert out.numero_provisorio == "2026070200001"
        assert out.data_autorizacao == date(2026, 7, 21)

    def test_reconciliar_invalid_number_rejected(self):
        comp = self._competencia()
        apac = self._apac(comp, numero="2026070200002")
        try:
            apac_lifecycle.reconciliar_numero_oficial(apac=apac, numero_oficial="123")
            raise AssertionError("expected invalid number to raise")
        except DjangoValidationError:
            pass
        apac.refresh_from_db()
        assert apac.situacao == ApacAutorizacao.Situacao.SOLICITADA

    def test_reconciliar_already_autorizada_rejected(self):
        comp = self._competencia()
        apac = self._apac(comp, numero="2026070200003")
        apac_lifecycle.reconciliar_numero_oficial(apac=apac, numero_oficial="8888888888888")
        try:
            apac_lifecycle.reconciliar_numero_oficial(apac=apac, numero_oficial="7777777777777")
            raise AssertionError("expected re-reconcile to raise")
        except DjangoValidationError:
            pass
        apac.refresh_from_db()
        assert apac.numero_apac == "8888888888888"

    def test_rejeitar_sets_rejeitada_with_motivo(self):
        comp = self._competencia()
        apac = self._apac(comp, numero="2026070200004")
        out = apac_lifecycle.rejeitar_apac(apac=apac, motivo="Fora de validade")
        assert out.situacao == ApacAutorizacao.Situacao.REJEITADA
        assert out.motivo_rejeicao == "Fora de validade"


# ─── CID-10 governado ─────────────────────────────────────────────────────────


class TestApacCid(SusRemessaTestBase):
    def test_cid_code_reconciles_to_fk(self):
        cid = CID10Code.objects.create(code="C509", description="Neoplasia maligna da mama")
        comp = self._competencia()
        apac = self._apac(comp, numero="2026070200005")
        apac.cid_principal_code = "C509"
        apac.save(update_fields=["cid10", "cid_principal", "cid_unmatched"])
        apac.refresh_from_db()
        assert apac.cid10_id == cid.id
        assert apac.cid_principal == ""
        assert apac.cid_unmatched is False
        assert apac.cid_principal_code == "C509"

    def test_cid_code_unmatched_keeps_text(self):
        comp = self._competencia()
        apac = self._apac(comp, numero="2026070200006")
        apac.cid_principal_code = "Z999"
        apac.save(update_fields=["cid10", "cid_principal", "cid_unmatched"])
        apac.refresh_from_db()
        assert apac.cid10_id is None
        assert apac.cid_principal == "Z999"
        assert apac.cid_unmatched is True

    def test_remessa_uses_reconciled_cid(self):
        CID10Code.objects.create(code="C509", description="Neoplasia")
        comp = self._competencia()
        apac = self._apac(comp, numero="2026070200007")
        apac.cid_principal_code = "C509"
        apac.save(update_fields=["cid10", "cid_principal", "cid_unmatched"])
        assert apac.cid_principal == ""
        remessa = gerar_remessa_apac(comp)
        assert "C509" in remessa

    def test_delete_blocked_when_referenced_by_apac(self):
        cid = CID10Code.objects.create(code="C509", description="Neoplasia")
        comp = self._competencia()
        apac = self._apac(comp, numero="2026070200008")
        apac.cid_principal_code = "C509"
        apac.save(update_fields=["cid10", "cid_principal", "cid_unmatched"])
        with self.assertRaises(ProtectedError) as ctx, transaction.atomic():
            cid.delete()
        assert "ApacAutorizacao" in str(ctx.exception)
        assert CID10Code.objects.filter(pk=cid.pk).exists()


# ─── API + RBAC ───────────────────────────────────────────────────────────────


class TestApacLifecycleAPI(SusRemessaTestBase):
    def test_reconciliar_requires_write_permission(self):
        comp = self._competencia()
        apac = self._apac(comp, numero="2026070200009")
        forbidden = self._client(self.reader).post(
            f"{BASE}/apac-autorizacoes/{apac.id}/reconciliar/",
            {"numero_oficial": "9999999999999"},
            format="json",
        )
        assert forbidden.status_code == 403, forbidden.content
        ok = self._client(self.writer).post(
            f"{BASE}/apac-autorizacoes/{apac.id}/reconciliar/",
            {"numero_oficial": "9999999999999"},
            format="json",
        )
        assert ok.status_code == 200, ok.content
        assert ok.data["situacao"] == "autorizada"

    def test_patch_cid_code_reconciles(self):
        CID10Code.objects.create(code="C509", description="Neoplasia")
        comp = self._competencia()
        apac = self._apac(comp, numero="2026070200010")
        resp = self._client(self.writer).patch(
            f"{BASE}/apac-autorizacoes/{apac.id}/",
            {"cid_principal_code": "C509"},
            format="json",
        )
        assert resp.status_code == 200, resp.content
        assert resp.data["cid10"] is not None
        assert resp.data["cid_unmatched"] is False
