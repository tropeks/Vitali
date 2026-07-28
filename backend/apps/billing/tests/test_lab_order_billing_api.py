"""
A5-T1 — Endpoint: faturar LabOrder finalizado → guia TISS SP/SADT.

Exercises POST /api/v1/billing/guides/from-lab-order/ which wraps the
``generate_sadt_guide_for_lab_order`` service:
  * success creates a draft SADT guide with priced items (201);
  * each precondition failure maps to HTTP 400 with the service's message;
  * a missing lab order → 404; a malformed body → 400;
  * re-billing the same order is idempotent (200, same guide);
  * billing permissions gate the endpoint (enfermeiro → 403).
"""

import datetime
from decimal import Decimal

from rest_framework.test import APIClient

from apps.billing.models import (
    InsuranceProvider,
    PriceTable,
    PriceTableItem,
    TISSGuide,
)
from apps.core.models import FeatureFlag, Role, TUSSCode, User
from apps.emr.models import (
    Encounter,
    LabOrder,
    LabOrderItem,
    LabTest,
    Patient,
    PatientInsurance,
    Professional,
)
from apps.test_utils import TenantTestCase

FROM_LAB_ORDER_URL = "/api/v1/billing/guides/from-lab-order/"


class LabOrderBillingAPITestCase(TenantTestCase):
    def setUp(self):
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant, module_key="billing", defaults={"is_enabled": True}
        )
        self.faturista_role = Role.objects.create(
            name="faturista",
            permissions=["billing.read", "billing.write"],
            is_system=True,
        )
        self.enfermeiro_role = Role.objects.create(
            name="enfermeiro", permissions=["emr.read"], is_system=True
        )
        self.faturista = User.objects.create_user(
            email="faturista@test.com",
            full_name="Faturista Test",
            password="Str0ng!Pass#2024",
            role=self.faturista_role,
        )
        self.enfermeiro = User.objects.create_user(
            email="enfermeiro@test.com",
            full_name="Enfermeiro Test",
            password="Str0ng!Pass#2024",
            role=self.enfermeiro_role,
        )
        prof_user = User.objects.create_user(
            email="medico@test.com",
            full_name="Dr. Test",
            password="Str0ng!Pass#2024",
            role=self.faturista_role,
        )
        self.patient = Patient.objects.create(
            full_name="Bill Paciente", birth_date="1980-01-01", gender="M", cpf="54444444444"
        )
        self.professional = Professional.objects.create(
            user=prof_user, council_type="CRM", council_number="B-1", council_state="SP"
        )
        self.encounter = Encounter.objects.create(
            patient=self.patient, professional=self.professional
        )
        self.provider = InsuranceProvider.objects.create(name="Unimed Test", ans_code="333333")
        self.insurance = PatientInsurance.objects.create(
            patient=self.patient,
            provider_ans_code="333333",
            provider_name="Unimed Test",
            card_number="9990001112223",
            is_active=True,
        )
        self.tuss_hb = TUSSCode.objects.create(
            code="40304361", description="Hemograma", group="procedimento", version="2024-01"
        )
        self.tuss_gluc = TUSSCode.objects.create(
            code="40302024", description="Glicose", group="procedimento", version="2024-01"
        )
        self.test_hb = LabTest.objects.create(code="40304361", name="Hemograma")
        self.test_gluc = LabTest.objects.create(code="40302024", name="Glicose")
        self.price_table = PriceTable.objects.create(
            provider=self.provider,
            name="Unimed 2026",
            valid_from=datetime.date(2026, 1, 1),
            is_active=True,
        )
        PriceTableItem.objects.create(
            table=self.price_table, tuss_code=self.tuss_hb, negotiated_value=Decimal("50.00")
        )
        PriceTableItem.objects.create(
            table=self.price_table, tuss_code=self.tuss_gluc, negotiated_value=Decimal("30.00")
        )

        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        self.client.force_authenticate(user=self.faturista)

    # ── helpers ────────────────────────────────────────────────────────────
    def _client_for(self, user):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user=user)
        return c

    def _make_order(self, *, status=LabOrder.Status.COMPLETED, encounter=True, tuss=True):
        order = LabOrder.objects.create(
            patient=self.patient,
            encounter=self.encounter if encounter else None,
            requested_by=self.faturista,
            status=status,
        )
        if tuss:
            for test in (self.test_hb, self.test_gluc):
                LabOrderItem.objects.create(order=order, test=test, test_name=test.name)
        else:
            internal = LabTest.objects.create(code="INTERNAL-XYZ", name="Exame interno")
            LabOrderItem.objects.create(order=order, test=internal, test_name="Exame interno")
        return order

    def _post(self, lab_order_id):
        return self.client.post(FROM_LAB_ORDER_URL, {"lab_order": str(lab_order_id)}, format="json")

    # ── success ────────────────────────────────────────────────────────────
    def test_bills_completed_order_into_draft_sadt_guide(self):
        order = self._make_order()
        resp = self._post(order.id)
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body["guide_type"], "sadt")
        self.assertEqual(body["status"], "draft")
        self.assertEqual(len(body["items"]), 2)
        self.assertEqual(body["total_value"], "80.00")
        self.assertEqual(TISSGuide.objects.filter(lab_order=order).count(), 1)

    def test_rebilling_is_idempotent_returns_same_guide(self):
        order = self._make_order()
        first = self._post(order.id)
        self.assertEqual(first.status_code, 201, first.content)
        second = self._post(order.id)
        self.assertEqual(second.status_code, 200, second.content)
        self.assertEqual(first.json()["id"], second.json()["id"])
        self.assertEqual(TISSGuide.objects.filter(lab_order=order).count(), 1)

    # ── precondition failures → 400 ──────────────────────────────────────────
    def test_not_completed_order_returns_400(self):
        order = self._make_order(status=LabOrder.Status.IN_PROGRESS)
        resp = self._post(order.id)
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn("concluídos", str(resp.json()))
        self.assertFalse(TISSGuide.objects.filter(lab_order=order).exists())

    def test_no_encounter_returns_400(self):
        order = self._make_order(encounter=False)
        resp = self._post(order.id)
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn("atendimento", str(resp.json()))

    def test_no_active_insurance_returns_400(self):
        PatientInsurance.objects.filter(patient=self.patient).update(is_active=False)
        order = self._make_order()
        resp = self._post(order.id)
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn("convênio", str(resp.json()))

    def test_unregistered_provider_returns_400(self):
        PatientInsurance.objects.filter(patient=self.patient).update(provider_ans_code="000000")
        order = self._make_order()
        resp = self._post(order.id)
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn("não cadastrada", str(resp.json()))

    def test_no_billable_tuss_items_returns_400(self):
        order = self._make_order(tuss=False)
        resp = self._post(order.id)
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn("faturáveis", str(resp.json()))
        self.assertFalse(TISSGuide.objects.filter(lab_order=order).exists())

    # ── input / not-found / permission ───────────────────────────────────────
    def test_missing_lab_order_field_returns_400(self):
        resp = self.client.post(FROM_LAB_ORDER_URL, {}, format="json")
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_unknown_lab_order_returns_404(self):
        resp = self._post("00000000-0000-0000-0000-000000000000")
        self.assertEqual(resp.status_code, 404, resp.content)

    def test_non_billing_role_forbidden(self):
        order = self._make_order()
        c = self._client_for(self.enfermeiro)
        resp = c.post(FROM_LAB_ORDER_URL, {"lab_order": str(order.id)}, format="json")
        self.assertEqual(resp.status_code, 403, resp.content)
