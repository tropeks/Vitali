"""
Integration tests for the FHIR R4 Observation and Condition REST surfaces.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from rest_framework.test import APIClient

from apps.core.models import FeatureFlag, Role, User
from apps.emr.models import Encounter, MedicalHistory, Patient, Professional, VitalSigns
from apps.test_utils import TenantTestCase

METADATA_URL = "/api/v1/fhir/metadata"
OBS_SEARCH = "/api/v1/fhir/Observation/"
COND_SEARCH = "/api/v1/fhir/Condition/"


def _obs_read(obs_id):
    return f"/api/v1/fhir/Observation/{obs_id}/"


def _cond_read(pk):
    return f"/api/v1/fhir/Condition/{pk}/"


def _make_user(*, role_name: str, perms: list[str], full_name: str = "Tester") -> User:
    role, _ = Role.objects.get_or_create(name=role_name, defaults={"permissions": perms})
    role.permissions = perms
    role.save()
    return User.objects.create_user(
        email=f"{role_name}@test.com", password="pw", role=role, full_name=full_name
    )


class FHIRObservationConditionViewsTest(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="fhir",
            defaults={"is_enabled": True},
        )
        self.user = _make_user(role_name="fhir_obs", perms=["fhir.read"], full_name="FHIR Bot")
        self.client.force_authenticate(user=self.user)

        self.patient = Patient.objects.create(
            full_name="Ana Maria Souza",
            cpf="12345678909",
            birth_date=date(1985, 7, 14),
            gender="F",
        )
        self.other_patient = Patient.objects.create(
            full_name="Bruno Lima",
            cpf="98765432100",
            birth_date=date(1990, 3, 1),
            gender="M",
        )
        self.md_user = _make_user(role_name="md_obs", perms=["fhir.read"], full_name="Dra Bia")
        self.professional = Professional.objects.create(
            user=self.md_user,
            council_type="CRM",
            council_number="700200",
            council_state="SP",
        )
        self.encounter = Encounter.objects.create(
            patient=self.patient,
            professional=self.professional,
            status="signed",
            encounter_date=datetime(2026, 5, 19, 9, 0, tzinfo=UTC),
        )
        self.vital = VitalSigns.objects.create(
            encounter=self.encounter,
            weight_kg=70,
            height_cm=170,
            blood_pressure_systolic=120,
            blood_pressure_diastolic=80,
            heart_rate=72,
            temperature_celsius=36,
            oxygen_saturation=98,
        )

        # Medical history rows
        self.hist_active = MedicalHistory.objects.create(
            patient=self.patient,
            condition="Diabetes Mellitus tipo 2",
            cid10_code="E11",
            type="chronic",
            status="active",
        )
        self.hist_surgical = MedicalHistory.objects.create(
            patient=self.patient,
            condition="Apendicectomia",
            cid10_code="K35",
            type="surgical",
            status="resolved",
        )
        self.other_hist = MedicalHistory.objects.create(
            patient=self.other_patient,
            condition="Hipertensão Arterial",
            cid10_code="I10",
            type="chronic",
            status="controlled",
        )

    # ─── Capability statement ────────────────────────────────────────────────

    def test_capability_statement_lists_observation_and_condition(self):
        self.client.logout()
        resp = self.client.get(METADATA_URL)
        types = {r["type"] for r in resp.data["rest"][0]["resource"]}
        self.assertIn("Observation", types)
        self.assertIn("Condition", types)

    # ─── Observation ─────────────────────────────────────────────────────────

    def test_observation_read_by_loinc(self):
        obs_id = f"{self.encounter.pk}_8480-6"  # systolic BP
        resp = self.client.get(_obs_read(obs_id))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["resourceType"], "Observation")
        self.assertEqual(resp.data["code"]["coding"][0]["code"], "8480-6")
        self.assertEqual(resp.data["valueQuantity"]["value"], 120.0)

    def test_observation_read_unknown_loinc_returns_404(self):
        obs_id = f"{self.encounter.pk}_00000-0"
        resp = self.client.get(_obs_read(obs_id))
        self.assertEqual(resp.status_code, 404)

    def test_observation_read_unknown_encounter_returns_404(self):
        obs_id = "00000000-0000-4000-8000-000000000000_8480-6"
        resp = self.client.get(_obs_read(obs_id))
        self.assertEqual(resp.status_code, 404)

    def test_observation_search_by_patient_returns_bundle(self):
        resp = self.client.get(OBS_SEARCH, {"patient": str(self.patient.pk)})
        self.assertEqual(resp.status_code, 200)
        codes = {entry["resource"]["code"]["coding"][0]["code"] for entry in resp.data["entry"]}
        # Should include several vitals from the single VitalSigns row
        assert "8480-6" in codes
        assert "29463-7" in codes

    def test_observation_search_by_encounter_and_code(self):
        resp = self.client.get(OBS_SEARCH, {"encounter": str(self.encounter.pk), "code": "8867-4"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["total"], 1)
        self.assertEqual(resp.data["entry"][0]["resource"]["valueQuantity"]["value"], 72.0)

    # ─── Condition ───────────────────────────────────────────────────────────

    def test_condition_read(self):
        resp = self.client.get(_cond_read(self.hist_active.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["resourceType"], "Condition")
        self.assertEqual(resp.data["code"]["coding"][0]["code"], "E11")
        self.assertEqual(resp.data["subject"]["reference"], f"Patient/{self.patient.pk}")

    def test_condition_search_by_patient(self):
        resp = self.client.get(COND_SEARCH, {"patient": str(self.patient.pk)})
        ids = {entry["resource"]["id"] for entry in resp.data["entry"]}
        self.assertIn(str(self.hist_active.pk), ids)
        self.assertIn(str(self.hist_surgical.pk), ids)
        self.assertNotIn(str(self.other_hist.pk), ids)

    def test_condition_search_by_clinical_status_resolved(self):
        resp = self.client.get(
            COND_SEARCH,
            {"patient": str(self.patient.pk), "clinical-status": "resolved"},
        )
        ids = {entry["resource"]["id"] for entry in resp.data["entry"]}
        self.assertEqual(ids, {str(self.hist_surgical.pk)})

    def test_condition_search_by_category_problem_list_item(self):
        resp = self.client.get(
            COND_SEARCH,
            {"patient": str(self.patient.pk), "category": "problem-list-item"},
        )
        ids = {entry["resource"]["id"] for entry in resp.data["entry"]}
        self.assertEqual(ids, {str(self.hist_active.pk)})

    def test_condition_search_unknown_category_returns_empty(self):
        resp = self.client.get(COND_SEARCH, {"category": "weird-cat"})
        self.assertEqual(resp.data["total"], 0)

    def test_condition_read_blocked_when_module_disabled(self):
        FeatureFlag.objects.filter(tenant=self.__class__.tenant, module_key="fhir").update(
            is_enabled=False
        )
        resp = self.client.get(_cond_read(self.hist_active.pk))
        self.assertEqual(resp.status_code, 403)
