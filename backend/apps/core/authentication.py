"""
Custom JWT Authentication for Vitali.

Enforces two things on every authenticated request:
1. The user account is globally active (``User.is_active``).
2. The user is bound to the CURRENT tenant — ``User``/``Role`` live in the public
   schema (apps.core is SHARED_APPS) as a single global registry, so a valid token
   would otherwise authenticate against ANY tenant's domain. Tenant binding is via
   :class:`apps.core.models.UserTenantMembership`; see ``apps.core.tenant_auth``.
   Gated by ``settings.ENFORCE_TENANT_MEMBERSHIP`` (default False) for safe rollout.
"""

from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication

from .tenant_auth import enforce_request_membership


class TenantJWTAuthentication(JWTAuthentication):
    def get_user(self, validated_token):
        user = super().get_user(validated_token)

        if not user.is_active:
            raise AuthenticationFailed({"code": "USER_INACTIVE", "message": "Conta desativada."})

        enforce_request_membership(user, validated_token)
        return user
