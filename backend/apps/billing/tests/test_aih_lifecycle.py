"""
AI-R1 — Reconciliação / ciclo de vida da AIH (SISAIH).

Cobre o serviço ``apps.billing.services.aih_lifecycle`` e as ações do viewset:
``reconciliar_numero_oficial`` troca o número provisório pelo oficial de 13
dígitos (preservando o provisório), leva a situação a ``autorizada`` e popula o
solicitante; rejeita número inválido/duplicado ou AIH já autorizada.
``rejeitar_aih`` marca ``rejeitada`` com motivo obrigatório.

RBAC herda ``_SusPermissionMixin``: reconciliar/rejeitar são escritas → ``sus.write``.
"""

from __future__ import annotations

from datetime import date

from django.core.exceptions import ValidationError as DjangoValidationError

from apps.billing.services import aih_lifecycle
from apps.billing.sus_models import AihAutorizacao

from .test_aih import AihTestBase

BASE = "/api/v1/billing"


# ─── Service-level ────────────────────────────────────────────────────────────


class TestReconciliarService(AihTestBase):
    def test_default_situacao_is_solicitada(self):
        comp = self._competencia()
        aih = self._aih(comp, numero="2026070000001")
        assert aih.situacao == AihAutorizacao.Situacao.SOLICITADA
        assert aih.numero_provisorio == ""

    def test_reconciliar_sets_official_number_and_autoriza(self):
        comp = self._competencia()
        aih = self._aih(comp, numero="2026070000001")
        out = aih_lifecycle.reconciliar_numero_oficial(
            aih=aih, numero_oficial="9999999999999", data_autorizacao=date(2026, 7, 20)
        )
        assert out.numero_aih == "9999999999999"
        assert out.situacao == AihAutorizacao.Situacao.AUTORIZADA
        assert out.numero_provisorio == "2026070000001"  # provisório preservado
        assert out.data_autorizacao == date(2026, 7, 20)

    def test_reconciliar_populates_solicitante(self):
        comp = self._competencia()
        aih = self._aih(comp, numero="2026070000002")
        aih.professional_solicitante = None
        aih.save(update_fields=["professional_solicitante"])
        out = aih_lifecycle.reconciliar_numero_oficial(
            aih=aih, numero_oficial="8888888888888", professional_solicitante=self.prof
        )
        assert out.professional_solicitante_id == self.prof.id

    def test_reconciliar_defaults_data_autorizacao_to_today(self):
        comp = self._competencia()
        aih = self._aih(comp, numero="2026070000003")
        out = aih_lifecycle.reconciliar_numero_oficial(aih=aih, numero_oficial="7777777777777")
        assert out.data_autorizacao is not None

    def test_reconciliar_invalid_number_rejected(self):
        comp = self._competencia()
        aih = self._aih(comp, numero="2026070000004")
        for bad in ["123", "12345678901234", "abcdefghijklm", ""]:
            try:
                aih_lifecycle.reconciliar_numero_oficial(aih=aih, numero_oficial=bad)
                raise AssertionError(f"expected invalid number {bad!r} to raise")
            except DjangoValidationError:
                pass
        aih.refresh_from_db()
        assert aih.situacao == AihAutorizacao.Situacao.SOLICITADA

    def test_reconciliar_duplicate_official_rejected(self):
        comp = self._competencia()
        first = self._aih(comp, numero="1111111111111")
        second = self._aih(comp, numero="2222222222222")
        try:
            aih_lifecycle.reconciliar_numero_oficial(aih=second, numero_oficial=first.numero_aih)
            raise AssertionError("expected duplicate official number to raise")
        except DjangoValidationError:
            pass

    def test_reconciliar_already_autorizada_rejected(self):
        comp = self._competencia()
        aih = self._aih(comp, numero="2026070000005")
        aih_lifecycle.reconciliar_numero_oficial(aih=aih, numero_oficial="6666666666666")
        try:
            aih_lifecycle.reconciliar_numero_oficial(aih=aih, numero_oficial="5555555555555")
            raise AssertionError("expected re-reconcile of autorizada to raise")
        except DjangoValidationError:
            pass
        aih.refresh_from_db()
        assert aih.numero_aih == "6666666666666"  # unchanged


class TestRejeitarService(AihTestBase):
    def test_rejeitar_sets_rejeitada_with_motivo(self):
        comp = self._competencia()
        aih = self._aih(comp, numero="2026070000006")
        out = aih_lifecycle.rejeitar_aih(aih=aih, motivo="CID incompatível com procedimento")
        assert out.situacao == AihAutorizacao.Situacao.REJEITADA
        assert out.motivo_rejeicao == "CID incompatível com procedimento"

    def test_rejeitar_empty_motivo_rejected(self):
        comp = self._competencia()
        aih = self._aih(comp, numero="2026070000007")
        try:
            aih_lifecycle.rejeitar_aih(aih=aih, motivo="   ")
            raise AssertionError("expected empty motivo to raise")
        except DjangoValidationError:
            pass


# ─── API + RBAC ───────────────────────────────────────────────────────────────


class TestAihLifecycleAPI(AihTestBase):
    def test_reconciliar_requires_write_permission(self):
        comp = self._competencia()
        aih = self._aih(comp, numero="2026070000008")
        # reader tem sus.read mas não sus.write → 403
        forbidden = self._client(self.reader).post(
            f"{BASE}/aih-autorizacoes/{aih.id}/reconciliar/",
            {"numero_oficial": "9999999999999"},
            format="json",
        )
        assert forbidden.status_code == 403, forbidden.content
        # writer tem sus.write → 200
        ok = self._client(self.writer).post(
            f"{BASE}/aih-autorizacoes/{aih.id}/reconciliar/",
            {"numero_oficial": "9999999999999"},
            format="json",
        )
        assert ok.status_code == 200, ok.content
        assert ok.data["situacao"] == "autorizada"
        assert ok.data["numero_aih"] == "9999999999999"

    def test_reconciliar_invalid_number_returns_409(self):
        comp = self._competencia()
        aih = self._aih(comp, numero="2026070000009")
        resp = self._client(self.writer).post(
            f"{BASE}/aih-autorizacoes/{aih.id}/reconciliar/",
            {"numero_oficial": "123"},
            format="json",
        )
        assert resp.status_code == 409, resp.content

    def test_rejeitar_via_api(self):
        comp = self._competencia()
        aih = self._aih(comp, numero="2026070000010")
        resp = self._client(self.writer).post(
            f"{BASE}/aih-autorizacoes/{aih.id}/rejeitar/",
            {"motivo": "Glosa administrativa"},
            format="json",
        )
        assert resp.status_code == 200, resp.content
        assert resp.data["situacao"] == "rejeitada"
        assert resp.data["motivo_rejeicao"] == "Glosa administrativa"
