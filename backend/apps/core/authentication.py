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

from .tenant_auth import (
    SMART_ALLOWED_PATH_PREFIX,
    SMART_TOKEN_USE,
    TOKEN_USE_CLAIM,
    enforce_request_membership,
)


class TenantJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        _user, validated_token = result
        # Audience restriction: tokens minted by the SMART-on-FHIR token endpoint
        # (token_use="smart") are scoped OAuth grants to third-party apps, not full
        # logins — they are only valid on the FHIR surface. Without this check a
        # SMART app granted `patient/*.read` would hold a token usable against the
        # entire Vitali API (including writes) as the authorizing user.
        if validated_token.get(TOKEN_USE_CLAIM) == SMART_TOKEN_USE and not request.path.startswith(
            SMART_ALLOWED_PATH_PREFIX
        ):
            raise AuthenticationFailed(
                {
                    "code": "SMART_TOKEN_WRONG_AUDIENCE",
                    "message": "Token SMART-on-FHIR válido apenas nos endpoints FHIR.",
                }
            )
        return result

    def get_user(self, validated_token):
        user = super().get_user(validated_token)

        if not user.is_active:
            raise AuthenticationFailed({"code": "USER_INACTIVE", "message": "Conta desativada."})

        enforce_request_membership(user, validated_token)
        return user
