"""
SMART-on-FHIR / OAuth2 authorization server endpoints.

Implements the standalone SMART App Launch authorization-code grant (with PKCE):

- ``GET  /api/v1/fhir/.well-known/smart-configuration`` — discovery document.
- ``GET/POST /api/v1/fhir/auth/authorize`` — authorization endpoint. The end user
  is authenticated by the Vitali platform itself (Bearer JWT / portal session):
  Vitali is both the resource server and the identity provider, so the authorize
  endpoint requires an authenticated tenant user rather than rendering its own
  login/consent page. On success it issues a single-use authorization code and
  302-redirects back to the app's ``redirect_uri``.
- ``POST /api/v1/fhir/auth/token`` — token endpoint. Exchanges the authorization
  code (validating PKCE / client secret) for a tenant-bound access token.

Access tokens are ordinary Vitali JWTs, so the downstream FHIR resource endpoints
keep their existing ``IsAuthenticated`` + module + ``fhir.read`` gating unchanged.
"""

from __future__ import annotations

import hmac
import secrets
from datetime import timedelta
from urllib.parse import urlencode

from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import ModuleRequiredPermission

from .models import SmartAuthorizationCode, SmartClient
from .services import smart

_FHIR_MODULE = ModuleRequiredPermission("fhir")


def _abs(request, name: str) -> str:
    try:
        return request.build_absolute_uri(reverse(name))
    except Exception:
        return reverse(name)


def _oauth_error(error: str, description: str, *, http_status: int = status.HTTP_400_BAD_REQUEST):
    return Response({"error": error, "error_description": description}, status=http_status)


def _redirect_with(redirect_uri: str, params: dict[str, str]) -> HttpResponseRedirect:
    separator = "&" if "?" in redirect_uri else "?"
    return HttpResponseRedirect(f"{redirect_uri}{separator}{urlencode(params)}")


