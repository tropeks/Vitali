"""
S-076-NEW: PasswordChangeRequiredMiddleware unit tests.

Covers:
  - Unauthenticated requests pass through (no middleware block)
  - Authenticated user without must_change_password flag passes through
  - Authenticated user with flag blocked on non-allowlisted paths
  - Allowlist paths (/api/v1/auth/password, /api/v1/auth/logout, /api/v1/me)
    are not blocked even when flag is True
  - ChangePasswordView clears must_change_password on success

Run: pytest apps/core/tests/test_password_change_required_middleware.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock

from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings
from rest_framework.test import APIClient

from apps.core.middleware import PasswordChangeRequiredMiddleware
from apps.core.models import Role, User
from apps.test_utils import TenantTestCase

# ─── Unit tests via RequestFactory (no DB, fast) ─────────────────────────────


def _make_middleware(status_code=200):
    """Return PasswordChangeRequiredMiddleware with a trivial pass-through."""
    from django.http import HttpResponse

    def get_response(request):
        return HttpResponse("ok", status=status_code)

    return PasswordChangeRequiredMiddleware(get_response)


def _anon_user():
    mock = MagicMock()
    mock.is_authenticated = False
    return mock


def _authed_user(must_change_password=False):
    mock = MagicMock()
    mock.is_authenticated = True
    mock.must_change_password = must_change_password
    return mock


class PasswordChangeRequiredMiddlewareUnitTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = _make_middleware()

    # ── anonymous ──────────────────────────────────────────────────────────────

    def test_unauthenticated_request_passes_through(self):
        """Anonymous user must never trigger the 403 guard."""
        request = self.factory.get("/api/v1/encounters/")
        request.user = _anon_user()
        response = self.middleware(request)
        self.assertNotEqual(response.status_code, 403)

    # ── flag False ────────────────────────────────────────────────────────────

    def test_user_without_flag_passes_through(self):
        """Authenticated user with must_change_password=False is not blocked."""
        request = self.factory.get("/api/v1/encounters/")
        request.user = _authed_user(must_change_password=False)
        response = self.middleware(request)
        self.assertNotEqual(response.status_code, 403)

    # ── flag True, non-allowlisted ─────────────────────────────────────────────

    def test_user_with_flag_blocked_on_protected_path(self):
        """Flag-True user hitting a non-allowlisted path receives 403."""
        request = self.factory.get("/api/v1/encounters/")
        request.user = _authed_user(must_change_password=True)
        response = self.middleware(request)
        self.assertEqual(response.status_code, 403)
        import json

        body = json.loads(response.content)
        self.assertEqual(body["error"]["code"], "PASSWORD_CHANGE_REQUIRED")
        self.assertEqual(body["error"]["redirect"], "/auth/change-password")

    # ── allowlist paths ────────────────────────────────────────────────────────

    def test_user_with_flag_can_hit_password_endpoint(self):
        """Flag-True user must not be blocked on /api/v1/auth/password."""
        request = self.factory.post("/api/v1/auth/password")
        request.user = _authed_user(must_change_password=True)
        response = self.middleware(request)
        self.assertNotEqual(response.status_code, 403)

    def test_user_with_flag_can_hit_logout_endpoint(self):
        """Flag-True user must not be blocked on /api/v1/auth/logout."""
        request = self.factory.post("/api/v1/auth/logout")
        request.user = _authed_user(must_change_password=True)
        response = self.middleware(request)
        self.assertNotEqual(response.status_code, 403)

    def test_user_with_flag_can_hit_me_endpoint(self):
        """Flag-True user must not be blocked on /api/v1/me."""
        request = self.factory.get("/api/v1/me")
        request.user = _authed_user(must_change_password=True)
        response = self.middleware(request)
        self.assertNotEqual(response.status_code, 403)

    # ── no user attribute on request ──────────────────────────────────────────

    def test_request_without_user_attribute_passes_through(self):
        """Middleware must not crash when request has no user attribute at all."""
        request = self.factory.get("/api/v1/encounters/")
        # deliberately do not set request.user
        if hasattr(request, "user"):
            del request.user
        response = self.middleware(request)
        self.assertNotEqual(response.status_code, 403)


# ─── Integration tests via TenantTestCase + APIClient (real JWT) ─────────────


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class PasswordChangeRequiredMiddlewareIntegrationTests(TenantTestCase):
    """
    Full HTTP round-trip tests against the live Django URL conf.
    Uses real JWT login so the middleware sees request.user correctly.
    (force_authenticate sets the DRF-layer user AFTER middleware runs;
    real JWT tokens go through TenantJWTAuthentication which populates
    request.user before the view — but still AFTER middleware. We therefore
    rely on the actual login flow to get a token and send it as a Bearer header.)
    """

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain

        role = Role.objects.create(name="clinician-pcr", permissions=["patients.read"])

        self.user_normal = User.objects.create_user(
            email="normal@test.com",
            password="Test123!",
            full_name="Normal User",
            role=role,
            must_change_password=False,
        )
        self.user_temp = User.objects.create_user(
            email="temp@test.com",
            password="Test123!",
            full_name="Temp User",
            role=role,
            must_change_password=True,
        )

    def _login(self, email, password):
        """Return the access token from a successful login."""
        resp = self.client.post(
            "/api/v1/auth/login",
            {"email": email, "password": password},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, msg=f"Login failed: {resp.json()}")
        return resp.json()["access"]

    # ── /api/v1/me (allowlist) ────────────────────────────────────────────────

    def test_user_with_flag_can_hit_me_endpoint_integration(self):
        """Flag-True user can GET /api/v1/me — middleware does not block it."""
        token = self._login("temp@test.com", "Test123!")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        response = self.client.get("/api/v1/me")
        # Middleware does NOT block; actual view returns 200
        self.assertNotEqual(response.status_code, 403)

    # ── blocked path ──────────────────────────────────────────────────────────

    def test_user_with_flag_blocked_integration(self):
        """Flag-True user hitting /api/v1/users/ receives 403 with payload."""
        token = self._login("temp@test.com", "Test123!")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        response = self.client.get("/api/v1/users/")
        self.assertEqual(response.status_code, 403)
        body = response.json()
        self.assertEqual(body["error"]["code"], "PASSWORD_CHANGE_REQUIRED")
        self.assertEqual(body["error"]["redirect"], "/auth/change-password")

    # ── change password clears flag ───────────────────────────────────────────

    def test_change_password_clears_flag(self):
        """
        PUT /api/v1/auth/password with valid credentials clears the flag.
        After clearing, subsequent requests to protected paths succeed.
        """
        token = self._login("temp@test.com", "Test123!")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        # First, assert the user is blocked on a protected path
        blocked = self.client.get("/api/v1/users/")
        self.assertEqual(blocked.status_code, 403)

        # Change the password (ChangePasswordView accepts PUT)
        response = self.client.put(
            "/api/v1/auth/password",
            {
                "current_password": "Test123!",
                "new_password": "NewSecure456!",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, msg=response.json())

        # Verify flag is cleared in the DB
        self.user_temp.refresh_from_db()
        self.assertFalse(self.user_temp.must_change_password)

        # Login again with new password to get a fresh token
        new_token = self._login("temp@test.com", "NewSecure456!")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {new_token}")
        unblocked = self.client.get("/api/v1/users/")
        # Should NOT be 403 from the middleware (may be 200 or other non-middleware code)
        self.assertNotEqual(unblocked.status_code, 403)
