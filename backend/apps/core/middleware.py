"""
HealthOS Core Middleware
========================
Feature flag utilities, tenant-aware helpers, and thread-local current user.
"""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.core.models import Tenant

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


class FeatureFlagMiddleware:
    """
    Attaches a helper method to the request for convenient feature flag checks.

    Usage: request.has_feature('module_emr')
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if hasattr(request, "tenant"):
            request.has_feature = lambda key: tenant_has_feature(request.tenant, key)
        response = self.get_response(request)
        return response


# ─── Utility ──────────────────────────────────────────────────────────────────

def tenant_has_feature(tenant: "Tenant", module_key: str) -> bool:
    """
    Check if a tenant has a specific feature/module enabled.

    Usage in views/serializers:
        if tenant_has_feature(request.tenant, 'module_pharmacy'):
            ...
    """
    from apps.core.models import FeatureFlag

    return FeatureFlag.objects.filter(
        tenant=tenant, module_key=module_key, is_enabled=True
    ).exists()
