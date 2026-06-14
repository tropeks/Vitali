"""Tests for the import_drug_interactions management command (S29-03).

ILLUSTRATIVE TEST DATA — NOT CLINICAL TRUTH.
All ingredient names and interaction pairs in the fixtures used by these tests
are FABRICATED to exercise the importer logic. They are NOT a clinical
reference and MUST NOT be copied into production.
"""

import os

from django.core.management import CommandError, call_command

from apps.pharmacy.models import DrugInteraction
from apps.test_utils import TenantTestCase

# Absolute paths to fixtures shipped alongside this test module.
_FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
_SAMPLE_CSV = os.path.join(_FIXTURES_DIR, "drug_interactions_sample.csv")
_MALFORMED_CSV = os.path.join(_FIXTURES_DIR, "drug_interactions_malformed.csv")


class TestImportDrugInteractionsCreatesRows(TenantTestCase):
    """Happy path: a valid CSV creates DrugInteraction rows."""

    def test_import_creates_drug_interactions(self):
        self.assertEqual(DrugInteraction.objects.count(), 0)

        call_command("import_drug_interactions", file=_SAMPLE_CSV)

        # drug_interactions_sample.csv has 2 data rows → 2 DrugInteraction rows.
        self.assertEqual(DrugInteraction.objects.count(), 2)

    def test_import_is_idempotent(self):
        """Running the command twice must NOT create duplicate rows."""
        call_command("import_drug_interactions", file=_SAMPLE_CSV)
        after_first = DrugInteraction.objects.count()

        call_command("import_drug_interactions", file=_SAMPLE_CSV)
        after_second = DrugInteraction.objects.count()

        self.assertEqual(after_first, after_second)
        self.assertEqual(after_second, 2)

    def test_provenance_recorded(self):
        """After import with --source X --version Y, rows have source=='X', version=='Y'."""
        call_command(
            "import_drug_interactions",
            file=_SAMPLE_CSV,
            source="FAKE-SOURCE",
            data_version="v99",
        )

        for obj in DrugInteraction.objects.all():
            self.assertEqual(obj.source, "FAKE-SOURCE")
            self.assertEqual(obj.version, "v99")


class TestImportDrugInteractionsErrors(TenantTestCase):
    """Error path: malformed CSV must be rejected with no partial commit."""

    def test_malformed_csv_rejected_no_partial_import(self):
        """A CSV with one bad row must raise CommandError.

        CRITICAL: no DrugInteraction rows must be committed — the entire import
        must roll back atomically. The error report must name the offending line.
        """
        with self.assertRaises(CommandError) as ctx:
            call_command("import_drug_interactions", file=_MALFORMED_CSV)

        # No partial commit: DB must be empty.
        self.assertEqual(DrugInteraction.objects.count(), 0)

        # Error message must name the offending line.
        error_msg = str(ctx.exception)
        # drug_interactions_malformed.csv layout:
        #   line 1: # comment  (skipped)
        #   line 2: header
        #   line 3: FAKE-GoodRow (data row 0)
        #   line 4: bad row — ingredient_a is missing  (data row 1)
        # Physical line of the bad row is 4.
        self.assertIn("Line 4", error_msg)

    def test_dry_run_writes_nothing(self):
        """--dry-run must leave the database untouched even on a valid CSV."""
        self.assertEqual(DrugInteraction.objects.count(), 0)

        call_command("import_drug_interactions", file=_SAMPLE_CSV, dry_run=True)

        # Nothing committed.
        self.assertEqual(DrugInteraction.objects.count(), 0)
