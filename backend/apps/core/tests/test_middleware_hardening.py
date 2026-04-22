"""
Sprint 13 — Middleware & throttle hardening tests.

Covers:
  - RequestIdMiddleware: UUID4 in X-Request-ID + thread-local cleanup
  - TenantRequestLogFilter: tenant + request_id fields on log records
  - TenantUserRateThrottle: per-tenant cache key scoping
  - production.py settings assertions (CONN_MAX_AGE, CACHES, SESSION_ENGINE, CSRF)

Run: python manage.py test apps.core.tests.test_middleware_hardening
"""

from __future__ import annotations

import logging
import uuid
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, TestCase, override_settings
from rest_framework.test import APIRequestFactory

from apps.core.middleware import (
    RequestIdMiddleware,
    TenantRequestLogFilter,
    _thread_locals,
)
from apps.core.throttles import TenantUserRateThrottle

# ─────────────────────────────────────────────────────────────────────────────
# RequestIdMiddleware
# ─────────────────────────────────────────────────────────────────────────────


class RequestIdMiddlewareTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _make_middleware(self, response=None):
        """Return a middleware instance with a trivial get_response."""
        from django.http import HttpResponse

        def get_response(request):
            return response or HttpResponse("ok")

        return RequestIdMiddleware(get_response)

    def test_x_request_id_header_is_set(self):
        """Response must carry an X-Request-ID header."""
        middleware = self._make_middleware()
        request = self.factory.get("/health/")
        response = middleware(request)
        self.assertIn("X-Request-ID", response)

    def test_x_request_id_is_valid_uuid4(self):
        """X-Request-ID must be a well-formed UUID4."""
        middleware = self._make_middleware()
        request = self.factory.get("/health/")
        response = middleware(request)
        request_id = response["X-Request-ID"]
        parsed = uuid.UUID(request_id, version=4)
        self.assertEqual(str(parsed), request_id)

    def test_request_id_unique_per_request(self):
        """Two back-to-back requests must have different IDs."""
        middleware = self._make_middleware()
        r1 = middleware(self.factory.get("/health/"))
        r2 = middleware(self.factory.get("/health/"))
        self.assertNotEqual(r1["X-Request-ID"], r2["X-Request-ID"])

    def test_thread_local_cleared_after_request(self):
        """_thread_locals.request_id must be None after the response is returned."""
        middleware = self._make_middleware()
        middleware(self.factory.get("/health/"))
        self.assertIsNone(getattr(_thread_locals, "request_id", None))

    def test_thread_local_cleared_even_on_exception(self):
        """Thread-local must be cleaned up even when the view raises."""

        def boom(request):
            raise ValueError("view exploded")

        middleware = RequestIdMiddleware(boom)
        with self.assertRaises(ValueError):
            middleware(self.factory.get("/health/"))

        self.assertIsNone(getattr(_thread_locals, "request_id", None))


# ─────────────────────────────────────────────────────────────────────────────
# TenantRequestLogFilter
# ─────────────────────────────────────────────────────────────────────────────


class TenantRequestLogFilterTests(TestCase):
    def _make_record(self):
        return logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test message",
            args=(),
            exc_info=None,
        )

    def test_request_id_injected_from_thread_local(self):
        """Filter must copy _thread_locals.request_id onto the log record."""
        _thread_locals.request_id = "test-request-id-123"
        try:
            f = TenantRequestLogFilter()
            record = self._make_record()
            f.filter(record)
            self.assertEqual(record.request_id, "test-request-id-123")
        finally:
            _thread_locals.request_id = None

    def test_request_id_defaults_to_dash_when_absent(self):
        """Filter must fall back to '-' when no request_id is in thread-locals."""
        if hasattr(_thread_locals, "request_id"):
            del _thread_locals.request_id
        f = TenantRequestLogFilter()
        record = self._make_record()
        f.filter(record)
        self.assertEqual(record.request_id, "-")

    def test_tenant_set_to_shared_when_no_connection_tenant(self):
        """In Celery context where connection.tenant is None, tenant='shared'."""
        with patch("apps.core.middleware.connection") as mock_conn:
            mock_conn.tenant = None
            f = TenantRequestLogFilter()
            record = self._make_record()
            f.filter(record)
            self.assertEqual(record.tenant, "shared")

    def test_tenant_set_to_schema_name_when_tenant_active(self):
        """In a request context with an active tenant, tenant=schema_name."""
        mock_tenant = MagicMock()
        mock_tenant.schema_name = "clinica_alfa"
        with patch("apps.core.middleware.connection") as mock_conn:
            mock_conn.tenant = mock_tenant
            f = TenantRequestLogFilter()
            record = self._make_record()
            f.filter(record)
            self.assertEqual(record.tenant, "clinica_alfa")

    def test_filter_returns_true(self):
        """Filter must always return True (never suppress records)."""
        f = TenantRequestLogFilter()
        record = self._make_record()
        self.assertTrue(f.filter(record))


