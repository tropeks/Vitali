"""
HealthOS Core Middleware
========================
Feature flag utilities and tenant-aware helpers.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.core.models import Tenant


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
