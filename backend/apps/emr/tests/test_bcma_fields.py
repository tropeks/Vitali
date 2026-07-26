"""N3-T1 — BCMA / eMAR beira-leito: barcode scan fields on the eMAR event.

The eMAR (:class:`MedicationAdministration`) is append-only; BCMA adds the
beira-leito scan evidence (patient wristband + medication barcode), a verified
flag, and the override justification a nurse must give to proceed past a failed
"certo". The patient wristband key lives on :class:`Patient`.
"""

from apps.emr.models import MedicationAdministration, Patient
from apps.test_utils import TenantTestCase


class BCMAFieldsTests(TenantTestCase):
    def test_medication_administration_has_bcma_scan_fields(self):
        names = {f.name for f in MedicationAdministration._meta.get_fields()}
        for name in (
            "patient_barcode_scanned",
            "medication_barcode_scanned",
            "bcma_verified",
            "bcma_override_reason",
        ):
            self.assertIn(name, names, f"missing BCMA field {name!r}")

    def test_bcma_verified_is_boolean_defaulting_false(self):
        field = MedicationAdministration._meta.get_field("bcma_verified")
        self.assertEqual(field.get_internal_type(), "BooleanField")
        self.assertFalse(field.default)

    def test_override_reason_is_blank_by_default(self):
        field = MedicationAdministration._meta.get_field("bcma_override_reason")
        self.assertTrue(field.blank)

    def test_patient_carries_a_wristband_barcode(self):
        names = {f.name for f in Patient._meta.get_fields()}
        self.assertIn("wristband_barcode", names)
