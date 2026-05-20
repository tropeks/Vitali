"""
Integration tests for the FHIR R4 Encounter REST surface (read + search +
capability statement listing).
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from rest_framework.test import APIClient

from apps.core.models import FeatureFlag, Role, User
from apps.emr.models import Encounter, Patient, Professional
from apps.test_utils import TenantTestCase

ENCOUNTER_SEARCH_URL = "/api/v1/fhir/Encounter/"
METADATA_URL = "/api/v1/fhir/metadata"


def _encounter_read_url(pk):
    return f"/api/v1/fhir/Encounter/{pk}/"


def _make_user(*, role_name: str, perms: list[str], full_name: str = "Dra Ana Silva") -> User:
    role, _ = Role.objects.get_or_create(name=role_name, defaults={"permissions": perms})
    role.permissions = perms
    role.save()
    return User.objects.create_user(
        email=f"{role_name}@test.com", password="pw", role=role, full_name=full_name
    )


class FHIREncounterViewsTest(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="fhir",
            defaults={"is_enabled": True},
        )
        self.user = _make_user(role_name="fhir_enc_reader", perms=["fhir.read"])
        self.client.force_authenticate(user=self.user)

        self.patient = Patient.objects.create(
            full_name="Bruno Lima",
            cpf="98765432100",
            birth_date=date(1990, 3, 1),
            gender="M",
        )
        self.professional = Professional.objects.create(
            user=self.user,
            council_type="CRM",
            council_number="100200",
            council_state="SP",
        )
        self.enc_open = Encounter.objects.create(
            patient=self.patient,
            professional=self.professional,
            status="open",
            chief_complaint="Tosse seca há 5 dias.",
            encounter_date=datetime(2026, 5, 20, 9, 30, tzinfo=UTC),
        )
        self.enc_signed = Encounter.objects.create(
            patient=self.patient,
            professional=self.professional,
            status="signed",
            encounter_date=datetime(2026, 5, 15, 14, 0, tzinfo=UTC),
            signed_at=datetime(2026, 5, 15, 14, 25, tzinfo=UTC),
        )

    # ─── Capability statement now advertises Encounter ────────────────────────

    def test_capability_statement_lists_encounter_resource(self):
        self.client.logout()
        resp = self.client.get(METADATA_URL)
        self.assertEqual(resp.status_code, 200)
        types = {r["type"] for r in resp.data["rest"][0]["resource"]}
        self.assertIn("Encounter", types)
        self.assertIn("Patient", types)

    # ─── Read ────────────────────────────────────────────────────────────────

    def test_read_returns_fhir_encounter(self):
        resp = self.client.get(_encounter_read_url(self.enc_open.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["resourceType"], "Encounter")
        self.assertEqual(resp.data["id"], str(self.enc_open.pk))
        self.assertEqual(resp.data["status"], "in-progress")
        self.assertEqual(resp.data["subject"]["reference"], f"Patient/{self.patient.pk}")
        participant = resp.data["participant"][0]
        self.assertEqual(
            participant["individual"]["reference"], f"Practitioner/{self.professional.pk}"
        )
        self.assertEqual(resp.data["reasonCode"][0]["text"], "Tosse seca há 5 dias.")

    def test_read_signed_encounter_has_period_end(self):
        resp = self.client.get(_encounter_read_url(self.enc_signed.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "finished")
        self.assertIn("end", resp.data["period"])

    def test_read_returns_404_for_unknown_id(self):
        resp = self.client.get(_encounter_read_url("00000000-0000-4000-8000-000000000000"))
        self.assertEqual(resp.status_code, 404)

    # ─── Search ──────────────────────────────────────────────────────────────

    def test_search_by_subject_patient_reference(self):
        resp = self.client.get(ENCOUNTER_SEARCH_URL, {"subject": f"Patient/{self.patient.pk}"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["resourceType"], "Bundle")
        self.assertGreaterEqual(resp.data["total"], 2)
        ids = {entry["resource"]["id"] for entry in resp.data["entry"]}
        self.assertIn(str(self.enc_open.pk), ids)
        self.assertIn(str(self.enc_signed.pk), ids)

    def test_search_by_patient_alias(self):
        resp = self.client.get(ENCOUNTER_SEARCH_URL, {"patient": str(self.patient.pk)})
        self.assertEqual(resp.status_code, 200)
        ids = {entry["resource"]["id"] for entry in resp.data["entry"]}
        self.assertIn(str(self.enc_open.pk), ids)

    def test_search_by_status_in_progress_filters_correctly(self):
        resp = self.client.get(
            ENCOUNTER_SEARCH_URL,
            {"subject": f"Patient/{self.patient.pk}", "status": "in-progress"},
        )
        self.assertEqual(resp.status_code, 200)
        ids = {entry["resource"]["id"] for entry in resp.data["entry"]}
        self.assertIn(str(self.enc_open.pk), ids)
        self.assertNotIn(str(self.enc_signed.pk), ids)

    def test_search_by_status_finished(self):
        resp = self.client.get(
            ENCOUNTER_SEARCH_URL,
            {"subject": f"Patient/{self.patient.pk}", "status": "finished"},
        )
        self.assertEqual(resp.status_code, 200)
        ids = {entry["resource"]["id"] for entry in resp.data["entry"]}
        self.assertIn(str(self.enc_signed.pk), ids)
        self.assertNotIn(str(self.enc_open.pk), ids)

    def test_search_with_unknown_status_returns_empty(self):
        resp = self.client.get(ENCOUNTER_SEARCH_URL, {"status": "triaged"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["total"], 0)

    # ─── Gates ────────────────────────────────────────────────────────────────

    def test_search_blocked_when_module_disabled(self):
        FeatureFlag.objects.filter(tenant=self.__class__.tenant, module_key="fhir").update(
            is_enabled=False
        )
        resp = self.client.get(ENCOUNTER_SEARCH_URL)
        self.assertEqual(resp.status_code, 403)

    def test_read_blocked_without_fhir_read_permission(self):
        no_perm = _make_user(role_name="no_fhir_enc", perms=["patients.read"])
        self.client.force_authenticate(user=no_perm)
        resp = self.client.get(_encounter_read_url(self.enc_open.pk))
        self.assertEqual(resp.status_code, 403)
