"""Onda2 2.3 — guia TISS faturada deixa de ser editável às cegas.

Antes desta mudança, ``TISSGuideViewSet`` era um ``ModelViewSet`` puro, sem
``perform_update``: ``authorization_number``, ``cid10_codes``, ``competency``,
``provider``, ``price_table`` e ``insured_card_number`` continuavam editáveis
por PATCH depois de ``status="submitted"``/``"paid"``, sem checagem de estado e
sem qualquer rastro de quem mudou o quê — o cenário de perda de receita descrito
na tarefa (guia editada depois do envio, lote exportado deixa de bater com o que
a operadora recebeu).

Este arquivo é novo; ``test_billing.py`` continua sendo a fonte de verdade para
o resto do ciclo de vida da guia (numeração, filtros, batch). O único PATCH de
guia já existente lá (``test_guide_status_patch_ignored``) roda sobre uma guia
ainda ``draft`` — continua passando sem alteração (ver relatório da tarefa,
seção RISCOS/REGRESSÕES).
"""

import datetime

from django.core.cache import cache
from rest_framework.test import APIClient

from apps.billing.models import InsuranceProvider, TISSGuide
from apps.core.models import AuditLog, FeatureFlag, Role, User
from apps.emr.models import Encounter, Patient, Professional
from apps.test_utils import TenantTestCase