class SmartConfigurationView(APIView):
    """GET /api/v1/fhir/.well-known/smart-configuration — SMART discovery doc.

    Public, like the CapabilityStatement: clients must discover the authorization
    server before they can authenticate.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        return Response(
            {
                "issuer": request.build_absolute_uri("/").rstrip("/"),
                "authorization_endpoint": _abs(request, "fhir-smart-authorize"),
                "token_endpoint": _abs(request, "fhir-smart-token"),
                "token_endpoint_auth_methods_supported": ["client_secret_post", "none"],
                "grant_types_supported": smart.GRANT_TYPES,
                "response_types_supported": smart.RESPONSE_TYPES,
                "scopes_supported": smart.SUPPORTED_SCOPES,
                "code_challenge_methods_supported": smart.CODE_CHALLENGE_METHODS,
                "capabilities": smart.SMART_CAPABILITIES,
            }
        )


class AuthorizeView(APIView):
    """GET/POST /api/v1/fhir/auth/authorize — OAuth2 authorization endpoint."""

    def get_permissions(self):
        return [IsAuthenticated(), _FHIR_MODULE]

    def get(self, request):
        return self._authorize(request, request.query_params)

    def post(self, request):
        return self._authorize(request, request.data)

    def _authorize(self, request, params):
        client_id = params.get("client_id")
        redirect_uri = params.get("redirect_uri")

        # Pre-redirect validation: client_id + redirect_uri must be valid before we
        # are willing to redirect anywhere (RFC 6749 §4.1.2.1).
        if not client_id or not redirect_uri:
            return _oauth_error("invalid_request", "client_id and redirect_uri are required.")
        try:
            client = SmartClient.objects.get(client_id=client_id, is_active=True)
        except SmartClient.DoesNotExist:
            return _oauth_error("invalid_client", "Unknown or inactive client_id.")
        if not client.allows_redirect_uri(redirect_uri):
            return _oauth_error(
                "invalid_request", "redirect_uri is not registered for this client."
            )

        state = params.get("state", "")
        response_type = params.get("response_type")
        if response_type != "code":
            return _redirect_with(
                redirect_uri,
                {"error": "unsupported_response_type", "state": state},
            )

        code_challenge = params.get("code_challenge", "")
        code_challenge_method = (
            params.get("code_challenge_method", "S256") if code_challenge else ""
        )
        if not code_challenge and not client.is_confidential:
            return _redirect_with(
                redirect_uri,
                {
                    "error": "invalid_request",
                    "error_description": "PKCE code_challenge is required for public clients.",
                    "state": state,
                },
            )
        if code_challenge and code_challenge_method not in smart.CODE_CHALLENGE_METHODS:
            return _redirect_with(
                redirect_uri,
                {
                    "error": "invalid_request",
                    "error_description": "Unsupported code_challenge_method.",
                    "state": state,
                },
            )

        scope = smart.filter_requested_scopes(params.get("scope", ""), client=client)
        # Optional standalone launch context: ?patient=<uuid>.
        patient_id = (params.get("patient") or params.get("launch/patient") or "").strip()

        code = secrets.token_urlsafe(32)
        SmartAuthorizationCode.objects.create(
            code=code,
            client=client,
            user=request.user,
            redirect_uri=redirect_uri,
            scope=scope,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            patient_id=patient_id,
            expires_at=timezone.now() + timedelta(seconds=smart.AUTH_CODE_TTL_SECONDS),
        )
        result = {"code": code}
        if state:
            result["state"] = state
        return _redirect_with(redirect_uri, result)


class TokenView(APIView):
    """POST /api/v1/fhir/auth/token — OAuth2 token endpoint (authorization_code)."""

    permission_classes = [AllowAny]

    def post(self, request):
        params = request.data
        grant_type = params.get("grant_type")
        if grant_type != "authorization_code":
            return _oauth_error("unsupported_grant_type", "Only authorization_code is supported.")

        code = params.get("code")
        redirect_uri = params.get("redirect_uri")
        client_id = params.get("client_id")
        if not code or not redirect_uri or not client_id:
            return _oauth_error("invalid_request", "code, redirect_uri and client_id are required.")

        try:
            client = SmartClient.objects.get(client_id=client_id, is_active=True)
        except SmartClient.DoesNotExist:
            return _oauth_error("invalid_client", "Unknown or inactive client_id.", http_status=401)

        # Confidential clients must authenticate with their secret.
        if client.is_confidential:
            provided_secret = params.get("client_secret", "")
            if not provided_secret or not hmac.compare_digest(
                provided_secret, client.client_secret
            ):
                return _oauth_error(
                    "invalid_client", "Client authentication failed.", http_status=401
                )

        try:
            auth_code = SmartAuthorizationCode.objects.select_related("client", "user").get(
                code=code, client=client
            )
        except SmartAuthorizationCode.DoesNotExist:
            return _oauth_error("invalid_grant", "Authorization code not found.")

        if not auth_code.is_redeemable():
            return _oauth_error("invalid_grant", "Authorization code is expired or already used.")
        if auth_code.redirect_uri != redirect_uri:
            return _oauth_error("invalid_grant", "redirect_uri mismatch.")

        # PKCE: required whenever a challenge was issued (always, for public clients).
        if auth_code.code_challenge:
            verifier = params.get("code_verifier", "")
            if not smart.verify_pkce(
                code_challenge=auth_code.code_challenge,
                method=auth_code.code_challenge_method,
                verifier=verifier,
            ):
                return _oauth_error("invalid_grant", "PKCE verification failed.")

        # Single-use: burn the code before issuing the token.
        auth_code.used_at = timezone.now()
        auth_code.save(update_fields=["used_at"])

        access_token = smart.mint_access_token(auth_code.user, scope=auth_code.scope)
        body = {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": smart.access_token_ttl_seconds(),
            "scope": auth_code.scope,
        }
        if auth_code.patient_id:
            body["patient"] = auth_code.patient_id
        return Response(body, status=status.HTTP_200_OK)
