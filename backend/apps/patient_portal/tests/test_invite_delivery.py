"""
Integration tests for patient portal invite delivery (issue #117).

Covers both delivery channels wired to `PatientPortalAccess.invite_token`:

- WhatsApp (primary) — routed through the apps.core notifier port
  (`apps.core.whatsapp_bridge`) so patient_portal never imports apps.whatsapp
  directly (P1-01 domain-independence contract). The opt_in gate + gateway are
  exercised in apps/whatsapp/tests/test_notifier.py.
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

ACCESS_URL = "/api/v1/portal/access/"

# Where _try_whatsapp resolves the notifier port (local import at call time).
NOTIFIER_PATH = "apps.core.whatsapp_bridge.get_patient_whatsapp_notifier"


def _make_user(*, role_name: str, perms: list[str], email: str, full_name: str) -> User:
    role, _ = Role.objects.get_or_create(name=role_name, defaults={"permissions": perms})
    role.permissions = perms
    role.save()
    return User.objects.create_user(email=email, password="pw", role=role, full_name=full_name)


def _notifier(sends: bool) -> MagicMock:
    """A stub PatientWhatsAppNotifier whose send returns ``sends``."""
    m = MagicMock()
    m.send_text_to_opted_in_patient.return_value = sends
    return m


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

    def test_whatsapp_sent_when_notifier_delivers(self):
        access = self._mint()
        notifier = _notifier(sends=True)

        with patch(NOTIFIER_PATH, return_value=notifier):
            channels = deliver_portal_invite(access)

        self.assertEqual(channels, ["whatsapp"])
        notifier.send_text_to_opted_in_patient.assert_called_once()
        kwargs = notifier.send_text_to_opted_in_patient.call_args.kwargs
        self.assertEqual(kwargs["patient"], self.patient)
        self.assertIn(access.invite_token, kwargs["text"])
        self.assertIn("https://portal.vitali.test/portal/activate", kwargs["text"])
        # WhatsApp succeeded → no email fallback.
        self.assertEqual(len(mail.outbox), 0)

    def test_falls_back_to_email_when_notifier_declines(self):
        # Notifier reports no delivery (no opted-in contact / not opted in /
        # send failed — all collapse to False at this layer) → email fallback.
        access = self._mint()
        notifier = _notifier(sends=False)

        with patch(NOTIFIER_PATH, return_value=notifier):
            channels = deliver_portal_invite(access)

        notifier.send_text_to_opted_in_patient.assert_called_once()
        self.assertEqual(channels, ["email"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("ana@email.test", mail.outbox[0].to)

    def test_falls_back_to_email_when_no_notifier_registered(self):
        access = self._mint()

        with patch(NOTIFIER_PATH, return_value=None):
            channels = deliver_portal_invite(access)

        self.assertEqual(channels, ["email"])
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertIn("ana@email.test", msg.to)
        self.assertIn(build_activation_url(access), msg.body)

    # ─── No channel ────────────────────────────────────────────────────────────

    def test_no_channel_when_neither_available(self):
        self.patient.email = ""
        self.patient.save(update_fields=["email"])
        access = self._mint()

        with patch(NOTIFIER_PATH, return_value=_notifier(sends=False)):
            channels = deliver_portal_invite(access)

        self.assertEqual(channels, [])
        self.assertEqual(len(mail.outbox), 0)


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

    def _post(self):
        return self.client.post(
            ACCESS_URL,
            {"user": self.patient_user.pk, "patient": str(self.patient.pk)},
            format="json",
        )

    def test_create_invite_delivers_whatsapp(self):
        self.client.force_authenticate(user=self.admin)
        notifier = _notifier(sends=True)
        with patch(NOTIFIER_PATH, return_value=notifier):
            resp = self._post()
        self.assertEqual(resp.status_code, 201, resp.data)
        notifier.send_text_to_opted_in_patient.assert_called_once()
        self.assertEqual(len(mail.outbox), 0)

    def test_create_invite_delivers_email_fallback(self):
        # No WhatsApp delivery → email fallback.
        self.client.force_authenticate(user=self.admin)
        with patch(NOTIFIER_PATH, return_value=_notifier(sends=False)):
            resp = self._post()
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("ana@email.test", mail.outbox[0].to)
