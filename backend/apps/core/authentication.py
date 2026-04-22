"""
Custom JWT Authentication for Vitali.
Validates tenant membership and user.is_active.
"""

from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication


class TenantJWTAuthentication(JWTAuthentication):
    """
    Extends SimpleJWT to:
    1. Ensure the user is active.
    2. Ensure the user belongs to the current tenant's schema
       (django-tenants already scopes the DB query to the correct schema).
    """

    def get_user(self, validated_token):
        user = super().get_user(validated_token)

        if not user.is_active:
            raise AuthenticationFailed({"code": "USER_INACTIVE", "message": "Conta desativada."})

        return user
