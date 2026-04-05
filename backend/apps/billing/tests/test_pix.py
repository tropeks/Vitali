"""
S-055 tests: PIX charge creation, webhook idempotency, expiry.

Critical tests from the Sprint 14 test plan:
1. Duplicate webhook fires only once (select_for_update idempotency)
2. AsaasService uses hmac.compare_digest (no timing attack on token)
3. PIXChargeView is idempotent (returns existing pending charge)
4. expire_pix_charges task transitions status correctly
"""
import hmac
import uuid
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import override_settings
from django.utils import timezone
from django_tenants.test.cases import TenantTestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.billing.models import PIXCharge
from apps.billing.services.tasks import expire_pix_charges
from apps.core.models import FeatureFlag, Role, User
from apps.emr.models import Appointment, Patient, Professional


def _future(minutes=30):
    return timezone.now() + timezone.timedelta(minutes=minutes)


def _past(minutes=5):
    return timezone.now() - timezone.timedelta(minutes=minutes)


@override_settings(ASAAS_API_KEY="test-key", ASAAS_WEBHOOK_TOKEN="test-webhook-token")
class PIXChargeViewTest(TenantTestCase):
    """PIXChargeView — create and fetch charges."""

    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain

        self.user = User.objects.create_user(
            email="doc@test.com",
            password="pass123",
            schema_name=self.tenant.schema_name,
        )
        self.client.force_authenticate(self.user)

        self.patient = Patient.objects.create(
            full_name="Test Patient",
            date_of_birth="1990-01-01",
            sex="M",
        )
        self.professional = Professional.objects.create(
            user=self.user,
            council_type="CRM",
            council_number="12345",
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

    @patch("apps.billing.views.AsaasService")
    def test_create_pix_charge(self, mock_asaas_cls):
        """POST /billing/pix/charges/ creates a PIXCharge and returns pix data."""
        mock_svc = MagicMock()
        mock_asaas_cls.return_value = mock_svc
        mock_svc.create_pix_charge.return_value = {
            "asaas_charge_id": "pay_test_001",
            "asaas_customer_id": "cus_test_001",
            "pix_copy_paste": "00020126test",
            "pix_qr_code_base64": "base64data",
            "expires_at": _future(30),
        }

        r = self.client.post("/api/v1/billing/pix/charges/", {
            "appointment_id": str(self.appointment.id),
            "amount": "150.00",
        }, format="json")

        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data["status"], "pending")
        self.assertEqual(r.data["pix_copy_paste"], "00020126test")
        self.assertTrue(PIXCharge.objects.filter(appointment=self.appointment).exists())

    @patch("apps.billing.views.AsaasService")
    def test_create_pix_charge_idempotent(self, mock_asaas_cls):
        """POST when pending charge exists returns existing charge (no new Asaas call)."""
        existing = PIXCharge.objects.create(
            appointment=self.appointment,
            asaas_charge_id="pay_existing_001",
            amount=Decimal("150.00"),
            status=PIXCharge.Status.PENDING,
            pix_copy_paste="existing-code",
            pix_qr_code_base64="",
            expires_at=_future(30),
        )

        r = self.client.post("/api/v1/billing/pix/charges/", {
            "appointment_id": str(self.appointment.id),
            "amount": "150.00",
        }, format="json")

        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["id"], str(existing.id))
        mock_asaas_cls.assert_not_called()  # no new Asaas API call


