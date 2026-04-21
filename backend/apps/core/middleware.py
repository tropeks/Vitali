"""
HealthOS Core Middleware
========================
Feature flag utilities, tenant-aware helpers, thread-local current user,
request ID injection, and tenant-scoped JSON log filter.
"""
from __future__ import annotations

import logging
import threading
import uuid

from django.conf import settings
from django.db import connection
from django.http import JsonResponse

logger = logging.getLogger(__name__)

# ─── Thread-local storage ─────────────────────────────────────────────────────

_thread_locals = threading.local()


def get_current_request():
    """Return the current HTTP request stored in thread-local storage."""
    return getattr(_thread_locals, "request", None)


def get_current_user():
    """Return the authenticated user from the current request, or None."""
    request = get_current_request()
    if request is None:
        return None
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        return user
    return None


# ─── Middleware classes ───────────────────────────────────────────────────────

class CurrentUserMiddleware:
    """
    Stores the current request in thread-local storage so that signals and
    model save() methods can access the authenticated user and IP address
    without needing to pass the request explicitly.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _thread_locals.request = request
        try:
            response = self.get_response(request)
        finally:
            # Always clean up to avoid leaking between requests
            _thread_locals.request = None
        return response


class DemoModeMiddleware:
    """
    S-043: Demo mode write protection.
    When DEMO_MODE=true in settings/env, all write operations (POST/PATCH/PUT/DELETE)
    return 403 with a [DEMO] prefixed message.

    Auth paths are whitelisted so JWT refresh still works — without this, the demo
    session expires after 15 minutes with a confusing "demo environment" error.

    Platform admin subscription/plan endpoints are whitelisted so Vitali operators
    can adjust the demo tenant's modules live. The tenant registration endpoint
    (/api/v1/platform/tenants) is intentionally NOT whitelisted — creating new
    schemas in a demo environment would permanently alter the demo database.
    """

    WHITELIST = (
        "/api/v1/auth/",                    # JWT login/refresh/logout — must work in demo
        "/api/v1/platform/plans/",          # Platform admin can adjust plans during demo
        "/api/v1/platform/subscriptions/",  # Platform admin can adjust subscriptions during demo
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if getattr(settings, "DEMO_MODE", False) and request.method in (
            "POST", "PATCH", "PUT", "DELETE"
        ):
            if not any(request.path.startswith(prefix) for prefix in self.WHITELIST):
                logger.warning(
                    "[DEMO_MODE] blocked %s %s for user=%s",
                    request.method,
                    request.path,
                    getattr(request.user, "id", "anon") if hasattr(request, "user") else "anon",
                )
                return JsonResponse(
                    {"detail": "[DEMO] This is a demo environment — write operations are disabled."},
                    status=403,
                )
        return self.get_response(request)


class RequestIdMiddleware:
    """
    Assigns a UUID4 request ID to every HTTP request.

    - Stored in thread-local (_thread_locals.request_id) so TenantRequestLogFilter
      can inject it into every log record for the duration of the request.
    - Echoed in the X-Request-ID response header for client-side correlation.
    - Cleared in a finally block to prevent leakage across requests on reused threads.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _thread_locals.request_id = str(uuid.uuid4())
        try:
            response = self.get_response(request)
            response["X-Request-ID"] = _thread_locals.request_id
        finally:
            _thread_locals.request_id = None
        return response


class TenantRequestLogFilter(logging.Filter):
    """
    Injects `tenant` and `request_id` into every log record so that structured
    JSON log lines are trivially grepable by clinic or request.

    Celery tasks do not go through the request cycle, so connection.tenant may
    be None — falls back to "shared" to avoid AttributeError.
    """

    def filter(self, record):
        try:
            tenant = getattr(connection, "tenant", None)
            record.tenant = tenant.schema_name if tenant else "shared"
        except Exception:
            record.tenant = "shared"

        record.request_id = getattr(_thread_locals, "request_id", None) or "-"
        return True


class FeatureFlagMiddleware:
    """
    Attaches a helper method to the request for convenient feature flag checks.

    Usage: request.has_feature('billing')
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if hasattr(request, "tenant"):
            from apps.core.utils import tenant_has_feature
            request.has_feature = lambda key: tenant_has_feature(request.tenant, key)
        response = self.get_response(request)
        return response


# ─── S-062: MFA Required Middleware ──────────────────────────────────────────

_MFA_EXEMPT_PATHS = {
    "/auth/login",
    "/auth/refresh",
    "/auth/mfa/login/",
    "/auth/mfa/setup/",
    "/auth/mfa/verify/",
}


class MFARequiredMiddleware:
    """
    Blocks staff/superuser requests that lack the mfa_verified JWT claim.

    Regular users are not blocked — MFA is only enforced for elevated accounts
    (is_staff or is_superuser). The JWT claim 'mfa_verified' is injected by
    MFALoginView after successful TOTP verification.

    Exempt paths: login, token refresh, and all /auth/mfa/* endpoints so users
    can complete the MFA flow without an active MFA session.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user and user.is_authenticated and (user.is_staff or user.is_superuser):
            path = request.path_info
            if not any(path.endswith(p) or path == p for p in _MFA_EXEMPT_PATHS):
                # Check JWT claim
                token_payload = getattr(request, "auth", None)
                mfa_verified = False
                if token_payload and hasattr(token_payload, "get"):
                    mfa_verified = bool(token_payload.get("mfa_verified"))
                elif isinstance(token_payload, dict):
                    mfa_verified = bool(token_payload.get("mfa_verified"))
                if not mfa_verified:
                    from apps.core.models import TOTPDevice
                    try:
                        device = TOTPDevice.objects.get(user=user, is_active=True)
                        _ = device  # MFA device exists — enforce the check
                        return JsonResponse(
                            {"detail": "MFA verification required.", "code": "mfa_required"},
                            status=403,
                        )
                    except TOTPDevice.DoesNotExist:
                        pass  # No device yet — don't block (grace period)
        return self.get_response(request)


