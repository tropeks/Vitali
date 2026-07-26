"""N3-T3 — BCMA check endpoint: POST /api/v1/emar/check/.

The beira-leito checagem action runs the "5 certos" verifier and, on success,
records the append-only administration. A failing right blocks the record and
returns the structured mismatch; the nurse may proceed only by supplying an
``override_reason`` (recorded with ``bcma_verified=False``). Gated by
``emar.administer``; the existing signed-order + pharmacist-validation +
witness invariants are preserved (the record path is unchanged).
"""

from decimal import Decimal

from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import Role, User
from apps.emr.models import (
    Encounter,
    MedicationAdministration,
    Patient,
    Prescription,
    PrescriptionItem,
    Professional,
)
from apps.pharmacy.models import Drug, PharmacistValidation
from apps.test_utils import TenantTestCase


class BCMACheckEndpointTests(TenantTestCase):
    URL = "/api/v1/emar/check/"

    def setUp(self):
        super().setUp()
        self.role = Role.objects.create(
            name="bcma_nurse",
            permissions=["emar.read", "emar.administer"],
        )
        self.user = User.objects.create_user(
            email="bcma-nurse@test.local", password="pw", role=self.role
        )
        self.patient = Patient.objects.create(
            full_name="Paciente BCMA",
            cpf="11122233344",
            birth_date="1970-01-01",
            gender="F",
            wristband_barcode="WRB-BEIRA-1",
        )
        self.professional = Professional.objects.create(
            user=self.user, council_type="COREN", council_number="7", council_state="SP"
        )
        self.encounter = Encounter.objects.create(
            patient=self.patient, professional=self.professional
        )
        self.drug = Drug.objects.create(
            name="Dipirona 500mg", generic_name="dipirona", barcode="MED-BEIRA-9"
        )
        self.prescription = Prescription.objects.create(
            encounter=self.encounter, patient=self.patient, prescriber=self.professional
        )
        self.prescription.sign(self.user)  # sets signed_at (aprazamento anchor)
        PharmacistValidation.objects.create(
            prescription=self.prescription,
            status="approved",
            pharmacist=self.user,
            validated_at=timezone.now(),
        )
        self.item = PrescriptionItem.objects.create(
            prescription=self.prescription,
            drug=self.drug,
            quantity=Decimal("1"),
            dose_amount=Decimal("500"),
            dose_unit="mg",
            route="IV",
            frequency_per_day=4,
        )
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        self.client.force_authenticate(self.user)

    def test_happy_path_records_administration_bcma_verified(self):
        response = self.client.post(
            self.URL,
            {
                "prescription_item": str(self.item.id),
                "patient_barcode": "WRB-BEIRA-1",
                "medication_barcode": "MED-BEIRA-9",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(MedicationAdministration.objects.count(), 1)
        event = MedicationAdministration.objects.get()
        self.assertTrue(event.bcma_verified)
        self.assertEqual(event.status, "given")
        self.assertEqual(event.patient_barcode_scanned, "WRB-BEIRA-1")
        self.assertEqual(event.medication_barcode_scanned, "MED-BEIRA-9")

    def test_wrong_medication_is_blocked_with_mismatch(self):
        response = self.client.post(
            self.URL,
            {
                "prescription_item": str(self.item.id),
                "patient_barcode": "WRB-BEIRA-1",
                "medication_barcode": "MED-WRONG-0",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 422, response.data)
        self.assertIn("medication", response.data["bcma"]["mismatches"])
        self.assertFalse(response.data["bcma"]["ok"])
        # blocked → nothing recorded
        self.assertEqual(MedicationAdministration.objects.count(), 0)

    def test_override_with_reason_records_unverified(self):
        response = self.client.post(
            self.URL,
            {
                "prescription_item": str(self.item.id),
                "patient_barcode": "WRB-BEIRA-1",
                "medication_barcode": "MED-WRONG-0",
                "override_reason": "Código do medicamento ilegível; conferido manualmente.",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        event = MedicationAdministration.objects.get()
        self.assertFalse(event.bcma_verified)
        self.assertTrue(event.bcma_override_reason)
        self.assertEqual(event.status, "given")

    def test_requires_emar_administer_permission(self):
        role = Role.objects.create(name="read_only_emar", permissions=["emar.read"])
        other = User.objects.create_user(email="ro@test.local", password="pw", role=role)
        client = APIClient()
        client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        client.force_authenticate(other)
        response = client.post(
            self.URL,
            {
                "prescription_item": str(self.item.id),
                "patient_barcode": "WRB-BEIRA-1",
                "medication_barcode": "MED-BEIRA-9",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 403)
