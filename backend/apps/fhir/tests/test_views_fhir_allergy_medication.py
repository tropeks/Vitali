"""
Integration tests for the FHIR R4 AllergyIntolerance and MedicationRequest
REST surfaces.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from rest_framework.test import APIClient

from apps.core.models import FeatureFlag, Role, User
from apps.emr.models import (
    Allergy,
    Encounter,
    Patient,
    Prescription,
    PrescriptionItem,
    Professional,
)
from apps.pharmacy.models import Drug
from apps.test_utils import TenantTestCase

ALLERGY_SEARCH_URL = "/api/v1/fhir/AllergyIntolerance/"
MEDREQ_SEARCH_URL = "/api/v1/fhir/MedicationRequest/"
METADATA_URL = "/api/v1/fhir/metadata"


def _allergy_read_url(pk):
    return f"/api/v1/fhir/AllergyIntolerance/{pk}/"


def _medreq_read_url(pk):
    return f"/api/v1/fhir/MedicationRequest/{pk}/"


def _make_user(*, role_name: str, perms: list[str], full_name: str = "Tester") -> User:
    role, _ = Role.objects.get_or_create(name=role_name, defaults={"permissions": perms})
    role.permissions = perms
    role.save()
    return User.objects.create_user(
        email=f"{role_name}@test.com", password="pw", role=role, full_name=full_name
    )


class FHIRAllergyAndMedicationViewsTest(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="fhir",
            defaults={"is_enabled": True},
        )
        self.user = _make_user(
            role_name="fhir_alg_med",
            perms=["fhir.read"],
            full_name="FHIR Reader",
        )
        self.client.force_authenticate(user=self.user)

        # Patient + Professional + Encounter + Prescription
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
        self.md_user = _make_user(role_name="md_alg", perms=["fhir.read"], full_name="Dra Bia")
        self.professional = Professional.objects.create(
            user=self.md_user,
            council_type="CRM",
            council_number="555111",
            council_state="SP",
        )
        self.encounter = Encounter.objects.create(
            patient=self.patient,
            professional=self.professional,
            status="signed",
            encounter_date=datetime(2026, 5, 19, 9, 0, tzinfo=UTC),
            signed_at=datetime(2026, 5, 19, 9, 30, tzinfo=UTC),
        )

        # Allergies
        self.allergy_active = Allergy.objects.create(
            patient=self.patient,
            substance="Penicilina",
            reaction="Urticária",
            severity="severe",
            status="active",
            confirmed_by=self.md_user,
        )
        self.allergy_resolved = Allergy.objects.create(
            patient=self.patient,
            substance="Sulfa",
            severity="mild",
            status="resolved",
        )
        self.other_allergy = Allergy.objects.create(
            patient=self.other_patient,
            substance="Iodo",
            severity="moderate",
            status="active",
        )

        # Prescription with two items
        self.drug = Drug.objects.create(generic_name="Amoxicilina", name="Amoxicilina")
        self.drug2 = Drug.objects.create(generic_name="Dipirona", name="Dipirona")
        self.prescription_signed = Prescription.objects.create(
            encounter=self.encounter,
            patient=self.patient,
            prescriber=self.professional,
            status="signed",
            signed_at=datetime(2026, 5, 19, 10, 0, tzinfo=UTC),
            signed_by=self.md_user,
        )
        self.item_signed_1 = PrescriptionItem.objects.create(
            prescription=self.prescription_signed,
            drug=self.drug,
            quantity=Decimal("21"),
            unit_of_measure="cápsula",
            dosage_instructions="8/8h por 7 dias.",
        )
        self.item_signed_2 = PrescriptionItem.objects.create(
            prescription=self.prescription_signed,
            drug=self.drug2,
            quantity=Decimal("10"),
            unit_of_measure="comprimido",
            dosage_instructions="SOS dor.",
        )
        self.prescription_dispensed = Prescription.objects.create(
            encounter=self.encounter,
            patient=self.other_patient,
            prescriber=self.professional,
            status="dispensed",
        )
        self.item_dispensed = PrescriptionItem.objects.create(
            prescription=self.prescription_dispensed,
            drug=self.drug,
            quantity=Decimal("14"),
            unit_of_measure="cápsula",
        )

    # ─── Capability statement ────────────────────────────────────────────────

    def test_capability_statement_advertises_both_resources(self):
        self.client.logout()
        resp = self.client.get(METADATA_URL)
        types = {r["type"] for r in resp.data["rest"][0]["resource"]}
        self.assertIn("AllergyIntolerance", types)
        self.assertIn("MedicationRequest", types)

    # ─── AllergyIntolerance ──────────────────────────────────────────────────

    def test_allergy_read(self):
        resp = self.client.get(_allergy_read_url(self.allergy_active.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["resourceType"], "AllergyIntolerance")
        self.assertEqual(resp.data["criticality"], "high")
        self.assertEqual(resp.data["code"]["text"], "Penicilina")
        self.assertEqual(resp.data["patient"]["reference"], f"Patient/{self.patient.pk}")

    def test_allergy_search_by_patient(self):
        resp = self.client.get(ALLERGY_SEARCH_URL, {"patient": f"Patient/{self.patient.pk}"})
        ids = {entry["resource"]["id"] for entry in resp.data["entry"]}
        self.assertIn(str(self.allergy_active.pk), ids)
        self.assertIn(str(self.allergy_resolved.pk), ids)
        self.assertNotIn(str(self.other_allergy.pk), ids)

    def test_allergy_search_by_clinical_status_active(self):
        resp = self.client.get(
            ALLERGY_SEARCH_URL,
            {"patient": str(self.patient.pk), "clinical-status": "active"},
        )
        ids = {entry["resource"]["id"] for entry in resp.data["entry"]}
        self.assertEqual(ids, {str(self.allergy_active.pk)})

    def test_allergy_read_blocked_when_module_disabled(self):
        FeatureFlag.objects.filter(tenant=self.__class__.tenant, module_key="fhir").update(
            is_enabled=False
        )
        resp = self.client.get(_allergy_read_url(self.allergy_active.pk))
        self.assertEqual(resp.status_code, 403)

    # ─── MedicationRequest ───────────────────────────────────────────────────

    def test_medication_request_read_at_item_level(self):
        resp = self.client.get(_medreq_read_url(self.item_signed_1.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["resourceType"], "MedicationRequest")
        self.assertEqual(resp.data["status"], "active")
        self.assertEqual(resp.data["subject"]["reference"], f"Patient/{self.patient.pk}")
        self.assertEqual(
            resp.data["requester"]["reference"], f"Practitioner/{self.professional.pk}"
        )

    def test_medication_request_search_by_patient(self):
        resp = self.client.get(MEDREQ_SEARCH_URL, {"patient": f"Patient/{self.patient.pk}"})
        ids = {entry["resource"]["id"] for entry in resp.data["entry"]}
        self.assertIn(str(self.item_signed_1.pk), ids)
        self.assertIn(str(self.item_signed_2.pk), ids)
        self.assertNotIn(str(self.item_dispensed.pk), ids)

    def test_medication_request_search_by_status_active(self):
        resp = self.client.get(MEDREQ_SEARCH_URL, {"status": "active"})
        ids = {entry["resource"]["id"] for entry in resp.data["entry"]}
        self.assertIn(str(self.item_signed_1.pk), ids)
        self.assertNotIn(str(self.item_dispensed.pk), ids)

    def test_medication_request_search_by_status_completed(self):
        resp = self.client.get(MEDREQ_SEARCH_URL, {"status": "completed"})
        ids = {entry["resource"]["id"] for entry in resp.data["entry"]}
        self.assertIn(str(self.item_dispensed.pk), ids)
        self.assertNotIn(str(self.item_signed_1.pk), ids)

    def test_medication_request_unknown_status_returns_empty(self):
        resp = self.client.get(MEDREQ_SEARCH_URL, {"status": "weirdo"})
        self.assertEqual(resp.data["total"], 0)

    def test_medication_request_group_identifier_carries_prescription_id(self):
        resp = self.client.get(_medreq_read_url(self.item_signed_1.pk))
        self.assertEqual(resp.data["groupIdentifier"]["value"], str(self.prescription_signed.pk))
