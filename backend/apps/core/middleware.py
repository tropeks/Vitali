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
from django.core.exceptions import DisallowedHost
from django.db import connection
from django.http import HttpResponseBadRequest, JsonResponse

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
        "/api/v1/auth/",  # JWT login/refresh/logout — must work in demo
        "/api/v1/platform/plans/",  # Platform admin can adjust plans during demo
        "/api/v1/platform/subscriptions/",  # Platform admin can adjust subscriptions during demo
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if getattr(settings, "DEMO_MODE", False) and request.method in (
            "POST",
            "PATCH",
            "PUT",
            "DELETE",
        ):
            if not any(request.path.startswith(prefix) for prefix in self.WHITELIST):
                logger.warning(
                    "[DEMO_MODE] blocked %s %s for user=%s",
                    request.method,
                    request.path,
                    getattr(request.user, "id", "anon") if hasattr(request, "user") else "anon",
                )
                return JsonResponse(
                    {
                        "detail": "[DEMO] This is a demo environment — write operations are disabled."
                    },
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
    "/auth/mfa/status/",
    "/auth/mfa/login/",
    "/auth/mfa/setup/",
    "/auth/mfa/verify/",
}


class MFARequiredMiddleware:
    """
    Enforces MFA for elevated/sensitive accounts (S-062 + S28-04).

    MFA is mandatory for is_staff/is_superuser AND for users whose role is in
    settings.MFA_REQUIRED_ROLES (admin / medico / dentista by default) — see
    ``apps.core.mfa.mfa_required_for``. Regular users are never blocked.

    For a covered user that has not passed MFA this session:
      * Device enrolled, no ``mfa_verified`` claim → 403 ``mfa_required`` (verify).
      * No device enrolled:
          - within the enrollment grace window → allowed (new staff can work while
            they set MFA up);
          - past the grace window (settings.MFA_ENROLLMENT_GRACE_DAYS from account
            creation) → 403 ``mfa_enrollment_required`` (must enrol now).

    Exempt paths: login, token refresh, and all /auth/mfa/* endpoints so users can
    complete setup/verification without an active MFA session.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user and user.is_authenticated:
            from apps.core.mfa import mfa_enrollment_grace_expired, mfa_required_for

            if mfa_required_for(user):
                path = request.path_info
                if not any(path.endswith(p) or path == p for p in _MFA_EXEMPT_PATHS):
                    token_payload = getattr(request, "auth", None)
                    mfa_verified = False
                    if token_payload and hasattr(token_payload, "get"):
                        mfa_verified = bool(token_payload.get("mfa_verified"))
                    elif isinstance(token_payload, dict):
                        mfa_verified = bool(token_payload.get("mfa_verified"))
                    if not mfa_verified:
                        from apps.core.models import TOTPDevice

                        has_device = TOTPDevice.objects.filter(user=user, is_active=True).exists()
                        if has_device:
                            return JsonResponse(
                                {"detail": "MFA verification required.", "code": "mfa_required"},
                                status=403,
                            )
                        # No device — block only once the enrollment grace expired.
                        if mfa_enrollment_grace_expired(user):
                            return JsonResponse(
                                {
                                    "detail": "MFA enrollment required.",
                                    "code": "mfa_enrollment_required",
                                    "redirect": "/auth/mfa/setup",
                                },
                                status=403,
                            )
        return self.get_response(request)


# ─── S-076-NEW: Password Change Required Middleware ───────────────────────────


class PasswordChangeRequiredMiddleware:
    """
    S-076-NEW: gates all authenticated requests behind password change for
    users with must_change_password=True. Mirrors MFARequiredMiddleware.

    Allowlist: change-password, logout, identity. Everything else → 403 with
    a structured redirect payload the frontend interceptor (T12) follows.
    """

    ALLOWLIST = frozenset(
        {
            "/api/v1/auth/password",
            "/api/v1/auth/logout",
            "/api/v1/me",
        }
    )
    # Prefix-matched paths (startswith) that are always open — no auth required.
    ALLOWLIST_PREFIXES = ("/api/v1/auth/set-password/",)

    def __init__(self, get_response):
        self.get_response = get_response

    def _resolve_user(self, request):
        """
        Return the authenticated user, attempting JWT resolution when the
        session user is anonymous. This is necessary because DRF authentication
        is lazy and only fires inside the view layer — middleware runs first.
        """
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            return user
        # Attempt JWT authentication so Bearer tokens are honoured in middleware.
        try:
            from apps.core.authentication import TenantJWTAuthentication

            result = TenantJWTAuthentication().authenticate(request)
            if result is not None:
                return result[0]
        except Exception:
            pass
        return None

    def __call__(self, request):
        if request.path in self.ALLOWLIST:
            return self.get_response(request)
        if any(request.path.startswith(prefix) for prefix in self.ALLOWLIST_PREFIXES):
            return self.get_response(request)
        user = self._resolve_user(request)
        if (
            user is not None
            and user.is_authenticated
            and getattr(user, "must_change_password", False)
        ):
            return JsonResponse(
                {
                    "error": {
                        "code": "PASSWORD_CHANGE_REQUIRED",
                        "message": "Senha temporária deve ser alterada antes de continuar.",
                        "redirect": "/auth/change-password",
                    }
                },
                status=403,
            )
        return self.get_response(request)


# ─── Phase 3 i18n: per-user preferred language ────────────────────────────────


class PreferredLanguageMiddleware:
    """
    Activate the authenticated user's `preferred_language` for the request,
    overriding any earlier `LocaleMiddleware` choice.

    Order matters: this MUST sit AFTER `django.middleware.locale.LocaleMiddleware`
    (so that middleware's initial activation runs first) and AFTER
    `AuthenticationMiddleware` (so `request.user` is populated). Both are
    enforced by the MIDDLEWARE ordering in `vitali/settings/base.py`.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.utils import translation

        user = getattr(request, "user", None)
        pref = ""
        if user is not None and getattr(user, "is_authenticated", False):
            pref = (getattr(user, "preferred_language", "") or "").strip()
        if pref:
            translation.activate(pref)
            request.LANGUAGE_CODE = pref
        try:
            return self.get_response(request)
        finally:
            if pref:
                translation.deactivate()


# ─── S-HOST: X-Forwarded-Host validation ────────────────────────────────────


class XForwardedHostValidationMiddleware:
    """
    Rejects requests whose X-Forwarded-Host does not appear in ALLOWED_HOSTS,
    logging a security warning before TenantMainMiddleware can use the header
    for schema routing.

    TRUSTED PROXY REQUIREMENT: the reverse proxy (nginx/Caddy/Traefik) MUST
    strip any client-supplied X-Forwarded-Host header and set it only from the
    original browser Host. Without proxy-level stripping a malicious client can
    forge this header to attempt tenant enumeration or cross-tenant routing.

    Implementation reuses Django's own get_host() validation (which reads
    USE_X_FORWARDED_HOST and validates against ALLOWED_HOSTS) so host-matching
    semantics stay in sync with the rest of the framework. When validation fails
    this middleware logs the attempt explicitly — Django's own DisallowedHost
    path returns 400 silently — before returning 400 itself.

    The check is skipped when ALLOWED_HOSTS contains '*' (dev/test environments
    where strict host validation is intentionally relaxed).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if getattr(settings, "USE_X_FORWARDED_HOST", False) and request.META.get(
            "HTTP_X_FORWARDED_HOST"
        ):
            allowed = getattr(settings, "ALLOWED_HOSTS", [])
            if "*" not in allowed:
                try:
                    request.get_host()
                except DisallowedHost:
                    logger.warning(
                        "S-HOST: X-Forwarded-Host %r not in ALLOWED_HOSTS — "
                        "possible host-header injection; returning 400.",
                        request.META.get("HTTP_X_FORWARDED_HOST", ""),
                    )
                    return HttpResponseBadRequest()
        return self.get_response(request)
