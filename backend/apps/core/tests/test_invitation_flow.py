"""
T6: UserInvitationView + SetPasswordView + EmailService.send_user_invitation tests.

Covers:
- test_invite_creates_token_and_sends_email
- test_set_password_with_valid_token_returns_jwt
- test_set_password_clears_must_change_password
- test_set_password_consumes_invitation
- test_set_password_with_expired_token_returns_410
- test_set_password_tampered_token_returns_400
- test_set_password_short_password_returns_400
- test_employee_onboarding_invite_mode_creates_invitation

Run: pytest apps/core/tests/test_invitation_flow.py -v
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import jwt
from django.conf import settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import AuditLog, Role, User, UserInvitation
from apps.test_utils import TenantTestCase

# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_user(email="invite.test@example.com", full_name="Invite Test"):
    return User.objects.create_user(
        email=email,
        password=None,
        full_name=full_name,
    )


def _make_admin(email="admin.invite@example.com"):
    role, _ = Role.objects.get_or_create(name="admin-inv", defaults={"permissions": ["admin"]})
    return User.objects.create_user(
        email=email,
        password="Admin123!",
        full_name="Admin Invite",
        role=role,
        is_staff=True,
    )


def _make_valid_token(user):
    """Create a real 72h JWT + matching UserInvitation row (not consumed)."""
    from apps.core.views import _create_invitation_for_user

    with patch("apps.core.services.email.EmailService.send_user_invitation"):
        invitation, token = _create_invitation_for_user(user, requesting_user=user)
    return invitation, token


# ─── Tests ────────────────────────────────────────────────────────────────────


class UserInvitationFlowTests(TenantTestCase):
    """Full invitation flow tests inside a tenant schema."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        self.admin = _make_admin()
        self.invite_user = _make_user()

    # ── 1: invite creates token + sends email ─────────────────────────────────

    @patch("apps.core.services.email.EmailService.send_user_invitation")
    def test_invite_creates_token_and_sends_email(self, mock_send):
        """POST /api/v1/auth/invite/ creates UserInvitation row + emails once."""
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(
            "/api/v1/auth/invite/",
            {"user_id": str(self.invite_user.id)},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.json())
        data = resp.json()
        self.assertIn("invitation_id", data)

        # DB row created
        invitation = UserInvitation.objects.get(id=data["invitation_id"])
        self.assertEqual(invitation.user, self.invite_user)
        self.assertFalse(invitation.is_consumed)

        # Email sent exactly once
        mock_send.assert_called_once()

    # ── 2: happy path — valid token returns JWT ───────────────────────────────

    @patch("apps.core.services.email.EmailService.send_user_invitation")
    def test_set_password_with_valid_token_returns_jwt(self, _mock_send):
        """POST /api/v1/auth/set-password/<token>/ with valid token returns access + refresh."""
        _invitation, token = _make_valid_token(self.invite_user)
        resp = self.client.post(
            f"/api/v1/auth/set-password/{token}/",
            {"password": "NewPass123!"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.json())
        data = resp.json()
        self.assertIn("access", data)
        self.assertIn("refresh", data)

    # ── 3: flag cleared after set-password ───────────────────────────────────

    @patch("apps.core.services.email.EmailService.send_user_invitation")
    def test_set_password_clears_must_change_password(self, _mock_send):
        """After set-password, user.must_change_password becomes False."""
        # give the user the flag first (simulate random_password mode)
        self.invite_user.must_change_password = True
        self.invite_user.save(update_fields=["must_change_password"])

        _invitation, token = _make_valid_token(self.invite_user)
        self.client.post(
            f"/api/v1/auth/set-password/{token}/",
            {"password": "NewPass123!"},
            format="json",
        )
        self.invite_user.refresh_from_db()
        self.assertFalse(self.invite_user.must_change_password)

    # ── 4: single-use enforcement ─────────────────────────────────────────────

    @patch("apps.core.services.email.EmailService.send_user_invitation")
    def test_set_password_consumes_invitation(self, _mock_send):
        """Second use of the same token returns 400 INVITATION_ALREADY_CONSUMED."""
        invitation, token = _make_valid_token(self.invite_user)
        url = f"/api/v1/auth/set-password/{token}/"

        # First use — should succeed
        resp1 = self.client.post(url, {"password": "FirstPass1!"}, format="json")
        self.assertEqual(resp1.status_code, 200)

        # consumed_at set
        invitation.refresh_from_db()
        self.assertIsNotNone(invitation.consumed_at)

        # Second use — must be rejected
        resp2 = self.client.post(url, {"password": "SecondPass1!"}, format="json")
        self.assertEqual(resp2.status_code, 400)
        self.assertEqual(resp2.json()["error"], "INVITATION_ALREADY_CONSUMED")

    # ── 5: expired token returns 410 ─────────────────────────────────────────

    @patch("apps.core.services.email.EmailService.send_user_invitation")
    def test_set_password_with_expired_token_returns_410(self, _mock_send):
        """Expired JWT (exp in the past) returns 410 INVITATION_EXPIRED."""
        # Craft a JWT with exp already in the past
        past_exp = int((timezone.now() - timedelta(seconds=10)).timestamp())
        payload = {
            "user_id": str(self.invite_user.id),
            "purpose": "password_set",
            "exp": past_exp,
        }
        expired_token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")

        resp = self.client.post(
            f"/api/v1/auth/set-password/{expired_token}/",
            {"password": "SomePass1!"},
            format="json",
        )
        self.assertEqual(resp.status_code, 410)
        self.assertEqual(resp.json()["error"], "INVITATION_EXPIRED")

    # ── 6: tampered token returns 400 ─────────────────────────────────────────

    @patch("apps.core.services.email.EmailService.send_user_invitation")
    def test_set_password_tampered_token_returns_400(self, _mock_send):
        """A tampered token returns 400.

        Either INVALID_TOKEN (signature check fails) or INVITATION_NOT_FOUND
        (signature happens to validate but SHA-256 hash mismatches) is a valid
        defense — both deny the request. The contract is "tampered → 400",
        not the specific error code.
        """
        _invitation, token = _make_valid_token(self.invite_user)
        # Replace the entire signature segment with garbage so decode reliably
        # fails on every PyJWT version + every SECRET_KEY.
        head, _sig = token.rsplit(".", 1)
        tampered = f"{head}.notavalidsignaturexxx"

        resp = self.client.post(
            f"/api/v1/auth/set-password/{tampered}/",
            {"password": "SomePass1!"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn(resp.json()["error"], ("INVALID_TOKEN", "INVITATION_NOT_FOUND"))

    # ── 7: short password returns 400 ─────────────────────────────────────────

    @patch("apps.core.services.email.EmailService.send_user_invitation")
    def test_set_password_short_password_returns_400(self, _mock_send):
        """Password shorter than 8 characters returns 400 PASSWORD_TOO_SHORT."""
        _invitation, token = _make_valid_token(self.invite_user)
        resp = self.client.post(
            f"/api/v1/auth/set-password/{token}/",
            {"password": "short"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "PASSWORD_TOO_SHORT")

    # ── 8: EmployeeOnboardingService invite mode ──────────────────────────────

    @patch("apps.core.services.email.EmailService.send_user_invitation")
    def test_employee_onboarding_invite_mode_creates_invitation(self, mock_send):
        """EmployeeOnboardingService with auth_mode='invite' creates UserInvitation + audit."""
        from datetime import date

        from apps.hr.services import EmployeeOnboardingService

        role, _ = Role.objects.get_or_create(name="admin", defaults={"permissions": ["admin"]})
        service = EmployeeOnboardingService(requesting_user=self.admin)
        payload = {
            "full_name": "Invited Employee",
            "email": "invited.emp@example.com",
            "cpf": "",
            "phone": "",
            "role": "admin",
            "hire_date": date(2026, 5, 1),
            "contract_type": "clt",
            "employment_status": "active",
            "council_type": "",
            "council_number": "",
            "council_state": "",
            "specialty": "",
            "auth_mode": "invite",
            "password": "",
            "setup_whatsapp": False,
        }

        service.onboard(payload)

        # User created with must_change_password=False
        user = User.objects.get(email="invited.emp@example.com")
        self.assertFalse(user.must_change_password)

        # UserInvitation row created
        self.assertTrue(UserInvitation.objects.filter(user=user).exists())

        # Email sent once
        mock_send.assert_called_once()

        # AuditLog contains user_invitation_sent with correlation_id
        self.assertTrue(
            AuditLog.objects.filter(
                action="user_invitation_sent",
                new_data__correlation_id=service.correlation_id,
            ).exists()
        )
