"""
SMART-on-FHIR authorization models.

The FHIR resource surface itself is stateless (a read-only projection over
existing tenant data), but the SMART App Launch authorization-code flow needs two
small pieces of state, both tenant-scoped (each tenant's domain is its own FHIR
authorization server):

- :class:`SmartClient` — a registered OAuth2 client (a SMART app) with its allowed
  redirect URIs and granted scopes.
- :class:`SmartAuthorizationCode` — a short-lived, single-use authorization code
  minted at the authorize endpoint and redeemed for an access token at the token
  endpoint, carrying the PKCE challenge and optional launch (patient) context.

User identity lives in the public schema (``apps.core`` is SHARED_APPS); the FK
from this tenant-scoped table to ``core.User`` mirrors how ``apps.emr`` models
(e.g. ``ClinicalDocument.signed_by``) already reference it.
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone


class SmartClient(models.Model):
    """A registered SMART-on-FHIR / OAuth2 client application (per tenant)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client_id = models.CharField(max_length=128, unique=True, db_index=True)
    client_name = models.CharField(max_length=200)
    # Confidential clients authenticate with client_secret at the token endpoint;
    # public clients (e.g. SPAs / native apps) rely on PKCE instead.
    is_confidential = models.BooleanField(default=False)
    client_secret = models.CharField(max_length=255, blank=True)
    # Exact-match allow-list of redirect URIs (one per line); the redirect_uri in
    # an authorize/token request must be present verbatim.
    redirect_uris = models.TextField(help_text="One redirect URI per line.")
    # Space-delimited scopes this client may request (SMART scope syntax).
    scopes = models.TextField(default="", blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["client_name"]
        verbose_name = "SMART Client"
        verbose_name_plural = "SMART Clients"

    def __str__(self) -> str:
        return f"{self.client_name} ({self.client_id})"

    def redirect_uri_list(self) -> list[str]:
        return [uri.strip() for uri in self.redirect_uris.splitlines() if uri.strip()]

    def allows_redirect_uri(self, redirect_uri: str) -> bool:
        return redirect_uri in self.redirect_uri_list()

    def allowed_scopes(self) -> set[str]:
        return {s for s in self.scopes.split() if s}


class SmartAuthorizationCode(models.Model):
    """A short-lived, single-use OAuth2 authorization code (PKCE-capable)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=255, unique=True, db_index=True)
    client = models.ForeignKey(
        SmartClient, on_delete=models.CASCADE, related_name="authorization_codes"
    )
    user = models.ForeignKey(
        "core.User", on_delete=models.CASCADE, related_name="smart_authorization_codes"
    )
    redirect_uri = models.CharField(max_length=2000)
    scope = models.TextField(default="", blank=True)
    # PKCE (RFC 7636). code_challenge_method is "S256" or "plain"; empty when the
    # client did not use PKCE (only allowed for confidential clients).
    code_challenge = models.CharField(max_length=255, blank=True)
    code_challenge_method = models.CharField(max_length=10, blank=True)
    # Optional SMART launch context — the patient the app was launched for.
    patient_id = models.CharField(max_length=64, blank=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "SMART Authorization Code"
        verbose_name_plural = "SMART Authorization Codes"

    def __str__(self) -> str:
        return f"code:{self.code[:8]}… client:{self.client_id}"

    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    def is_redeemable(self) -> bool:
        return self.used_at is None and not self.is_expired()
