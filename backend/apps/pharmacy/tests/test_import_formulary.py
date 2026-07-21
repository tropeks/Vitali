"""Tests for the import_formulary management command (S29-02).

ILLUSTRATIVE TEST DATA — NOT CLINICAL TRUTH.
All drug names, strengths, and dose values in the fixtures used by these tests
are FABRICATED to exercise the importer logic. They are NOT a clinical formulary
and MUST NOT be copied into production.
"""

import os
from decimal import Decimal

from django.core.management import CommandError, call_command

from apps.pharmacy.models import DoseRule, Drug, MedicationFormulary
from apps.test_utils import TenantTestCase

# Absolute paths to fixtures shipped alongside this test module.
_FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
_SAMPLE_CSV = os.path.join(_FIXTURES_DIR, "formulary_sample.csv")
_MALFORMED_CSV = os.path.join(_FIXTURES_DIR, "formulary_malformed.csv")
_BANDED_CSV = os.path.join(_FIXTURES_DIR, "formulary_banded.csv")


class TestImportFormularyCreatesRows(TenantTestCase):
    """Happy path: a valid CSV creates MedicationFormulary + DoseRule rows."""

    def test_import_creates_formulary_and_doserules(self):
        self.assertEqual(MedicationFormulary.objects.count(), 0)
        self.assertEqual(DoseRule.objects.count(), 0)

        call_command("import_formulary", file=_SAMPLE_CSV)

        # formulary_sample.csv has 3 data rows → 3 drugs, 3 formularies, 3 rules.
        self.assertEqual(Drug.objects.filter(name__startswith="FAKE-Import").count(), 3)
        self.assertEqual(MedicationFormulary.objects.count(), 3)
        self.assertEqual(DoseRule.objects.count(), 3)

    def test_import_is_idempotent(self):
        """Running the command twice must NOT create duplicate rows."""
        call_command("import_formulary", file=_SAMPLE_CSV)
        after_first = {
            "formularies": MedicationFormulary.objects.count(),
            "rules": DoseRule.objects.count(),
        }

        call_command("import_formulary", file=_SAMPLE_CSV)
        after_second = {
            "formularies": MedicationFormulary.objects.count(),
            "rules": DoseRule.objects.count(),
        }

        self.assertEqual(after_first, after_second)
        self.assertEqual(after_second["formularies"], 3)
        self.assertEqual(after_second["rules"], 3)

    def test_imported_doserule_defaults_not_validated(self):
        """Every DoseRule created by the importer must have validated=False.

        The importer NEVER self-validates — human pharmacist sign-off is required
        via the UI. A rule that is active=True but validated=False is inert in the
        DoseChecker (the gate is active+validated).
        """
        call_command("import_formulary", file=_SAMPLE_CSV)

        rules = DoseRule.objects.all()
        self.assertGreater(rules.count(), 0)
        for rule in rules:
            self.assertFalse(
                rule.validated,
                f"DoseRule {rule.pk} was validated=True after import; importer must not self-validate.",
            )
            self.assertIsNone(rule.validated_by_id)
            self.assertIsNone(rule.validated_at)


class TestImportFormularyErrors(TenantTestCase):
    """Error path: malformed CSV must be rejected with no partial commit."""

    def test_malformed_csv_rejected_no_partial_import(self):
        """A CSV with one bad row must raise CommandError.

        CRITICAL: no MedicationFormulary or DoseRule rows must be committed —
        the entire import must roll back atomically. The error report must
        name the offending line number.
        """
        with self.assertRaises(CommandError) as ctx:
            call_command("import_formulary", file=_MALFORMED_CSV)

        # No partial commit: DB must be empty.
        self.assertEqual(MedicationFormulary.objects.count(), 0)
        self.assertEqual(DoseRule.objects.count(), 0)

        # Error message must name the PHYSICAL line number.
        # formulary_malformed.csv layout:
        #   line 1: # comment (skipped)
        #   line 2: header
        #   line 3: FAKE-GoodRow (data row 0)
        #   line 4: FAKE-BadRow (data row 1 — the bad row)
        # The physical line of the bad row is 4 (not 3 — the comment shifts it).
        error_msg = str(ctx.exception)
        self.assertIn("Line 4", error_msg)

    def test_dry_run_writes_nothing(self):
        """--dry-run must leave the database untouched even on a valid CSV."""
        self.assertEqual(MedicationFormulary.objects.count(), 0)

        call_command("import_formulary", file=_SAMPLE_CSV, dry_run=True)

        # Nothing committed.
        self.assertEqual(MedicationFormulary.objects.count(), 0)
        self.assertEqual(DoseRule.objects.count(), 0)
        self.assertEqual(Drug.objects.filter(name__startswith="FAKE-Import").count(), 0)


