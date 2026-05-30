"""
Security hardening tests — settings & middleware.

Covers:
  - FIELD_ENCRYPTION_KEY: assert_field_encryption_key() raises on the all-zero
    placeholder or an empty string, passes on a real key.
  - XForwardedHostValidationMiddleware: rejects/logs X-Forwarded-Host values
    that are not in ALLOWED_HOSTS; passes valid hosts and skips the check when
    ALLOWED_HOSTS='*' (development/test mode).
  - MFA_GRACE_PERIOD_DAYS: the default grace period before MFA enrolment is
    enforced is the hardened value (7 days, down from 30).
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings

from apps.core.middleware import XForwardedHostValidationMiddleware
from vitali.settings._security_checks import (
    _DEV_SECRET_KEY,
    _FERNET_ZERO_KEY,
    assert_field_encryption_key,
    assert_postgres_password,
    assert_redis_password,
    assert_secret_key,
    assert_whatsapp_evolution_api_key,
)

_REAL_KEY = "dGVzdGtleXRlc3RrZXl0ZXN0a2V5dGVzdGtleXRlc3Q="  # 32-byte base64, not the zero key
_STRONG_PASSWORD = "xK9#mP2$vL7@qN4&rT6"
_STRONG_SECRET_KEY = "real-secret-key-that-is-not-a-placeholder-and-is-long-enough-for-production"


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


# ─────────────────────────────────────────────────────────────────────────────
# MFA grace period default
# ─────────────────────────────────────────────────────────────────────────────


class MFAGracePeriodDefaultTests(TestCase):
    def test_default_grace_period_is_seven_days(self):
        """The hardened default MFA grace period is 7 days (reduced from 30)."""
        self.assertEqual(settings.MFA_GRACE_PERIOD_DAYS, 7)

    def test_grace_period_does_not_exceed_legacy_default(self):
        """Guard against regressing back to the looser 30-day window."""
        self.assertLessEqual(settings.MFA_GRACE_PERIOD_DAYS, 7)


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


# ─────────────────────────────────────────────────────────────────────────────
# SECRET_KEY startup guard
# ─────────────────────────────────────────────────────────────────────────────


class SecretKeyCheckTests(TestCase):
    def test_raises_on_empty_string(self):
        with self.assertRaises(ImproperlyConfigured):
            assert_secret_key("")

    def test_raises_on_dev_default(self):
        """The committed dev default must be rejected at production startup."""
        with self.assertRaises(ImproperlyConfigured):
            assert_secret_key(_DEV_SECRET_KEY)

    def test_raises_on_change_me_placeholder(self):
        with self.assertRaises(ImproperlyConfigured):
            assert_secret_key("change-me")

    def test_raises_on_vitali_placeholder(self):
        with self.assertRaises(ImproperlyConfigured):
            assert_secret_key("vitali")

    def test_raises_on_django_insecure_prefix(self):
        """Keys generated by Django's startproject use 'django-insecure-' — must be rejected."""
        with self.assertRaises(ImproperlyConfigured):
            assert_secret_key("django-insecure-abc123xyz-should-not-reach-production")

    def test_raises_on_build_time_placeholder(self):
        """The Dockerfile build placeholder must never reach a running container."""
        with self.assertRaises(ImproperlyConfigured):
            assert_secret_key("build-time-placeholder-not-used-in-production")

    def test_passes_on_strong_key(self):
        assert_secret_key(_STRONG_SECRET_KEY)  # must not raise

    def test_error_message_mentions_generation_command(self):
        with self.assertRaises(ImproperlyConfigured) as ctx:
            assert_secret_key(_DEV_SECRET_KEY)
        self.assertIn("get_random_secret_key", str(ctx.exception))


# ─────────────────────────────────────────────────────────────────────────────
# POSTGRES_PASSWORD startup guard
# ─────────────────────────────────────────────────────────────────────────────


class PostgresPasswordCheckTests(TestCase):
    def test_raises_on_empty_string(self):
        with self.assertRaises(ImproperlyConfigured):
            assert_postgres_password("")

    def test_raises_on_vitali_placeholder(self):
        """'vitali' is the dev docker-compose.yml POSTGRES_PASSWORD — must be rejected."""
        with self.assertRaises(ImproperlyConfigured):
            assert_postgres_password("vitali")

    def test_raises_on_change_me_placeholder(self):
        with self.assertRaises(ImproperlyConfigured):
            assert_postgres_password("change-me")

    def test_raises_on_password_placeholder(self):
        with self.assertRaises(ImproperlyConfigured):
            assert_postgres_password("password")

    def test_passes_on_strong_password(self):
        assert_postgres_password(_STRONG_PASSWORD)  # must not raise

    def test_error_message_mentions_secret_manager(self):
        with self.assertRaises(ImproperlyConfigured) as ctx:
            assert_postgres_password("vitali")
        self.assertIn("secret manager", str(ctx.exception))


# ─────────────────────────────────────────────────────────────────────────────
# REDIS_PASSWORD startup guard
# ─────────────────────────────────────────────────────────────────────────────


class RedisPasswordCheckTests(TestCase):
    def test_raises_on_empty_string(self):
        with self.assertRaises(ImproperlyConfigured):
            assert_redis_password("")

    def test_raises_on_vitali_placeholder(self):
        with self.assertRaises(ImproperlyConfigured):
            assert_redis_password("vitali")

    def test_raises_on_change_me_placeholder(self):
        with self.assertRaises(ImproperlyConfigured):
            assert_redis_password("change-me")

    def test_raises_on_redis_placeholder(self):
        with self.assertRaises(ImproperlyConfigured):
            assert_redis_password("redis")

    def test_passes_on_strong_password(self):
        assert_redis_password(_STRONG_PASSWORD)  # must not raise

    def test_error_message_mentions_secret_manager(self):
        with self.assertRaises(ImproperlyConfigured) as ctx:
            assert_redis_password("change-me")
        self.assertIn("secret manager", str(ctx.exception))


# ─────────────────────────────────────────────────────────────────────────────
# WHATSAPP_EVOLUTION_API_KEY startup guard
# ─────────────────────────────────────────────────────────────────────────────


class WhatsappEvolutionKeyCheckTests(TestCase):
    def test_raises_on_empty_string(self):
        with self.assertRaises(ImproperlyConfigured):
            assert_whatsapp_evolution_api_key("")

    def test_raises_on_change_me_placeholder(self):
        """'change-me' is the docker-compose.yml default — must be rejected."""
        with self.assertRaises(ImproperlyConfigured):
            assert_whatsapp_evolution_api_key("change-me")

    def test_passes_on_real_key(self):
        assert_whatsapp_evolution_api_key("evo_live_8f3c2a1b9d7e6f5a4c3b2a1d")  # must not raise
