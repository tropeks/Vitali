"""
Security hardening tests — settings & middleware.

Covers:
  - FIELD_ENCRYPTION_KEY: assert_field_encryption_key() raises on the all-zero
    placeholder or an empty string, passes on a real key.
  - XForwardedHostValidationMiddleware: rejects/logs X-Forwarded-Host values
    that are not in ALLOWED_HOSTS; passes valid hosts and skips the check when
    ALLOWED_HOSTS='*' (development/test mode).
"""

from __future__ import annotations

import logging

from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings

from apps.core.middleware import XForwardedHostValidationMiddleware
from vitali.settings._security_checks import _FERNET_ZERO_KEY, assert_field_encryption_key

_REAL_KEY = "dGVzdGtleXRlc3RrZXl0ZXN0a2V5dGVzdGtleXRlc3Q="  # 32-byte base64, not the zero key


# ─────────────────────────────────────────────────────────────────────────────
# FIELD_ENCRYPTION_KEY startup guard
# ─────────────────────────────────────────────────────────────────────────────


class FieldEncryptionKeyCheckTests(TestCase):
    def test_raises_on_zero_placeholder(self):
        """All-zero Fernet placeholder must be rejected at startup."""
        with self.assertRaises(ImproperlyConfigured):
            assert_field_encryption_key(_FERNET_ZERO_KEY)

    def test_raises_on_empty_string(self):
        """Missing key (empty string) must be rejected at startup."""
        with self.assertRaises(ImproperlyConfigured):
            assert_field_encryption_key("")

    def test_passes_on_real_key(self):
        """A non-placeholder, non-empty key must not raise."""
        assert_field_encryption_key(_REAL_KEY)  # must not raise

    def test_error_message_mentions_fernet(self):
        """Error message must guide the operator to generate a proper Fernet key."""
        with self.assertRaises(ImproperlyConfigured) as ctx:
            assert_field_encryption_key(_FERNET_ZERO_KEY)
        self.assertIn("Fernet", str(ctx.exception))


# ─────────────────────────────────────────────────────────────────────────────
# XForwardedHostValidationMiddleware
# ─────────────────────────────────────────────────────────────────────────────


def _make_middleware():
    """Return a XForwardedHostValidationMiddleware wrapping a trivial view."""

    def get_response(request):
        return HttpResponse("ok")

    return XForwardedHostValidationMiddleware(get_response)


@override_settings(
    USE_X_FORWARDED_HOST=True,
    ALLOWED_HOSTS=["clinic.vitali.com.br", ".vitali.com.br"],
    DEBUG=False,
)
class XForwardedHostValidationMiddlewareTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = _make_middleware()

    def test_valid_host_passes(self):
        """A host matching ALLOWED_HOSTS must be allowed through."""
        request = self.factory.get(
            "/api/v1/health/",
            HTTP_HOST="clinic.vitali.com.br",
            HTTP_X_FORWARDED_HOST="clinic.vitali.com.br",
        )
        response = self.middleware(request)
        self.assertEqual(response.status_code, 200)

    def test_wildcard_subdomain_passes(self):
        """A host matching a .prefix entry in ALLOWED_HOSTS must pass."""
        request = self.factory.get(
            "/api/v1/health/",
            HTTP_HOST="other.vitali.com.br",
            HTTP_X_FORWARDED_HOST="other.vitali.com.br",
        )
        response = self.middleware(request)
        self.assertEqual(response.status_code, 200)

    def test_invalid_host_returns_400(self):
        """An X-Forwarded-Host not in ALLOWED_HOSTS must return 400."""
        request = self.factory.get(
            "/api/v1/health/",
            HTTP_HOST="evil.example.com",
            HTTP_X_FORWARDED_HOST="evil.example.com",
        )
        response = self.middleware(request)
        self.assertEqual(response.status_code, 400)

    def test_invalid_host_logs_warning(self):
        """A forged host must emit a security warning log entry."""
        request = self.factory.get(
            "/api/v1/health/",
            HTTP_HOST="evil.example.com",
            HTTP_X_FORWARDED_HOST="evil.example.com",
        )
        with self.assertLogs("apps.core.middleware", level=logging.WARNING) as cm:
            self.middleware(request)
        self.assertTrue(
            any("S-HOST" in line for line in cm.output),
            msg="Expected a S-HOST warning log entry",
        )

    def test_no_forwarded_host_header_passes(self):
        """Requests without X-Forwarded-Host must not be blocked."""
        request = self.factory.get(
            "/api/v1/health/",
            HTTP_HOST="clinic.vitali.com.br",
        )
        response = self.middleware(request)
        self.assertEqual(response.status_code, 200)

    @override_settings(ALLOWED_HOSTS=["*"])
    def test_wildcard_allowed_hosts_skips_check(self):
        """When ALLOWED_HOSTS='*' (dev/test), the check must be skipped entirely."""
        request = self.factory.get(
            "/api/v1/health/",
            HTTP_HOST="anything.goes.com",
            HTTP_X_FORWARDED_HOST="anything.goes.com",
        )
        response = self.middleware(request)
        self.assertEqual(response.status_code, 200)

    @override_settings(USE_X_FORWARDED_HOST=False)
    def test_disabled_use_x_forwarded_host_skips_check(self):
        """When USE_X_FORWARDED_HOST=False the middleware must be a no-op."""
        request = self.factory.get(
            "/api/v1/health/",
            HTTP_HOST="evil.example.com",
            HTTP_X_FORWARDED_HOST="evil.example.com",
        )
        response = self.middleware(request)
        self.assertEqual(response.status_code, 200)