class TestImportFormularyAgeBandedRules(TenantTestCase):
    """FIX 1 — age-banded rules must not collapse on import (S29 audit fix).

    The formulary_banded.csv fixture has two rows for the SAME drug/basis/route/
    dose_role/freq but DIFFERENT age bands (0–365 days vs 366–6570 days). The
    prior natural key omitted band fields, causing one band to overwrite the other.
    The fixed key includes all four band fields so each band gets its own row.
    """

    def test_import_supports_age_banded_rules(self):
        """Two rows with the same drug/route/basis but different age bands must create
        two separate DoseRule rows — not collapse to one.
        """
        self.assertEqual(DoseRule.objects.count(), 0)

        call_command("import_formulary", file=_BANDED_CSV)

        # One drug, one formulary, but TWO dose rules (one per age band).
        self.assertEqual(Drug.objects.filter(name="FAKE-BandedDrug").count(), 1)
        self.assertEqual(MedicationFormulary.objects.count(), 1)
        self.assertEqual(DoseRule.objects.count(), 2, "Expected 2 banded rules, not 1 (collapsed).")

        rules = DoseRule.objects.order_by("age_min_days")
        neonate_rule = rules[0]
        child_rule = rules[1]

        self.assertEqual(neonate_rule.age_min_days, 0)
        self.assertEqual(neonate_rule.age_max_days, 365)
        self.assertEqual(neonate_rule.min_per_dose, Decimal("1.0000"))
        self.assertEqual(neonate_rule.max_per_dose, Decimal("5.0000"))

        self.assertEqual(child_rule.age_min_days, 366)
        self.assertEqual(child_rule.age_max_days, 6570)
        self.assertEqual(child_rule.min_per_dose, Decimal("5.0000"))
        self.assertEqual(child_rule.max_per_dose, Decimal("20.0000"))

    def test_reimport_with_existing_banded_rules_is_idempotent(self):
        """Re-importing the same banded CSV must not raise MultipleObjectsReturned
        and must leave counts stable (update in-place, not insert new rows).
        """
        # Pre-create the two banded rules via ORM (simulating a prior import).
        formulary_entry = MedicationFormulary.objects.create(
            drug=Drug.objects.create(name="FAKE-BandedDrug", generic_name="fake_banded"),
            strength_value=Decimal("10.000"),
            strength_unit="mg",
            route="IV",
            active=True,
        )
        DoseRule.objects.create(
            formulary=formulary_entry,
            basis=DoseRule.Basis.FIXED,
            dose_unit="mg",
            min_per_dose=Decimal("1.0000"),
            max_per_dose=Decimal("5.0000"),
            absolute_max_dose=Decimal("5.0000"),
            dose_role=DoseRule.DoseRole.MAINTENANCE,
            route="IV",
            age_min_days=0,
            age_max_days=365,
        )
        DoseRule.objects.create(
            formulary=formulary_entry,
            basis=DoseRule.Basis.FIXED,
            dose_unit="mg",
            min_per_dose=Decimal("5.0000"),
            max_per_dose=Decimal("20.0000"),
            absolute_max_dose=Decimal("20.0000"),
            dose_role=DoseRule.DoseRole.MAINTENANCE,
            route="IV",
            age_min_days=366,
            age_max_days=6570,
        )
        self.assertEqual(DoseRule.objects.count(), 2)

        # Re-import must NOT raise MultipleObjectsReturned and must NOT add rows.
        call_command("import_formulary", file=_BANDED_CSV)

        self.assertEqual(
            DoseRule.objects.count(), 2, "Re-import must be idempotent (no extra rows)."
        )
        self.assertEqual(MedicationFormulary.objects.count(), 1)


class TestImportFormularyPublicSchemaGuard(TenantTestCase):
    """FIX 2 — import_formulary must refuse to run in the public schema.

    TenantTestCase runs inside a real tenant schema. To test the public-schema
    rejection we temporarily switch the connection to the public schema using
    schema_context, then call the command and assert CommandError.
    """

    def test_command_raises_in_public_schema(self):
        """import_formulary must raise CommandError when run in the public schema."""
        from django_tenants.utils import get_public_schema_name, schema_context

        with schema_context(get_public_schema_name()):
            with self.assertRaises(CommandError) as ctx:
                call_command("import_formulary", file=_SAMPLE_CSV)

        self.assertIn("public schema", str(ctx.exception).lower())


class TestImportFormularyPhysicalLineNumbers(TenantTestCase):
    """FIX 3 — error messages must report PHYSICAL line numbers, not data-row numbers.

    formulary_malformed.csv has a leading comment line, so the bad row is at
    physical line 4 even though it is data row 2 (the second data row after the header).
    """

    def test_error_reports_physical_line_not_data_row(self):
        """The error message must reference physical line 4, not data-row line 3."""
        with self.assertRaises(CommandError) as ctx:
            call_command("import_formulary", file=_MALFORMED_CSV)

        error_msg = str(ctx.exception)
        # Physical layout of formulary_malformed.csv:
        #   line 1: # comment
        #   line 2: header
        #   line 3: FAKE-GoodRow  (data row 0)
        #   line 4: FAKE-BadRow   (data row 1, the malformed one)
        self.assertIn("Line 4", error_msg)
        # Must NOT report the incorrect data-row number.
        self.assertNotIn("Line 3", error_msg)
