"""
Integration tests for the SMART-on-FHIR / OAuth2 authorization server:
discovery, the authorization-code grant with PKCE, and the token endpoint.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import FeatureFlag, Role, User
from apps.fhir.models import SmartAuthorizationCode, SmartClient
from apps.test_utils import TenantTestCase

SMART_CONFIG_URL = "/api/v1/fhir/.well-known/smart-configuration"
AUTHORIZE_URL = "/api/v1/fhir/auth/authorize"
TOKEN_URL = "/api/v1/fhir/auth/token"
METADATA_URL = "/api/v1/fhir/metadata"

REDIRECT_URI = "https://app.example.org/callback"
VERIFIER = "a-test-code-verifier-of-sufficient-length-0123456789"


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _make_user(*, role_name: str, perms: list[str]) -> User:
    role, _ = Role.objects.get_or_create(name=role_name, defaults={"permissions": perms})
    role.permissions = perms
    role.save()
    return User.objects.create_user(email=f"{role_name}@test.com", password="pw", role=role)


class SmartConfigurationTest(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain

    def test_smart_configuration_is_public(self):
        resp = self.client.get(SMART_CONFIG_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("authorization_endpoint", resp.data)
        self.assertIn("token_endpoint", resp.data)
        self.assertIn("authorization_code", resp.data["grant_types_supported"])
        self.assertIn("S256", resp.data["code_challenge_methods_supported"])
        self.assertIn("patient/*.read", resp.data["scopes_supported"])

    def test_capability_statement_advertises_smart_security(self):
        resp = self.client.get(METADATA_URL)
        security = resp.data["rest"][0]["security"]
        codes = {coding["code"] for service in security["service"] for coding in service["coding"]}
        self.assertIn("SMART-on-FHIR", codes)
        # The oauth-uris extension must point at the authorize + token endpoints.
        ext_urls = {e["url"] for e in security["extension"][0]["extension"]}
        self.assertEqual(ext_urls, {"authorize", "token"})


class SmartAuthorizationCodeFlowTest(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="fhir",
            defaults={"is_enabled": True},
        )
        self.user = _make_user(role_name="fhir_smart", perms=["fhir.read"])
        self.public_client = SmartClient.objects.create(
            client_id="public-app",
            client_name="Public SPA",
            is_confidential=False,
            redirect_uris=REDIRECT_URI,
            scopes="openid patient/*.read launch/patient",
        )

    def _authorize(self, **overrides):
        params = {
            "response_type": "code",
            "client_id": "public-app",
            "redirect_uri": REDIRECT_URI,
            "scope": "openid patient/*.read",
            "state": "xyz",
            "code_challenge": _challenge(VERIFIER),
            "code_challenge_method": "S256",
        }
        params.update(overrides)
        self.client.force_authenticate(user=self.user)
        return self.client.get(AUTHORIZE_URL, params)

    # ─── Authorize endpoint ──────────────────────────────────────────────────

    def test_authorize_requires_authentication(self):
        resp = self.client.get(
            AUTHORIZE_URL,
            {"response_type": "code", "client_id": "public-app", "redirect_uri": REDIRECT_URI},
        )
        self.assertIn(resp.status_code, (401, 403))

    def test_authorize_issues_code_and_redirects(self):
        resp = self._authorize()
        self.assertEqual(resp.status_code, 302)
        location = urlparse(resp["Location"])
        query = parse_qs(location.query)
        self.assertTrue(location.geturl().startswith(REDIRECT_URI))
        self.assertIn("code", query)
        self.assertEqual(query["state"][0], "xyz")
        # The code is persisted, single-use, and not yet redeemed.
        code = SmartAuthorizationCode.objects.get(code=query["code"][0])
        self.assertIsNone(code.used_at)
        self.assertTrue(code.is_redeemable())

    def test_authorize_rejects_unknown_client(self):
        resp = self._authorize(client_id="ghost")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["error"], "invalid_client")

    def test_authorize_rejects_unregistered_redirect_uri(self):
        resp = self._authorize(redirect_uri="https://evil.example.com/x")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["error"], "invalid_request")

    def test_authorize_requires_pkce_for_public_client(self):
        resp = self._authorize(code_challenge="", code_challenge_method="")
        # Error is delivered back via the redirect (client_id+redirect_uri valid).
        self.assertEqual(resp.status_code, 302)
        query = parse_qs(urlparse(resp["Location"]).query)
        self.assertEqual(query["error"][0], "invalid_request")

    # ─── Token endpoint ──────────────────────────────────────────────────────

    def _get_code(self, **overrides) -> str:
        resp = self._authorize(**overrides)
        self.assertEqual(resp.status_code, 302)
        self.client.force_authenticate(user=None)  # token endpoint is unauthenticated
        return parse_qs(urlparse(resp["Location"]).query)["code"][0]

    def test_full_authorization_code_grant_with_pkce(self):
        code = self._get_code()
        resp = self.client.post(
            TOKEN_URL,
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": "public-app",
                "code_verifier": VERIFIER,
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("access_token", resp.data)
        self.assertEqual(resp.data["token_type"], "Bearer")
        self.assertGreater(resp.data["expires_in"], 0)
        self.assertIn("patient/*.read", resp.data["scope"])

    def test_token_rejects_bad_pkce_verifier(self):
        code = self._get_code()
        resp = self.client.post(
            TOKEN_URL,
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": "public-app",
                "code_verifier": "the-wrong-verifier",
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["error"], "invalid_grant")

    def test_authorization_code_is_single_use(self):
        code = self._get_code()
        body = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": "public-app",
            "code_verifier": VERIFIER,
        }
        first = self.client.post(TOKEN_URL, body)
        self.assertEqual(first.status_code, 200)
        replay = self.client.post(TOKEN_URL, body)
        self.assertEqual(replay.status_code, 400)
        self.assertEqual(replay.data["error"], "invalid_grant")

    def test_token_rejects_redirect_uri_mismatch(self):
        code = self._get_code()
        resp = self.client.post(
            TOKEN_URL,
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://app.example.org/other",
                "client_id": "public-app",
                "code_verifier": VERIFIER,
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["error"], "invalid_grant")

    def test_token_rejects_expired_code(self):
        code = self._get_code()
        SmartAuthorizationCode.objects.filter(code=code).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        resp = self.client.post(
            TOKEN_URL,
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": "public-app",
                "code_verifier": VERIFIER,
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["error"], "invalid_grant")

    def test_token_rejects_unsupported_grant_type(self):
        resp = self.client.post(TOKEN_URL, {"grant_type": "client_credentials"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["error"], "unsupported_grant_type")

    def test_launch_patient_context_returned_in_token(self):
        code = self._get_code(patient="patient-123")
        resp = self.client.post(
            TOKEN_URL,
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": "public-app",
                "code_verifier": VERIFIER,
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["patient"], "patient-123")


class SmartConfidentialClientTest(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="fhir",
            defaults={"is_enabled": True},
        )
        self.user = _make_user(role_name="fhir_conf", perms=["fhir.read"])
        self.confidential = SmartClient.objects.create(
            client_id="backend-svc",
            client_name="Confidential Service",
            is_confidential=True,
            client_secret="s3cr3t",
            redirect_uris=REDIRECT_URI,
        )

    def test_confidential_client_does_not_require_pkce(self):
        self.client.force_authenticate(user=self.user)
        resp = self.client.get(
            AUTHORIZE_URL,
            {
                "response_type": "code",
                "client_id": "backend-svc",
                "redirect_uri": REDIRECT_URI,
                "scope": "patient/*.read",
            },
        )
        self.assertEqual(resp.status_code, 302)
        code = parse_qs(urlparse(resp["Location"]).query)["code"][0]

        self.client.force_authenticate(user=None)
        ok = self.client.post(
            TOKEN_URL,
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": "backend-svc",
                "client_secret": "s3cr3t",
            },
        )
        self.assertEqual(ok.status_code, 200)
        self.assertIn("access_token", ok.data)

    def test_token_rejects_wrong_client_secret(self):
        self.client.force_authenticate(user=self.user)
        resp = self.client.get(
            AUTHORIZE_URL,
            {
                "response_type": "code",
                "client_id": "backend-svc",
                "redirect_uri": REDIRECT_URI,
            },
        )
        code = parse_qs(urlparse(resp["Location"]).query)["code"][0]

        self.client.force_authenticate(user=None)
        bad = self.client.post(
            TOKEN_URL,
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": "backend-svc",
                "client_secret": "wrong",
            },
        )
        self.assertEqual(bad.status_code, 401)
        self.assertEqual(bad.data["error"], "invalid_client")