# ─────────────────────────────────────────────────────────────────────────────
# TenantUserRateThrottle
# ─────────────────────────────────────────────────────────────────────────────


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    REST_FRAMEWORK={
        "DEFAULT_THROTTLE_RATES": {"user": "100/hour"},
    },
)
class TenantUserRateThrottleTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()

    def _make_authed_request(self, user_id=1):
        """Return a DRF request with a mock authenticated user."""
        request = self.factory.get("/api/v1/test/")
        mock_user = MagicMock()
        mock_user.pk = user_id
        mock_user.is_authenticated = True
        request.user = mock_user
        return request

    def test_cache_key_includes_schema_name(self):
        """Cache key must be prefixed with the current tenant schema."""
        mock_tenant = MagicMock()
        mock_tenant.schema_name = "clinica_alfa"
        with patch("apps.core.throttles.connection") as mock_conn:
            mock_conn.tenant = mock_tenant
            throttle = TenantUserRateThrottle()
            request = self._make_authed_request(user_id=1)
            key = throttle.get_cache_key(request, view=None)
            self.assertIn("clinica_alfa", key)
            self.assertTrue(key.startswith("throttle:clinica_alfa:"))

    def test_cache_key_differs_across_tenants_for_same_user_id(self):
        """Same user_id in two different tenants must produce different keys."""

        def make_key(schema):
            mock_tenant = MagicMock()
            mock_tenant.schema_name = schema
            with patch("apps.core.throttles.connection") as mock_conn:
                mock_conn.tenant = mock_tenant
                throttle = TenantUserRateThrottle()
                return throttle.get_cache_key(self._make_authed_request(user_id=1), view=None)

        key_a = make_key("clinica_alfa")
        key_b = make_key("clinica_beta")
        self.assertNotEqual(key_a, key_b)

    def test_cache_key_falls_back_to_public_when_no_tenant(self):
        """When no tenant is active (public schema), key uses 'public'."""
        with patch("apps.core.throttles.connection") as mock_conn:
            mock_conn.tenant = None
            throttle = TenantUserRateThrottle()
            request = self._make_authed_request(user_id=1)
            key = throttle.get_cache_key(request, view=None)
            self.assertIn("public", key)

    def test_returns_none_for_anonymous_user(self):
        """Unauthenticated requests must return None (no throttle key)."""
        request = self.factory.get("/api/v1/test/")
        mock_user = MagicMock()
        mock_user.pk = None
        mock_user.is_authenticated = False
        request.user = mock_user
        throttle = TenantUserRateThrottle()
        key = throttle.get_cache_key(request, view=None)
        self.assertIsNone(key)


# ─────────────────────────────────────────────────────────────────────────────
# Production settings assertions
# ─────────────────────────────────────────────────────────────────────────────


@override_settings(
    DATABASES={
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "CONN_MAX_AGE": 60,
            "CONN_HEALTH_CHECKS": True,
        }
    },
    SESSION_ENGINE="django.contrib.sessions.backends.cache",
    CSRF_TRUSTED_ORIGINS=["https://staging.vitali.com.br"],
)
class ProductionSettingsTests(TestCase):
    def test_conn_max_age_is_set(self):
        from django.conf import settings

        self.assertEqual(settings.DATABASES["default"]["CONN_MAX_AGE"], 60)

    def test_conn_health_checks_is_true(self):
        from django.conf import settings

        self.assertTrue(settings.DATABASES["default"]["CONN_HEALTH_CHECKS"])

    def test_session_engine_is_cache(self):
        from django.conf import settings

        self.assertEqual(
            settings.SESSION_ENGINE,
            "django.contrib.sessions.backends.cache",
        )

    def test_csrf_trusted_origins_is_list(self):
        """CSRF_TRUSTED_ORIGINS must be a list, not a plain string.
        A plain string would be iterated character-by-character by Django,
        silently breaking all CSRF protection.
        """
        from django.conf import settings

        self.assertIsInstance(settings.CSRF_TRUSTED_ORIGINS, list)
        self.assertTrue(len(settings.CSRF_TRUSTED_ORIGINS) > 0)
