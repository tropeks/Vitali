"""
HealthOS Core Middleware
========================
Feature flag utilities, tenant-aware helpers, and thread-local current user.
"""
from __future__ import annotations

import logging
import threading

from django.conf import settings
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