class GuideImmutabilityTestCase(TenantTestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain

        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant, module_key="billing", defaults={"is_enabled": True}
        )

        self.faturista_role = Role.objects.create(
            name="faturista_guide_lock",
            permissions=["billing.read", "billing.write"],
            is_system=True,
        )
        self.faturista = User.objects.create_user(
            email="fat.lock@test.com",
            full_name="Faturista Lock",
            password="Str0ng!Pass#2024",
            role=self.faturista_role,
        )
        prof_user = User.objects.create_user(
            email="medico.lock@test.com",
            full_name="Dr. Lock",
            password="Str0ng!Pass#2024",
            role=self.faturista_role,
        )
        self.patient = Patient.objects.create(
            full_name="Guia Lock Paciente",
            cpf="111.222.333-44",
            birth_date=datetime.date(1985, 1, 1),
            gender="F",
        )
        self.professional = Professional.objects.create(
            user=prof_user, council_type="CRM", council_number="LK-1", council_state="SP"
        )
        self.encounter = Encounter.objects.create(
            patient=self.patient, professional=self.professional
        )
        self.provider = InsuranceProvider.objects.create(name="Unimed Lock", ans_code="888888")

        self.fat_token = self._get_token("fat.lock@test.com")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_token(self, email):
        resp = self.client.post(
            "/api/v1/auth/login",
            {"email": email, "password": "Str0ng!Pass#2024"},
            format="json",
        )
        return resp.json().get("access")

    def _auth(self, token):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return c

    def _create_guide(self, client=None):
        if client is None:
            client = self._auth(self.fat_token)
        return client.post(
            "/api/v1/billing/guides/",
            {
                "guide_type": "sadt",
                "encounter": str(self.encounter.id),
                "patient": str(self.patient.id),
                "provider": self.provider.id,
                "insured_card_number": "0001234567890001",
                "competency": "2026-03",
                "cid10_codes": [{"code": "J00"}],
            },
            format="json",
        )

    # ── draft continua editável ─────────────────────────────────────────────

    def test_patch_draft_guide_still_works(self):
        guide_id = self._create_guide().json()["id"]
        client = self._auth(self.fat_token)
        resp = client.patch(
            f"/api/v1/billing/guides/{guide_id}/",
            {"competency": "2026-04"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["competency"], "2026-04")
        self.assertTrue(
            AuditLog.objects.filter(action="guide_updated", resource_id=guide_id).exists()
        )

    # ── submitted é travada ──────────────────────────────────────────────────

    def test_patch_submitted_guide_is_blocked(self):
        client = self._auth(self.fat_token)
        guide_id = self._create_guide(client).json()["id"]
        submit_resp = client.post(f"/api/v1/billing/guides/{guide_id}/submit/")
        self.assertEqual(submit_resp.status_code, 200, submit_resp.content)

        patch_resp = client.patch(
            f"/api/v1/billing/guides/{guide_id}/",
            {"competency": "2026-05", "provider": self.provider.id},
            format="json",
        )
        self.assertEqual(patch_resp.status_code, 400, patch_resp.content)

        guide = TISSGuide.objects.get(id=guide_id)
        self.assertEqual(guide.competency, "2026-03")  # não mudou
        self.assertEqual(guide.status, "submitted")

    def test_blocked_patch_writes_an_audit_row(self):
        """O bloqueio em si grava a tentativa — é o rastro que faltava.

        Não precisa isolar do audit escrito por ``submit()``: aquele usa a ação
        ``guide_{numero}_status_...→submitted``, nunca ``guide_update_blocked``
        (o ``AuditLog`` é append-only e imutável a nível de banco — ver
        ``test_auditlog_immutable.py` — então nem daria pra limpar entre passos
        mesmo que precisasse)."""
        client = self._auth(self.fat_token)
        guide_id = self._create_guide(client).json()["id"]
        client.post(f"/api/v1/billing/guides/{guide_id}/submit/")

        resp = client.patch(
            f"/api/v1/billing/guides/{guide_id}/",
            {"competency": "2026-06"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

        entry = AuditLog.objects.filter(action="guide_update_blocked", resource_id=guide_id).first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.old_data.get("status"), "submitted")
        self.assertIn("competency", entry.new_data.get("attempted_fields", []))

    def test_paid_guide_is_also_blocked(self):
        """Não é só 'submitted': qualquer estado fora de draft é imutável."""
        guide_id = self._create_guide().json()["id"]
        guide = TISSGuide.objects.get(id=guide_id)
        guide.status = "paid"
        guide.save(update_fields=["status"])

        client = self._auth(self.fat_token)
        resp = client.patch(
            f"/api/v1/billing/guides/{guide_id}/",
            {"authorization_number": "AUTH-FRAUD-1"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        guide.refresh_from_db()
        self.assertEqual(guide.authorization_number, "")

    # ── B10: authorization_date herda a mesma trava ──────────────────────────

    def test_authorization_date_is_writable_in_draft(self):
        """Contrato da API: authorization_date é editável por PATCH enquanto a
        guia é draft, formato "YYYY-MM-DD" (DateField padrão do DRF)."""
        guide_id = self._create_guide().json()["id"]
        client = self._auth(self.fat_token)
        resp = client.patch(
            f"/api/v1/billing/guides/{guide_id}/",
            {"authorization_number": "AUTH-DIGITADA", "authorization_date": "2026-08-15"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["authorization_date"], "2026-08-15")
        guide = TISSGuide.objects.get(id=guide_id)
        self.assertEqual(guide.authorization_date, datetime.date(2026, 8, 15))

    # ── Onda 4: tipo_faturamento herda a mesma trava ─────────────────────────

    def test_tipo_faturamento_is_writable_in_draft(self):
        """Contrato da API: tipo_faturamento (dm_tipoFaturamento, obrigatório na
        guia de resumo de internação) é editável por PATCH enquanto a guia é
        draft. É o único dos cinco campos de <dadosInternacao> que mora na guia e
        não na internação — logo é aqui, e só aqui, que o faturista o preenche."""
        guide_id = self._create_guide().json()["id"]
        client = self._auth(self.fat_token)
        resp = client.patch(
            f"/api/v1/billing/guides/{guide_id}/",
            {"tipo_faturamento": "2"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["tipo_faturamento"], "2")
        # O par valor/_display segue o padrão de status/guide_type. O rótulo é
        # deliberadamente "a confirmar no manual ANS" enquanto o manual não
        # estiver no repo — ver TISSGuide.TipoFaturamento.
        self.assertEqual(
            resp.json()["tipo_faturamento_display"],
            "Código 2 (rótulo a confirmar no manual ANS)",
        )
        guide = TISSGuide.objects.get(id=guide_id)
        self.assertEqual(guide.tipo_faturamento, "2")

    def test_tipo_faturamento_is_blocked_after_draft(self):
        """Depois do envio, trocar o tipo de faturamento muda o SIGNIFICADO do
        documento já transmitido: a guia declarada à operadora como parcial
        passaria a constar como de encerramento (ou o inverso), sem nenhum rastro
        no lote exportado. Mesma trava dos demais campos (Onda2 2.3)."""
        client = self._auth(self.fat_token)
        guide_id = self._create_guide(client).json()["id"]
        submit_resp = client.post(f"/api/v1/billing/guides/{guide_id}/submit/")
        self.assertEqual(submit_resp.status_code, 200, submit_resp.content)

        patch_resp = client.patch(
            f"/api/v1/billing/guides/{guide_id}/",
            {"tipo_faturamento": "3"},
            format="json",
        )
        self.assertEqual(patch_resp.status_code, 400, patch_resp.content)

        guide = TISSGuide.objects.get(id=guide_id)
        self.assertEqual(guide.tipo_faturamento, "")

    def test_authorization_date_is_blocked_after_draft(self):
        """A digitação da data de autorização só é possível antes do envio —
        depois disso a guia entra na mesma trava de imutabilidade de
        authorization_number (Onda2 2.3): editar a data pós-envio teria o
        mesmo risco de divergir do que foi transmitido à operadora."""
        client = self._auth(self.fat_token)
        guide_id = self._create_guide(client).json()["id"]
        submit_resp = client.post(f"/api/v1/billing/guides/{guide_id}/submit/")
        self.assertEqual(submit_resp.status_code, 200, submit_resp.content)

        patch_resp = client.patch(
            f"/api/v1/billing/guides/{guide_id}/",
            {"authorization_date": "2026-08-15"},
            format="json",
        )
        self.assertEqual(patch_resp.status_code, 400, patch_resp.content)

        guide = TISSGuide.objects.get(id=guide_id)
        self.assertIsNone(guide.authorization_date)
