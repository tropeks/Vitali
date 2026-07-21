"""Tenant-membership binding for the global User table (Model B).

``User``/``Role`` live in the public schema (``apps.core`` is SHARED_APPS) — a single
global registry shared across tenants. A user is bound to a tenant only via
:class:`apps.core.models.UserTenantMembership`. These helpers stamp the tenant schema
into issued JWTs and enforce membership on each authenticated request, closing the
cross-tenant access hole (a clinic-A token must not work on clinic-B's domain).

Enforcement is gated by ``settings.ENFORCE_TENANT_MEMBERSHIP`` (default False) for a
safe two-step rollout: R1 deploy + migrate + backfill + verify, THEN R2 flip the env.
While the flag is off every check is a no-op, so a deploy/backfill window never locks
users out.
"""

from django.conf import settings
from django.db import connection
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.tokens import RefreshToken

PUBLIC_SCHEMA = "public"
SCHEMA_CLAIM = "schema"

# ── SMART-on-FHIR token audience restriction ─────────────────────────────────
# Access tokens minted by the SMART-on-FHIR token endpoint (apps.fhir) carry
# ``token_use="smart"``. They authenticate through the same TenantJWTAuthentication
# as regular login tokens, but are only honoured on the FHIR surface — a SMART app
# granted read scopes must never receive a token usable against the whole Vitali
# API as the authorizing user. The constants live here (not in apps.fhir) because
# apps.core must not import from domain apps (.importlinter).
TOKEN_USE_CLAIM = "token_use"
SMART_TOKEN_USE = "smart"
SMART_ALLOWED_PATH_PREFIX = "/api/v1/fhir/"


def enforcement_enabled() -> bool:
    return bool(getattr(settings, "ENFORCE_TENANT_MEMBERSHIP", False))


def tokens_for_user(user) -> RefreshToken:
    """A RefreshToken bound to the current tenant schema via the ``schema`` claim.

    SimpleJWT copies non-reserved claims onto the access token (and onto rotated
    refresh tokens), so a token minted for tenant A carries ``schema="A"`` and is
    detectable when replayed against tenant B. Callers may set further claims
    (email, role, mfa_verified) before stringifying.
    """
    refresh = RefreshToken.for_user(user)
    refresh[SCHEMA_CLAIM] = connection.schema_name  # type: ignore[attr-defined]
    return refresh


def _membership_exists(user, tenant) -> bool:
    # Imported lazily to avoid an import cycle (models import is heavy at app-load).
    from .models import UserTenantMembership

    return UserTenantMembership.objects.filter(user=user, tenant=tenant, is_active=True).exists()


def login_allowed(user) -> bool:
    """True if ``user`` may obtain tokens on the current tenant (login/mint path).

    Used at token-issuing endpoints. Returns a bool (not an exception) so the login
    view can answer with a generic 401 and avoid a cross-tenant enumeration oracle.
    """
    if not enforcement_enabled():
        return True
    schema = connection.schema_name  # type: ignore[attr-defined]
    if not schema or schema == PUBLIC_SCHEMA:
        return bool(user.is_superuser)
    if user.is_superuser:
        return True
    tenant = getattr(connection, "tenant", None)
    return tenant is not None and _membership_exists(user, tenant)


def enforce_request_membership(user, validated_token=None) -> None:
    """Raise :class:`AuthenticationFailed` unless ``user`` may act in this schema.

    Applied on every authenticated request (via ``TenantJWTAuthentication``). Rules
    (only when enforcement is enabled):

    * empty/unresolved schema → fail closed.
    * public schema → superuser only (platform ops); else 401.
    * tenant schema → the token's ``schema`` claim must match the current schema
      (defense-in-depth, catches replay even if a future path forgets the query),
      AND the user must be superuser OR hold an active membership.
    """
    if not enforcement_enabled():
        return
    schema = connection.schema_name  # type: ignore[attr-defined]
    if not schema:
        raise AuthenticationFailed({"code": "NO_TENANT", "message": "Tenant não resolvido."})
    if schema == PUBLIC_SCHEMA:
        if user.is_superuser:
            return
        raise AuthenticationFailed(
            {"code": "NO_TENANT_MEMBERSHIP", "message": "Acesso negado a este tenant."}
        )
    if validated_token is not None and validated_token.get(SCHEMA_CLAIM) != schema:
        raise AuthenticationFailed(
            {"code": "TOKEN_SCHEMA_MISMATCH", "message": "Token inválido para este domínio."}
        )
    if user.is_superuser:
        return
    tenant = getattr(connection, "tenant", None)
    if tenant is None or not _membership_exists(user, tenant):
        raise AuthenticationFailed(
            {"code": "NO_TENANT_MEMBERSHIP", "message": "Acesso negado a este tenant."}
        )


def enforce_refresh_membership(refresh_token) -> None:
    """Guard the token-refresh path (which never loads the user via ``get_user``).

    ``token_blacklist`` tables are per-schema, so rotation does not protect a token
    replayed cross-tenant — this binds refresh to the schema the token was minted
    for and re-checks membership. Raises :class:`InvalidToken` (→ 401) on mismatch.
    """
    if not enforcement_enabled():
        return
    schema = connection.schema_name  # type: ignore[attr-defined]
    if not schema:
        raise InvalidToken({"code": "NO_TENANT", "message": "Tenant não resolvido."})

    from .models import User

    uid = refresh_token.get("user_id")
    try:
        user = User.objects.get(pk=uid)
    except User.DoesNotExist:
        raise InvalidToken({"code": "USER_NOT_FOUND", "message": "Token inválido."}) from None

    if not user.is_active:
        raise InvalidToken({"code": "USER_INACTIVE", "message": "Conta desativada."})

    if schema == PUBLIC_SCHEMA:
        if user.is_superuser:
            return
        raise InvalidToken(
            {"code": "NO_TENANT_MEMBERSHIP", "message": "Token inválido para este domínio."}
        )
    if refresh_token.get(SCHEMA_CLAIM) != schema:
        raise InvalidToken(
            {"code": "TOKEN_SCHEMA_MISMATCH", "message": "Token inválido para este domínio."}
        )
    if user.is_superuser:
        return
    tenant = getattr(connection, "tenant", None)
    if tenant is None or not _membership_exists(user, tenant):
        raise InvalidToken(
            {"code": "NO_TENANT_MEMBERSHIP", "message": "Token inválido para este domínio."}
        )
