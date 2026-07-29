"""
Authz tests for the AI Scribe endpoints (CSO finding 3 — IDOR of clinical data).

ScribeStatusView returns the SOAP note (clinical PHI) and ScribeStartView
dispatches clinical-note generation, both by encounter id with no role gate.
They must be gated on emr.read (status) / emr.write (start): a role without the
permission gets 403; a clinical role passes the gate.
"""

import datetime

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.test_utils import TenantTestCase


@override_settings(FEATURE_AI_SCRIBE=True)
class TestScribeAuthz(TenantTestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        from apps.core.models import Role
        from apps.core.permissions import DEFAULT_ROLES
        from apps.emr.models import Encounter, Patient, Professional

        User = get_user_model()

        # Role WITHOUT emr.read/write (front-desk-like).
        self.no_emr_role = Role.objects.create(
            name="recepcao_scribe_authz", permissions=["patients.read"]
        )
        self.clinical_role = Role.objects.create(
            name="medico_scribe_authz", permissions=DEFAULT_ROLES["medico"]
        )

        self.no_emr_user = User.objects.create_user(
            email="recep_scribe_authz@clinic.test",
            password="TestPass123!",
            full_name="Recep Scribe",
            role=self.no_emr_role,
        )
        self.clinical_user = User.objects.create_user(
            email="medico_scribe_authz@clinic.test",
            password="TestPass123!",
            full_name="Dr Scribe",
            role=self.clinical_role,
        )

        self.patient = Patient.objects.create(
            full_name="Scribe Authz Patient",
            cpf="222.333.444-55",
            birth_date=datetime.date(1980, 6, 15),
            gender="M",
        )
        self.professional = Professional.objects.create(
            user=self.clinical_user,
            council_type="CRM",
            council_number="321321",
            council_state="SP",
        )
        self.encounter = Encounter.objects.create(
            patient=self.patient,
            professional=self.professional,
            encounter_date=timezone.now(),
        )

    def _client_for(self, user):
        client = APIClient()
        client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        refresh = RefreshToken.for_user(user)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}")
        return client

    def test_status_denied_without_emr_read(self):
        """GET scribe/status/ (reads SOAP/PHI) → 403 for a role without emr.read."""
        client = self._client_for(self.no_emr_user)
        r = client.get(f"/api/v1/encounters/{self.encounter.pk}/scribe/status/")
        self.assertEqual(r.status_code, 403)

    def test_start_denied_without_emr_write(self):
        """POST scribe/start/ (generates clinical note) → 403 without emr.write."""
        client = self._client_for(self.no_emr_user)
        r = client.post(
            f"/api/v1/encounters/{self.encounter.pk}/scribe/start/",
            {"transcription": "paciente relata cefaleia"},
            format="json",
        )
        self.assertEqual(r.status_code, 403)

    def test_status_allowed_with_emr_read(self):
        """A clinical role with emr.read passes the gate (no session yet → 200)."""
        client = self._client_for(self.clinical_user)
        r = client.get(f"/api/v1/encounters/{self.encounter.pk}/scribe/status/")
        # Passes authz; no session exists yet.
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "none")