@override_settings(ASAAS_API_KEY="test-key", ASAAS_WEBHOOK_TOKEN="test-webhook-token")
class AsaasWebhookTest(TenantTestCase):
    """AsaasWebhookView — token validation, idempotency, payment flow."""

    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain

        self.user = User.objects.create_user(
            email="doc2@test.com",
            password="pass123",
            schema_name=self.tenant.schema_name,
        )
        patient = Patient.objects.create(
            full_name="Webhook Patient",
            date_of_birth="1985-06-15",
            sex="F",
        )
        professional = Professional.objects.create(
            user=self.user,
            council_type="CRM",
            council_number="99999",
            council_state="RJ",
        )
        now = timezone.now()
        appointment = Appointment.objects.create(
            patient=patient,
            professional=professional,
            start_time=now + timezone.timedelta(hours=2),
            end_time=now + timezone.timedelta(hours=3),
            status="scheduled",
        )
        self.charge = PIXCharge.objects.create(
            appointment=appointment,
            asaas_charge_id="pay_webhook_001",
            amount=Decimal("200.00"),
            status=PIXCharge.Status.PENDING,
            pix_copy_paste="webhook-code",
            pix_qr_code_base64="",
            expires_at=_future(30),
        )

        # Create AsaasChargeMap entry in public schema
        from apps.core.models import AsaasChargeMap
        AsaasChargeMap.objects.get_or_create(
            asaas_charge_id="pay_webhook_001",
            defaults={"tenant_schema": self.tenant.schema_name},
        )

    def _webhook_payload(self, charge_id="pay_webhook_001", event="PAYMENT_RECEIVED"):
        return {
            "event": event,
            "payment": {
                "id": charge_id,
                "status": "RECEIVED",
                "value": 200.00,
            },
        }

    def test_webhook_invalid_token_rejected(self):
        """Webhook with wrong token returns 401."""
        r = self.client.post(
            "/api/v1/billing/pix/webhook/",
            self._webhook_payload(),
            format="json",
            HTTP_ASAAS_ACCESS_TOKEN="wrong-token",
        )
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_webhook_valid_token_accepted(self):
        """Webhook with correct token processes payment."""
        r = self.client.post(
            "/api/v1/billing/pix/webhook/",
            self._webhook_payload(),
            format="json",
            HTTP_ASAAS_ACCESS_TOKEN="test-webhook-token",
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.charge.refresh_from_db()
        self.assertEqual(self.charge.status, PIXCharge.Status.PAID)
        self.assertIsNotNone(self.charge.paid_at)

    def test_webhook_idempotent_duplicate(self):
        """Duplicate PAYMENT_RECEIVED for already-paid charge is a no-op."""
        # First webhook
        self.client.post(
            "/api/v1/billing/pix/webhook/",
            self._webhook_payload(),
            format="json",
            HTTP_ASAAS_ACCESS_TOKEN="test-webhook-token",
        )
        self.charge.refresh_from_db()
        self.assertEqual(self.charge.status, PIXCharge.Status.PAID)
        paid_at_first = self.charge.paid_at

        # Second duplicate webhook
        self.client.post(
            "/api/v1/billing/pix/webhook/",
            self._webhook_payload(),
            format="json",
            HTTP_ASAAS_ACCESS_TOKEN="test-webhook-token",
        )
        self.charge.refresh_from_db()
        # Still paid, paid_at unchanged
        self.assertEqual(self.charge.status, PIXCharge.Status.PAID)
        self.assertEqual(self.charge.paid_at, paid_at_first)

    def test_webhook_uses_hmac_compare_digest(self):
        """Token comparison must use hmac.compare_digest (no timing oracle)."""
        # This test verifies the code path exists by importing and checking
        # it is not a naive == comparison.
        from apps.billing.views import AsaasWebhookView
        import inspect
        source = inspect.getsource(AsaasWebhookView)
        self.assertIn("compare_digest", source)
        self.assertNotIn("token == ", source)


class PIXChargeExpiryTaskTest(TenantTestCase):
    """S-055: expire_pix_charges Celery task."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="doc3@test.com",
            password="pass123",
            schema_name=self.tenant.schema_name,
        )
        patient = Patient.objects.create(
            full_name="Expiry Patient",
            date_of_birth="1970-01-01",
            sex="M",
        )
        professional = Professional.objects.create(
            user=self.user,
            council_type="CRM",
            council_number="77777",
            council_state="MG",
        )
        now = timezone.now()
        appointment = Appointment.objects.create(
            patient=patient,
            professional=professional,
            start_time=now + timezone.timedelta(hours=3),
            end_time=now + timezone.timedelta(hours=4),
            status="scheduled",
        )
        self.expired_charge = PIXCharge.objects.create(
            appointment=appointment,
            asaas_charge_id="pay_expiry_001",
            amount=Decimal("100.00"),
            status=PIXCharge.Status.PENDING,
            pix_copy_paste="expiry-code",
            pix_qr_code_base64="",
            expires_at=_past(5),  # 5 minutes in the past
        )

    def test_expire_pix_charges_updates_status(self):
        """expire_pix_charges marks past-expiry PENDING charges as EXPIRED."""
        expire_pix_charges()
        self.expired_charge.refresh_from_db()
        self.assertEqual(self.expired_charge.status, PIXCharge.Status.EXPIRED)

    def test_expire_pix_charges_does_not_touch_paid(self):
        """expire_pix_charges does not modify already-paid charges."""
        self.expired_charge.status = PIXCharge.Status.PAID
        self.expired_charge.save(update_fields=["status"])

        expire_pix_charges()
        self.expired_charge.refresh_from_db()
        self.assertEqual(self.expired_charge.status, PIXCharge.Status.PAID)
