"""
Authz tests for PIXChargeView (CSO finding — billing endpoint missing role gate).

PIXChargeView was the only billing endpoint gated on ``[IsAuthenticated]`` alone.
It must align with the rest of billing: ``[IsAuthenticated, _BILLING_MODULE,
IsFaturistaOrAdmin]``. A non-billing role (e.g. clinical emr.read) gets 403; a
faturista creates the charge.
"""

from unittest.mock import MagicMock, patch

from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.core.models import FeatureFlag, Role, User
from apps.emr.models import Appointment, Patient, Professional
from apps.test_utils import TenantTestCase


def _future(minutes=30):
    return timezone.now() + timezone.timedelta(minutes=minutes)


@override_settings(ASAAS_API_KEY="test-key", ASAAS_WEBHOOK_TOKEN="test-webhook-token")
class PIXChargeAuthzTest(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain

        # Billing module active so the test isolates the ROLE gate.
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant, module_key="billing", defaults={"is_enabled": True}
        )

        self.faturista_role = Role.objects.create(
            name="faturista_pix_authz", permissions=["billing.read", "billing.write"]
        )
        # Clinical role: no billing.* → must be denied.
        self.clinical_role = Role.objects.create(
            name="enfermeiro_pix_authz", permissions=["emr.read"]
        )

        self.faturista = User.objects.create_user(
            email="faturista_pix_authz@test.com",
            password="pass123",
            role=self.faturista_role,
        )
        self.clinical = User.objects.create_user(
            email="enf_pix_authz@test.com",
            password="pass123",
            role=self.clinical_role,
        )

        self.patient = Patient.objects.create(
            full_name="Authz Patient",
            birth_date="1990-01-01",
            gender="M",
        )
        self.professional = Professional.objects.create(
            user=self.faturista,
            council_type="CRM",
            council_number="54321",
            council_state="SP",
        )
        now = timezone.now()
        self.appointment = Appointment.objects.create(
            patient=self.patient,
            professional=self.professional,
            start_time=now + timezone.timedelta(hours=1),
            end_time=now + timezone.timedelta(hours=2),
            status="scheduled",
        )

    def test_non_faturista_denied(self):
        """A clinical (non-billing) role gets 403 creating a PIX charge."""
        self.client.force_authenticate(self.clinical)
        r = self.client.post(
            "/api/v1/billing/pix/charges/",
            {"appointment_id": str(self.appointment.id), "amount": "150.00"},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    @patch("apps.billing.views.AsaasService")
    def test_faturista_allowed(self, mock_asaas_cls):
        """A faturista creates the PIX charge (201)."""
        mock_svc = MagicMock()
        mock_asaas_cls.return_value = mock_svc
        mock_svc.create_pix_charge.return_value = {
            "asaas_charge_id": "pay_authz_001",
            "asaas_customer_id": "cus_authz_001",
            "pix_copy_paste": "00020126test",
            "pix_qr_code_base64": "base64data",
            "expires_at": _future(30),
        }

        self.client.force_authenticate(self.faturista)
        r = self.client.post(
            "/api/v1/billing/pix/charges/",
            {"appointment_id": str(self.appointment.id), "amount": "150.00"},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data["status"], "pending")
