"""
Core utility functions — shared across middleware, permissions, and views.
Canonical home for tenant_has_feature to avoid circular imports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.core.models import Tenant


def tenant_has_feature(tenant: Tenant, module_key: str) -> bool:
    """
    Check if a tenant has a specific feature/module enabled.

    Usage in views/serializers/permissions:
        from apps.core.utils import tenant_has_feature
        if tenant_has_feature(request.tenant, 'billing'):
            ...
    """
    from apps.core.models import FeatureFlag

    return FeatureFlag.objects.filter(
        tenant=tenant, module_key=module_key, is_enabled=True
    ).exists()
