"""S5-T2 — PIX payment of open receivables through the patient portal."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.billing.models import AccountsReceivable, InsuranceProvider, PIXCharge, TISSGuide
from apps.core.models import AuditLog, FeatureFlag, Role, User
from apps.emr.models import Appointment, Encounter, Patient, Professional
from apps.patient_portal.models import PatientPortalAccess, PortalConsent
from apps.patient_portal.transactional_models import PortalPixPayment
from apps.test_utils import TenantTestCase

RECEIVABLES_URL = "/api/v1/portal/me/receivables/"


def _pix_url(pk):
    return f"/api/v1/portal/me/receivables/{pk}/pix/"


def _make_user(*, role_name, perms, email, full_name):
    role, _ = Role.objects.get_or_create(name=role_name, defaults={"permissions": perms})
    role.permissions = perms
    role.save()
    return User.objects.create_user(email=email, password="pw", role=role, full_name=full_name)


def _fake_charge_data():
    return {
        "asaas_charge_id": "pay_portal_123",
        "asaas_customer_id": "cus_1",
        "pix_copy_paste": "00020126PIX",
        "pix_qr_code_base64": "QRDATA",
        "expires_at": timezone.now() + timedelta(minutes=30),
    }


@override_settings(ASAAS_API_KEY="test-key")
class PortalPixTest(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="patient_portal",
            defaults={"is_enabled": True},
        )
        self.admin = _make_user(
            role_name="pix_admin",
            perms=["users.read", "users.write"],
            email="admin_x@test.com",
            full_name="Admin",
        )
        self.md_user = _make_user(
            role_name="md_x", perms=["users.read"], email="md_x@test.com", full_name="Dra Bia"
        )
        self.md = Professional.objects.create(
            user=self.md_user, council_type="CRM", council_number="700501", council_state="SP"
        )
        self.provider = InsuranceProvider.objects.create(name="Bradesco", ans_code="888888")

        self.patient = Patient.objects.create(
            full_name="Ana Souza", cpf="12345678909", birth_date=date(1985, 7, 14), gender="F"
        )
        self.patient_user = _make_user(
            role_name="pix_self",
            perms=["portal.self_access"],
            email="ana_x@test.com",
            full_name="Ana Souza",
        )
        access = PatientPortalAccess.objects.create(
            user=self.patient_user, patient=self.patient, created_by=self.admin
        )
        access.activate()
        self.consent = PortalConsent.objects.create(
            patient=self.patient,
            granted_by=self.patient_user,
            purpose="portal_payment",
            policy_version="1.0",
        )
        self.receivable = self._make_receivable(
            self.patient, Decimal("150.00"), offset_h=1, guide_number="202607000501"
        )

        # A second patient with their own receivable (isolation).
        self.other_patient = Patient.objects.create(
            full_name="Bruno Lima", cpf="98765432100", birth_date=date(1990, 3, 1), gender="M"
        )
        self.other_receivable = self._make_receivable(
            self.other_patient, Decimal("99.00"), offset_h=5, guide_number="202607000502"
        )

        self.client.force_authenticate(user=self.patient_user)

    def _make_receivable(self, patient, amount, offset_h, guide_number):
        appt = Appointment.objects.create(
            patient=patient,
            professional=self.md,
            start_time=timezone.now() + timedelta(days=1, hours=offset_h),
            end_time=timezone.now() + timedelta(days=1, hours=offset_h + 1),
            status="scheduled",
        )
        encounter = Encounter.objects.create(
            patient=patient, professional=self.md, appointment=appt, status="signed"
        )
        guide = TISSGuide.objects.create(
            guide_number=guide_number,
            guide_type="consultation",
            encounter=encounter,
            patient=patient,
            provider=self.provider,
            insured_card_number="1234567890000001",
            competency="2026-07",
        )
        return AccountsReceivable.objects.create(guide=guide, amount=amount, status="billed")

    # ── list ─────────────────────────────────────────────────────────────────

    def test_lists_only_own_open_receivables(self):
        resp = self.client.get(RECEIVABLES_URL)
        self.assertEqual(resp.status_code, 200, resp.data)
        ids = {r["id"] for r in resp.data}
        self.assertIn(str(self.receivable.pk), ids)
        self.assertNotIn(str(self.other_receivable.pk), ids)

    # ── pix ────────────────────────────────────────────────────────────────

    @patch("apps.patient_portal.views_transactional.AsaasService")
    def test_initiates_pix_charge(self, mock_asaas_cls):
        instance = MagicMock()
        instance.create_pix_charge.return_value = _fake_charge_data()
        mock_asaas_cls.return_value = instance

        resp = self.client.post(_pix_url(self.receivable.pk), {}, format="json")
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data["amount"], "150.00")
        self.assertEqual(resp.data["pix_copy_paste"], "00020126PIX")
        self.assertEqual(PIXCharge.objects.count(), 1)
        payment = PortalPixPayment.objects.get(patient=self.patient)
        self.assertEqual(payment.receivable_ref, str(self.receivable.pk))
        self.assertEqual(payment.amount, Decimal("150.00"))
        self.assertTrue(AuditLog.objects.filter(action="portal_pix_charge_initiated").exists())

    @patch("apps.patient_portal.views_transactional.AsaasService")
    def test_cannot_pay_other_patients_receivable(self, mock_asaas_cls):
        instance = MagicMock()
        instance.create_pix_charge.return_value = _fake_charge_data()
        mock_asaas_cls.return_value = instance

        resp = self.client.post(_pix_url(self.other_receivable.pk), {}, format="json")
        self.assertEqual(resp.status_code, 404, resp.data)
        self.assertEqual(PIXCharge.objects.count(), 0)

    @patch("apps.patient_portal.views_transactional.AsaasService")
    def test_pix_requires_lgpd_consent(self, mock_asaas_cls):
        self.consent.revoked_at = timezone.now()
        self.consent.save(update_fields=["revoked_at"])
        resp = self.client.post(_pix_url(self.receivable.pk), {}, format="json")
        self.assertEqual(resp.status_code, 403, resp.data)
        self.assertEqual(PIXCharge.objects.count(), 0)
