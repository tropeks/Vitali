"""
Security tests for SMART-on-FHIR token scoping:

1. Audience restriction — a SMART-minted token must NOT work outside the FHIR
   surface (it is an OAuth grant to a third-party app, not a full Vitali login).
2. Scope enforcement — a SMART token without a read scope cannot read resources.
3. Patient-compartment confinement — a token granted only ``patient/*.read`` is
   confined to its launch-context patient across reads and searches.
4. ``user/*.read`` grants user-level (tenant-wide, RBAC-bound) access.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, date, datetime
from urllib.parse import parse_qs, urlparse

from rest_framework.test import APIClient

from apps.core.models import FeatureFlag, Role, User
from apps.emr.models import Allergy, Encounter, Patient, Professional
from apps.fhir.models import SmartClient
from apps.fhir.services import smart
from apps.test_utils import TenantTestCase

AUTHORIZE_URL = "/api/v1/fhir/auth/authorize"
TOKEN_URL = "/api/v1/fhir/auth/token"
PATIENT_SEARCH = "/api/v1/fhir/Patient/"
ALLERGY_SEARCH = "/api/v1/fhir/AllergyIntolerance/"
ENCOUNTER_SEARCH = "/api/v1/fhir/Encounter/"
NON_FHIR_URL = "/api/v1/me"

REDIRECT_URI = "https://app.example.org/callback"
VERIFIER = "a-test-code-verifier-of-sufficient-length-0123456789"


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class SmartScopeEnforcementTest(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="fhir",
            defaults={"is_enabled": True},
        )
        role, _ = Role.objects.get_or_create(
            name="fhir_scope", defaults={"permissions": ["fhir.read"]}
        )
        role.permissions = ["fhir.read"]
        role.save()
        self.user = User.objects.create_user(
            email="fhir_scope@test.com", password="pw", role=role, full_name="Scoped MD"
        )
        self.smart_client = SmartClient.objects.create(
            client_id="scoped-app",
            client_name="Scoped SPA",
            is_confidential=False,
            redirect_uris=REDIRECT_URI,
            scopes="openid launch/patient patient/*.read user/*.read",
        )
        self.patient_a = Patient.objects.create(
            full_name="Alice Contexto",
            cpf="12345678909",
            birth_date=date(1980, 1, 1),
            gender="F",
        )
        self.patient_b = Patient.objects.create(
            full_name="Bruno Outro",
            cpf="98765432100",
            birth_date=date(1975, 2, 2),
            gender="M",
        )
        self.allergy_a = Allergy.objects.create(
            patient=self.patient_a, substance="Penicilina", severity="severe", status="active"
        )
        self.allergy_b = Allergy.objects.create(
            patient=self.patient_b, substance="Dipirona", severity="mild", status="active"
        )

    def _bearer(self, *, scope: str, patient_id: str = "") -> None:
        token = smart.mint_access_token(self.user, scope=scope, patient_id=patient_id)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    # ─── 1. Audience restriction ─────────────────────────────────────────────

    def test_smart_token_rejected_outside_fhir_surface(self):
        self._bearer(scope="user/*.read")
        resp = self.client.get(NON_FHIR_URL)
        self.assertEqual(resp.status_code, 401)

    def test_smart_token_accepted_on_fhir_surface(self):
        self._bearer(scope="user/*.read")
        resp = self.client.get(PATIENT_SEARCH)
        self.assertEqual(resp.status_code, 200)

    def test_regular_login_token_unaffected_outside_fhir(self):
        from apps.core.tenant_auth import tokens_for_user

        refresh = tokens_for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
        resp = self.client.get(NON_FHIR_URL)
        self.assertEqual(resp.status_code, 200)

    # ─── 2. Scope enforcement ────────────────────────────────────────────────

    def test_smart_token_without_read_scope_is_forbidden(self):
        self._bearer(scope="openid")
        resp = self.client.get(PATIENT_SEARCH)
        self.assertEqual(resp.status_code, 403)

    def test_patient_scope_without_patient_context_is_forbidden(self):
        self._bearer(scope="patient/*.read")
        resp = self.client.get(PATIENT_SEARCH)
        self.assertEqual(resp.status_code, 403)

    # ─── 3. Patient-compartment confinement ──────────────────────────────────

    def test_patient_scoped_token_search_confined_to_context_patient(self):
        self._bearer(scope="patient/*.read", patient_id=str(self.patient_a.pk))
        resp = self.client.get(PATIENT_SEARCH)
        self.assertEqual(resp.status_code, 200)
        ids = {e["resource"]["id"] for e in resp.data["entry"]}
        self.assertEqual(ids, {str(self.patient_a.pk)})

        resp = self.client.get(ALLERGY_SEARCH)
        ids = {e["resource"]["id"] for e in resp.data["entry"]}
        self.assertEqual(ids, {str(self.allergy_a.pk)})

    def test_patient_scoped_token_cannot_widen_via_search_param(self):
        self._bearer(scope="patient/*.read", patient_id=str(self.patient_a.pk))
        resp = self.client.get(ALLERGY_SEARCH, {"patient": str(self.patient_b.pk)})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["total"], 0)

    def test_patient_scoped_token_read_of_other_patient_is_404(self):
        self._bearer(scope="patient/*.read", patient_id=str(self.patient_a.pk))
        resp = self.client.get(f"{PATIENT_SEARCH}{self.patient_b.pk}/")
        self.assertEqual(resp.status_code, 404)
        resp = self.client.get(f"{ALLERGY_SEARCH}{self.allergy_b.pk}/")
        self.assertEqual(resp.status_code, 404)

    def test_patient_scoped_token_read_of_context_patient_ok(self):
        self._bearer(scope="patient/*.read", patient_id=str(self.patient_a.pk))
        resp = self.client.get(f"{PATIENT_SEARCH}{self.patient_a.pk}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["id"], str(self.patient_a.pk))

    def test_malformed_patient_context_matches_nothing(self):
        self._bearer(scope="patient/*.read", patient_id="not-a-uuid")
        resp = self.client.get(PATIENT_SEARCH)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["total"], 0)

    # ─── 4. user/*.read is user-level ────────────────────────────────────────

    def test_user_scoped_token_is_not_confined(self):
        self._bearer(scope="user/*.read", patient_id=str(self.patient_a.pk))
        resp = self.client.get(PATIENT_SEARCH)
        ids = {e["resource"]["id"] for e in resp.data["entry"]}
        self.assertEqual(ids, {str(self.patient_a.pk), str(self.patient_b.pk)})

    # ─── End-to-end through the real OAuth flow ──────────────────────────────

    def test_full_flow_token_is_patient_confined(self):
        self.client.force_authenticate(user=self.user)
        resp = self.client.get(
            AUTHORIZE_URL,
            {
                "response_type": "code",
                "client_id": "scoped-app",
                "redirect_uri": REDIRECT_URI,
                "scope": "openid patient/*.read",
                "code_challenge": _challenge(VERIFIER),
                "code_challenge_method": "S256",
                "patient": str(self.patient_a.pk),
            },
        )
        self.assertEqual(resp.status_code, 302)
        code = parse_qs(urlparse(resp["Location"]).query)["code"][0]
        self.client.force_authenticate(user=None)

        token_resp = self.client.post(
            TOKEN_URL,
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": "scoped-app",
                "code_verifier": VERIFIER,
            },
        )
        self.assertEqual(token_resp.status_code, 200)
        self.assertEqual(token_resp.data["patient"], str(self.patient_a.pk))

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_resp.data['access_token']}")
        search = self.client.get(ENCOUNTER_SEARCH)
        self.assertEqual(search.status_code, 200)
        # And the token must not work outside FHIR.
        outside = self.client.get(NON_FHIR_URL)
        self.assertEqual(outside.status_code, 401)


class SmartConfinementAcrossResourcesTest(TenantTestCase):
    """Spot-check confinement on an encounter-joined resource (Encounter itself)."""

    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="fhir",
            defaults={"is_enabled": True},
        )
        role, _ = Role.objects.get_or_create(
            name="fhir_scope2", defaults={"permissions": ["fhir.read"]}
        )
        role.permissions = ["fhir.read"]
        role.save()
        self.user = User.objects.create_user(
            email="fhir_scope2@test.com", password="pw", role=role, full_name="Dra Scoped"
        )
        self.professional = Professional.objects.create(
            user=self.user, council_type="CRM", council_number="900100", council_state="SP"
        )
        self.patient_a = Patient.objects.create(
            full_name="Alice Contexto",
            cpf="12345678909",
            birth_date=date(1980, 1, 1),
            gender="F",
        )
        self.patient_b = Patient.objects.create(
            full_name="Bruno Outro",
            cpf="98765432100",
            birth_date=date(1975, 2, 2),
            gender="M",
        )
        self.enc_a = Encounter.objects.create(
            patient=self.patient_a,
            professional=self.professional,
            status="signed",
            encounter_date=datetime(2026, 5, 1, 9, 0, tzinfo=UTC),
        )
        self.enc_b = Encounter.objects.create(
            patient=self.patient_b,
            professional=self.professional,
            status="signed",
            encounter_date=datetime(2026, 5, 2, 9, 0, tzinfo=UTC),
        )

    def test_encounter_search_and_read_confined(self):
        token = smart.mint_access_token(
            self.user, scope="patient/*.read", patient_id=str(self.patient_a.pk)
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        search = self.client.get(ENCOUNTER_SEARCH)
        self.assertEqual(search.status_code, 200)
        ids = {e["resource"]["id"] for e in search.data["entry"]}
        self.assertEqual(ids, {str(self.enc_a.pk)})

        ok = self.client.get(f"{ENCOUNTER_SEARCH}{self.enc_a.pk}/")
        self.assertEqual(ok.status_code, 200)
        denied = self.client.get(f"{ENCOUNTER_SEARCH}{self.enc_b.pk}/")
        self.assertEqual(denied.status_code, 404)
