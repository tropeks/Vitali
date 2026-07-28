"""N3-T2 — BCMA "5 certos" verifier (pure/deterministic).

``verify_five_rights`` checks the five rights of medication administration for a
bedside barcode scan against the signed order:

* paciente certo — scanned wristband matches the patient (wristband barcode / MRN)
* medicamento certo — scanned medication barcode matches the ordered drug
* dose certa — the order carries a structured, verifiable dose
* via certa — the order carries a structured route
* hora certa — ``at_time`` falls inside the item's aprazamento window

It is a pure function: no DB writes, no clock reads — same inputs, same output.
"""

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.core.models import Role, User
from apps.emr.models import Encounter, Patient, Prescription, PrescriptionItem, Professional
from apps.emr.services.bcma import verify_five_rights
from apps.pharmacy.models import Drug
from apps.test_utils import TenantTestCase


class VerifyFiveRightsTests(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.role = Role.objects.create(name="bcma_verify", permissions=["emar.administer"])
        self.user = User.objects.create_user(
            email="bcma-verify@test.local", password="pw", role=self.role
        )
        self.patient = Patient.objects.create(
            full_name="Paciente BCMA",
            cpf="98765432100",
            birth_date="1975-05-05",
            gender="M",
            wristband_barcode="WRB-0001",
        )
        self.professional = Professional.objects.create(
            user=self.user, council_type="COREN", council_number="9", council_state="SP"
        )
        self.encounter = Encounter.objects.create(
            patient=self.patient, professional=self.professional
        )
        self.drug = Drug.objects.create(
            name="Dipirona 500mg", generic_name="dipirona", barcode="MED-7891234"
        )
        self.prescription = Prescription.objects.create(
            encounter=self.encounter, patient=self.patient, prescriber=self.professional
        )
        # A fully-structured, aprazado order: anchored at signed_at, dosed, routed.
        self.anchor = timezone.now()
        self.prescription.signed_at = self.anchor
        self.prescription.save(update_fields=["signed_at"])
        self.item = PrescriptionItem.objects.create(
            prescription=self.prescription,
            drug=self.drug,
            quantity=Decimal("1"),
            dose_amount=Decimal("500"),
            dose_unit="mg",
            route="IV",
            frequency_per_day=4,  # 6/6h → slot at the anchor
        )

    def _verify(self, **overrides):
        kwargs = {
            "prescription_item": self.item,
            "patient": self.patient,
            "patient_barcode": "WRB-0001",
            "medication_barcode": "MED-7891234",
            "at_time": self.anchor,
        }
        kwargs.update(overrides)
        return verify_five_rights(**kwargs)

    def test_all_rights_pass(self):
        result = self._verify()
        self.assertTrue(result.patient)
        self.assertTrue(result.medication)
        self.assertTrue(result.dose)
        self.assertTrue(result.route)
        self.assertTrue(result.time)
        self.assertTrue(result.ok)
        self.assertEqual(result.mismatches, [])

    def test_wrong_patient_wristband_fails_patient_right(self):
        result = self._verify(patient_barcode="WRB-9999")
        self.assertFalse(result.patient)
        self.assertFalse(result.ok)
        self.assertIn("patient", result.mismatches)

    def test_mrn_is_accepted_as_wristband_fallback(self):
        result = self._verify(patient_barcode=self.patient.medical_record_number)
        self.assertTrue(result.patient)

    def test_wrong_medication_barcode_fails_medication_right(self):
        result = self._verify(medication_barcode="MED-0000000")
        self.assertFalse(result.medication)
        self.assertFalse(result.ok)
        self.assertIn("medication", result.mismatches)

    def test_missing_structured_dose_fails_dose_right(self):
        self.item.dose_amount = None
        self.item.save(update_fields=["dose_amount"])
        result = self._verify()
        self.assertFalse(result.dose)
        self.assertIn("dose", result.mismatches)

    def test_missing_route_fails_route_right(self):
        self.item.route = ""
        self.item.save(update_fields=["route"])
        result = self._verify()
        self.assertFalse(result.route)
        self.assertIn("route", result.mismatches)

    def test_out_of_window_time_fails_time_right(self):
        result = self._verify(at_time=self.anchor + timedelta(hours=3))
        self.assertFalse(result.time)
        self.assertIn("time", result.mismatches)

    def test_within_window_time_passes(self):
        result = self._verify(at_time=self.anchor + timedelta(minutes=20))
        self.assertTrue(result.time)

    def test_result_as_dict_shape(self):
        payload = self._verify().as_dict()
        self.assertEqual(
            set(payload),
            {"patient", "medication", "dose", "route", "time", "ok", "mismatches"},
        )
        self.assertTrue(payload["ok"])

    def test_is_pure_no_side_effects(self):
        before = timezone.now()
        r1 = self._verify()
        r2 = self._verify()
        self.assertEqual(r1.as_dict(), r2.as_dict())
        # no rows written by the verifier
        self.assertFalse(self.item.administrations.filter(created_at__gte=before).exists())
