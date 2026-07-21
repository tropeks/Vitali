"""
Integration tests for patient portal invite delivery (issue #117).

Covers both delivery channels wired to `PatientPortalAccess.invite_token`:

- WhatsApp (primary) — gated on an opted-in `WhatsAppContact`.
- Email (fallback) — used when WhatsApp is unavailable and an address exists.

The admin REST surface (`POST /api/v1/portal/access/`) must trigger delivery
so that creating an invite actually reaches the patient.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from django.core import mail
from django.test import override_settings
from rest_framework.test import APIClient

from apps.core.models import FeatureFlag, Role, User
from apps.emr.models import Patient
from apps.patient_portal.models import PatientPortalAccess
from apps.patient_portal.services import build_activation_url, deliver_portal_invite
from apps.test_utils import TenantTestCase
from apps.whatsapp.models import WhatsAppContact

ACCESS_URL = "/api/v1/portal/access/"

# Where the service looks up the gateway (local import inside _try_whatsapp).
GATEWAY_PATH = "apps.whatsapp.gateway.get_gateway"


def _make_user(*, role_name: str, perms: list[str], email: str, full_name: str) -> User:
    role, _ = Role.objects.get_or_create(name=role_name, defaults={"permissions": perms})
    role.permissions = perms
    role.save()
    return User.objects.create_user(email=email, password="pw", role=role, full_name=full_name)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="noreply@vitali.test",
    FRONTEND_URL="https://portal.vitali.test",
)
class InviteDeliveryServiceTest(TenantTestCase):
    """Direct tests of the delivery service (both channels + gates)."""

    def setUp(self):
        mail.outbox = []
        self.patient = Patient.objects.create(
            full_name="Ana Maria Souza",
            cpf="12345678909",
            birth_date=date(1985, 7, 14),
            gender="F",
            whatsapp="5511988887777",
            email="ana@email.test",
        )
        self.user = _make_user(
            role_name="portal_self",
            perms=["portal.self_access"],
            email="ana_portal@test.com",
            full_name="Ana Maria Souza",
        )

    def _mint(self) -> PatientPortalAccess:
        return PatientPortalAccess.objects.create(user=self.user, patient=self.patient)

    # ─── WhatsApp channel ──────────────────────────────────────────────────────

    def test_whatsapp_sent_when_contact_opted_in(self):
        WhatsAppContact.objects.create(phone="5511988887777", patient=self.patient, opt_in=True)
        access = self._mint()

        with patch(GATEWAY_PATH) as mock_get_gateway:
            gateway = MagicMock()
            mock_get_gateway.return_value = gateway
            channels = deliver_portal_invite(access)

        self.assertEqual(channels, ["whatsapp"])
        gateway.send_text.assert_called_once()
        to, text = gateway.send_text.call_args.args
        self.assertEqual(to, "5511988887777")
        self.assertIn(access.invite_token, text)
        self.assertIn("https://portal.vitali.test/portal/activate", text)
        # WhatsApp succeeded → no email fallback.
        self.assertEqual(len(mail.outbox), 0)

    def test_no_whatsapp_without_opt_in_falls_back_to_email(self):
        # Contact exists but has NOT opted in → WhatsApp gate closed.
        WhatsAppContact.objects.create(phone="5511988887777", patient=self.patient, opt_in=False)
        access = self._mint()

        with patch(GATEWAY_PATH) as mock_get_gateway:
            gateway = MagicMock()
            mock_get_gateway.return_value = gateway
            channels = deliver_portal_invite(access)

        gateway.send_text.assert_not_called()
        self.assertEqual(channels, ["email"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("ana@email.test", mail.outbox[0].to)

    # ─── Email fallback channel ────────────────────────────────────────────────

    def test_email_fallback_when_no_whatsapp_contact(self):
        access = self._mint()  # no WhatsAppContact at all
        channels = deliver_portal_invite(access)

        self.assertEqual(channels, ["email"])
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertIn("ana@email.test", msg.to)
        self.assertIn(build_activation_url(access), msg.body)

    def test_no_channel_when_neither_available(self):
        self.patient.email = ""
        self.patient.save(update_fields=["email"])
        access = self._mint()

        channels = deliver_portal_invite(access)

        self.assertEqual(channels, [])
        self.assertEqual(len(mail.outbox), 0)

    def test_whatsapp_send_failure_falls_back_to_email(self):
        WhatsAppContact.objects.create(phone="5511988887777", patient=self.patient, opt_in=True)
        access = self._mint()

        with patch(GATEWAY_PATH) as mock_get_gateway:
            gateway = MagicMock()
            gateway.send_text.side_effect = RuntimeError("evolution down")
            mock_get_gateway.return_value = gateway
            channels = deliver_portal_invite(access)

        # Send raised → fail-open → email fallback kicks in.
        self.assertEqual(channels, ["email"])
        self.assertEqual(len(mail.outbox), 1)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="noreply@vitali.test",
    FRONTEND_URL="https://portal.vitali.test",
)
class InviteDeliveryViewTest(TenantTestCase):
    """The admin create endpoint must trigger delivery on invite creation."""

    def setUp(self):
        mail.outbox = []
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="patient_portal",
            defaults={"is_enabled": True},
        )
        self.admin = _make_user(
            role_name="portal_admin",
            perms=["users.read", "users.write"],
            email="admin_p@test.com",
            full_name="Admin",
        )
        self.patient = Patient.objects.create(
            full_name="Ana Maria Souza",
            cpf="12345678909",
            birth_date=date(1985, 7, 14),
            gender="F",
            whatsapp="5511988887777",
            email="ana@email.test",
        )
        self.patient_user = _make_user(
            role_name="portal_self",
            perms=["portal.self_access"],
            email="ana_portal@test.com",
            full_name="Ana Maria Souza",
        )

    def test_create_invite_delivers_whatsapp(self):
        WhatsAppContact.objects.create(phone="5511988887777", patient=self.patient, opt_in=True)
        self.client.force_authenticate(user=self.admin)
        with patch(GATEWAY_PATH) as mock_get_gateway:
            gateway = MagicMock()
            mock_get_gateway.return_value = gateway
            resp = self.client.post(
                ACCESS_URL,
                {"user": self.patient_user.pk, "patient": str(self.patient.pk)},
                format="json",
            )
        self.assertEqual(resp.status_code, 201, resp.data)
        gateway.send_text.assert_called_once()
        self.assertEqual(len(mail.outbox), 0)

    def test_create_invite_delivers_email_fallback(self):
        # No opted-in WhatsApp contact → email fallback.
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(
            ACCESS_URL,
            {"user": self.patient_user.pk, "patient": str(self.patient.pk)},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("ana@email.test", mail.outbox[0].to)
