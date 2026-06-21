"""
SMART-on-FHIR helpers: scopes, discovery metadata, PKCE, and access-token minting.

Vitali exposes a read-only FHIR surface, so the advertised scopes are read scopes
plus the SMART launch/identity scopes. Access tokens are ordinary Vitali JWTs
(SimpleJWT ``AccessToken``) carrying the tenant ``schema`` claim — so a token
issued through the SMART flow is validated by the same ``TenantJWTAuthentication``
and module/permission gates as a token issued through the normal login, and is
bound to the tenant it was minted for.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import timedelta
from typing import cast

from django.conf import settings
from django.db import connection
from rest_framework_simplejwt.tokens import AccessToken

from apps.core.tenant_auth import SCHEMA_CLAIM

# Scopes advertised in discovery + CapabilityStatement. Read-only surface, so no
# write scopes. `patient/*.read` and `user/*.read` cover the resource types.
SUPPORTED_SCOPES: list[str] = [
    "openid",
    "profile",
    "fhirUser",
    "launch",
    "launch/patient",
    "offline_access",
    "patient/*.read",
    "user/*.read",
]

# SMART capabilities advertised at .well-known/smart-configuration.
SMART_CAPABILITIES: list[str] = [
    "launch-standalone",
    "client-public",
    "client-confidential-symmetric",
    "context-standalone-patient",
    "permission-patient",
    "permission-user",
    "authorize-post",
]

CODE_CHALLENGE_METHODS: list[str] = ["S256", "plain"]
GRANT_TYPES: list[str] = ["authorization_code"]
RESPONSE_TYPES: list[str] = ["code"]

# Authorization codes are short-lived and single-use.
AUTH_CODE_TTL_SECONDS = 300


def access_token_ttl_seconds() -> int:
    """Access-token lifetime in seconds, from the project's SIMPLE_JWT config."""
    lifetime = cast(timedelta, settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"])
    return int(lifetime.total_seconds())


def mint_access_token(user, *, scope: str) -> str:
    """Mint a tenant-bound FHIR access token (stringified JWT) for ``user``.

    Mirrors ``apps.core.tenant_auth.tokens_for_user``: stamps the current schema so
    the token is detectable if replayed against another tenant, and attaches the
    granted ``scope`` claim.
    """
    token = AccessToken.for_user(user)
    token[SCHEMA_CLAIM] = connection.schema_name  # type: ignore[attr-defined]
    token["scope"] = scope
    return str(token)


def filter_requested_scopes(requested: str, *, client) -> str:
    """Intersect the space-delimited requested scopes with what the client allows.

    A client with no explicitly configured scopes is treated as allowed to request
    any supported scope (sensible default for first-party clients). Unsupported
    scopes are always dropped.
    """
    requested_set = [s for s in requested.split() if s]
    allowed = client.allowed_scopes()
    granted: list[str] = []
    for scope in requested_set:
        if scope not in SUPPORTED_SCOPES:
            continue
        if allowed and scope not in allowed:
            continue
        granted.append(scope)
    return " ".join(granted)


def verify_pkce(*, code_challenge: str, method: str, verifier: str) -> bool:
    """Verify an RFC 7636 PKCE ``code_verifier`` against the stored challenge."""
    if not code_challenge:
        return False
    if not verifier:
        return False
    if method == "S256":
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return hmac.compare_digest(computed, code_challenge)
    # "plain" (or unspecified): verifier must equal the challenge verbatim.
    return hmac.compare_digest(verifier, code_challenge)
