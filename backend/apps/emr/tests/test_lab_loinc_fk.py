"""
M2-S3-T2 — emr.LabTest.loinc governed cross-schema FK to core.LoincCode.

Covers: FK set/validated, legacy loinc_code preserved alongside the FK, the
cross-schema deletion-protection signal (mirrors AnvisaProduct/CID10), and the
data-migration reconcile helper (preserves the legacy code while linking the FK).
"""

from django.db import transaction
from django.db.models.deletion import ProtectedError

from apps.core.loinc_models import LoincCode
from apps.emr.loinc_backfill import reconcile_lab_test_loinc
from apps.emr.models import LabTest
from apps.test_utils import TenantTestCase


class TestLabTestLoincFK(TenantTestCase):
    def test_attach_loinc_via_fk(self):
        loinc = LoincCode.objects.create(code="718-7", display="Hemoglobin in Blood")
        test = LabTest.objects.create(code="HB", name="Hemoglobina", loinc=loinc)
        test.refresh_from_db()
        self.assertEqual(test.loinc_id, loinc.pk)
        self.assertEqual(test.loinc_display_code, "718-7")

    def test_legacy_loinc_code_preserved_alongside_fk(self):
        loinc = LoincCode.objects.create(code="718-7", display="Hemoglobin")
        test = LabTest.objects.create(
            code="HB", name="Hemoglobina", loinc_code="718-7", loinc=loinc
        )
        test.refresh_from_db()
        self.assertEqual(test.loinc_code, "718-7")  # legacy kept
        self.assertEqual(test.loinc_id, loinc.pk)

    def test_fk_nullable_by_default_falls_back_to_legacy(self):
        test = LabTest.objects.create(code="HB", name="x", loinc_code="99999-9")
        self.assertIsNone(test.loinc_id)
        self.assertEqual(test.loinc_display_code, "99999-9")


class TestLoincCodeDeleteProtection(TenantTestCase):
    def test_delete_blocked_when_referenced_by_lab_test(self):
        loinc = LoincCode.objects.create(code="718-7", display="Hemoglobin")
        LabTest.objects.create(code="HB", name="Hemoglobina", loinc=loinc)
        with self.assertRaises(ProtectedError) as ctx, transaction.atomic():
            loinc.delete()
        self.assertIn("LoincCode", str(ctx.exception))
        self.assertIn("LabTest", str(ctx.exception))
        self.assertTrue(LoincCode.objects.filter(pk=loinc.pk).exists())

    def test_delete_allowed_when_unreferenced(self):
        loinc = LoincCode.objects.create(code="2160-0", display="Creatinine")
        loinc.delete()
        self.assertFalse(LoincCode.objects.filter(pk=loinc.pk).exists())


class TestLoincReconcileBackfill(TenantTestCase):
    def test_reconcile_links_matching_code_and_preserves_legacy(self):
        loinc = LoincCode.objects.create(code="718-7", display="Hemoglobin")
        test = LabTest.objects.create(code="HB", name="Hemoglobina", loinc_code="718-7")
        linked, unmatched = reconcile_lab_test_loinc(LabTest, LoincCode)
        self.assertEqual((linked, unmatched), (1, 0))
        test.refresh_from_db()
        self.assertEqual(test.loinc_id, loinc.pk)
        self.assertEqual(test.loinc_code, "718-7")  # legacy preserved, never lost

    def test_reconcile_leaves_unmatched_untouched(self):
        test = LabTest.objects.create(code="XX", name="Unknown", loinc_code="00000-0")
        linked, unmatched = reconcile_lab_test_loinc(LabTest, LoincCode)
        self.assertEqual((linked, unmatched), (0, 1))
        test.refresh_from_db()
        self.assertIsNone(test.loinc_id)
        self.assertEqual(test.loinc_code, "00000-0")
