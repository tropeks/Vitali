"""
Vitali — DRF Throttle Classes
==============================
Extends DRF's built-in throttling with tenant-scoped cache keys.

Problem: DRF's default UserRateThrottle cache key is `throttle_user_{user_id}`.
In a multi-tenant system, user IDs are per-schema but Redis is shared — user #1
in tenant_a and user #1 in tenant_b would share the same bucket. One tenant's
burst could exhaust the quota for an unrelated user on another tenant.

Fix: prefix the key with the current tenant's schema name.
"""

from django.db import connection
from rest_framework.throttling import UserRateThrottle


class TenantUserRateThrottle(UserRateThrottle):
    """
    Rate throttle keyed by `{schema}:user:{user_id}` to prevent cross-tenant
    cache collisions. Falls back to plain `user:{user_id}` when no tenant is
    active (e.g. public-schema admin requests).
    """

    def get_cache_key(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return None
        base_key = super().get_cache_key(request, view)
        if base_key is None:
            return None

        try:
            tenant = getattr(connection, "tenant", None)
            schema = tenant.schema_name if tenant else "public"
        except Exception:
            schema = "public"

        return f"throttle:{schema}:{base_key}"
