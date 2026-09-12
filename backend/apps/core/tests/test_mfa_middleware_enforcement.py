"""
Onda 0 / item 0.6-backend — MFARequiredMiddleware Bearer-token enforcement.

The bug: MFARequiredMiddleware read ``request.user``/``request.auth`` at the
Django-middleware level. AuthenticationMiddleware only resolves
``request.user`` from the SESSION, and DRF's TenantJWTAuthentication (the
*only* entry in DEFAULT_AUTHENTICATION_CLASSES) is lazy — it runs inside the
view layer. So for every Bearer-token API request (i.e. all real API
traffic), ``request.user`` was AnonymousUser at the point the middleware
ran, and the whole MFA gate silently no-op'd. Only the session-based Django
admin was ever actually covered.

apps/emr/tests/test_mfa.py:140 (`test_mfa_required_middleware_blocks_without_claim`)
tests `apps.core.mfa.is_mfa_verified()` directly against a bare
`RequestFactory` request — never routes through Django's middleware stack —
so it could not, and did not, catch this. Every test below is a REAL HTTP
round-trip (APIClient + Bearer header) through the full middleware stack and
a real DRF view, which is the only way to prove the gate is enforced.

Run: pytest apps/core/tests/test_mfa_middleware_enforcement.py -v
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.core.models import Role, User
from apps.test_utils import MFATestMixin, TenantTestCase


class MFAMiddlewareEnforcementTests(MFATestMixin, TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain

        # "medico" is covered by the default settings.MFA_REQUIRED_ROLES.
        self.covered_role = Role.objects.create(
            name="medico", permissions=["emr.read", "emr.write"]
        )
        # "recepcionista" is NOT in the default MFA_REQUIRED_ROLES set.
        self.uncovered_role = Role.objects.create(
            name="recepcionista", permissions=["patients.read"]
        )

    def _make_user(self, role, email):
        return User.objects.create_user(
            email=email,
            password="Test123!",
            full_name="Test User",
            role=role,
        )

    def _bearer(self, token: str) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def _plain_access_token(self, user) -> str:
        """Access token with NO mfa_verified claim (ordinary login token)."""
        return str(RefreshToken.for_user(user).access_token)

    # ── (a) THE bug-reproducing case ──────────────────────────────────────────

    def test_covered_user_with_device_blocked_without_mfa_claim(self):
        """
        Covered role + active TOTP device + Bearer token WITHOUT mfa_verified
        → 403 mfa_required on a real clinical endpoint.

        This is the case that passed silently (200) on the old code, because
        the middleware never saw a resolved request.user for a Bearer request.
        """
        user = self._make_user(self.covered_role, "doc_a@test.com")
        self.create_totp_device(user, activate=True)
        self._bearer(self._plain_access_token(user))

        response = self.client.get("/api/v1/me")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "mfa_required")

    # ── (b) claim present → passes ────────────────────────────────────────────

    def test_covered_user_with_mfa_verified_claim_passes(self):
        """Same user/device as (a), but the token carries mfa_verified=True."""
        user = self._make_user(self.covered_role, "doc_b@test.com")
        self.create_totp_device(user, activate=True)
        access, _refresh = self.get_mfa_jwt_tokens(user)
        self._bearer(access)

        response = self.client.get("/api/v1/me")

        self.assertEqual(response.status_code, 200)

    # ── (c) uncovered role → never blocked ────────────────────────────────────

    def test_uncovered_role_never_blocked_even_without_device(self):
        """A role outside MFA_REQUIRED_ROLES is never gated, device or not."""
        user = self._make_user(self.uncovered_role, "front_c@test.com")
        self._bearer(self._plain_access_token(user))

        response = self.client.get("/api/v1/me")

        self.assertEqual(response.status_code, 200)

    # ── (d) exempt path → passes without claim ────────────────────────────────

    def test_exempt_path_passes_without_mfa_claim(self):
        """/auth/mfa/status/ is exempt: reachable even without mfa_verified."""
        user = self._make_user(self.covered_role, "doc_d@test.com")
        self.create_totp_device(user, activate=True)
        self._bearer(self._plain_access_token(user))

        response = self.client.get("/api/v1/auth/mfa/status/")

        self.assertNotEqual(response.status_code, 403)
        self.assertEqual(response.status_code, 200)

    # ── (e) no device — grace window ──────────────────────────────────────────

    def test_no_device_within_grace_window_passes(self):
        """No device yet, but still inside MFA_GRACE_PERIOD_DAYS → allowed."""
        user = self._make_user(self.covered_role, "doc_e1@test.com")
        # created_at is auto_now_add=True → defaults to "now", well inside
        # the default 7-day grace window.
        self._bearer(self._plain_access_token(user))

        response = self.client.get("/api/v1/me")

        self.assertEqual(response.status_code, 200)

    def test_no_device_past_grace_window_blocked(self):
        """No device, grace window expired → 403 mfa_enrollment_required."""
        user = self._make_user(self.covered_role, "doc_e2@test.com")
        User.objects.filter(pk=user.pk).update(created_at=timezone.now() - timedelta(days=30))
        self._bearer(self._plain_access_token(user))

        response = self.client.get("/api/v1/me")

        self.assertEqual(response.status_code, 403)
        body = response.json()
        self.assertEqual(body["code"], "mfa_enrollment_required")
        self.assertEqual(body["redirect"], "/auth/mfa/setup")

    # ── (f) fail-closed, not fail-500 ─────────────────────────────────────────

    def test_no_authorization_header_returns_401_not_500_not_403(self):
        """
        No credentials at all → the middleware must NOT become a parallel
        authenticator (no 500 from a raised exception, no 403 of its own).
        DRF's IsAuthenticated is the one that produces the 401.
        """
        response = self.client.get("/api/v1/me")

        self.assertEqual(response.status_code, 401)

    def test_malformed_bearer_token_returns_401_not_500(self):
        """
        A syntactically present but garbage/invalid Bearer token must not
        crash the middleware — it should fall through to the view, which
        rejects it with a normal DRF 401.
        """
        self._bearer("not-a-real-jwt")

        response = self.client.get("/api/v1/me")

        self.assertEqual(response.status_code, 401)
