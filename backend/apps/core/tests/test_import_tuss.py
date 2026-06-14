"""Tests for the import_tuss management command.

Covers:
  * valid import creates TUSSCode rows from fixture;
  * --dry-run rolls back all writes and does NOT persist a SUCCESS TUSSSyncLog;
  * malformed CSV (missing CODIGO) raises CommandError naming the offending line,
    and commits zero rows;
  * second import of the same file is idempotent (upsert by code).

Fixtures live in backend/apps/core/tests/fixtures/ and contain fabricated
FAKE- rows only — no real ANS clinical data.

Run: python manage.py test apps.core.tests.test_import_tuss
"""

import os

from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.models import TUSSCode, TUSSSyncLog
from apps.test_utils import TenantTestCase

# Absolute path to the fixtures directory alongside this file.
_FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

_SAMPLE_CSV = os.path.join(_FIXTURES_DIR, "tuss_sample.csv")
_MALFORMED_CSV = os.path.join(_FIXTURES_DIR, "tuss_malformed.csv")

# tuss_sample.csv has 3 fabricated FAKE- data rows (CODIGO: 10101010, 20202020, 30303030).
_SAMPLE_ROW_COUNT = 3


class ImportTussValidImportTests(TenantTestCase):
    """Happy-path: valid CSV creates the expected TUSSCode rows."""

    def test_valid_import_creates_rows(self):
        """Importing tuss_sample.csv creates exactly 3 TUSSCode rows."""
        count_before = TUSSCode.objects.count()
        call_command("import_tuss", file=_SAMPLE_CSV, tuss_version="2024-01")
        self.assertEqual(TUSSCode.objects.count(), count_before + _SAMPLE_ROW_COUNT)

    def test_imported_codes_have_correct_version(self):
        """All imported rows carry the supplied tuss_version label."""
        call_command("import_tuss", file=_SAMPLE_CSV, tuss_version="2024-01")
        self.assertTrue(
            TUSSCode.objects.filter(version="2024-01").count() >= _SAMPLE_ROW_COUNT
        )

    def test_idempotent_upsert(self):
        """Importing the same file twice does not grow the TUSSCode count."""
        call_command("import_tuss", file=_SAMPLE_CSV, tuss_version="2024-01")
        count_after_first = TUSSCode.objects.count()
        call_command("import_tuss", file=_SAMPLE_CSV, tuss_version="2024-01")
        self.assertEqual(TUSSCode.objects.count(), count_after_first)


class ImportTussDryRunTests(TenantTestCase):
    """--dry-run rolls back all DB writes and does not persist a SUCCESS log."""

    def test_dry_run_writes_nothing(self):
        """dry_run=True leaves TUSSCode count unchanged and writes no SUCCESS log."""
        count_before = TUSSCode.objects.count()
        log_count_before = TUSSSyncLog.objects.filter(
            status=TUSSSyncLog.Status.SUCCESS
        ).count()

        call_command("import_tuss", file=_SAMPLE_CSV, tuss_version="2024-01", dry_run=True)

        # No new TUSSCode rows.
        self.assertEqual(TUSSCode.objects.count(), count_before)
        # No new SUCCESS log entry.
        self.assertEqual(
            TUSSSyncLog.objects.filter(status=TUSSSyncLog.Status.SUCCESS).count(),
            log_count_before,
        )


class ImportTussMalformedTests(TenantTestCase):
    """Per-line error collection: malformed rows raise CommandError, commit nothing."""

    def test_malformed_csv_reports_lines_no_partial(self):
        """Empty CODIGO raises CommandError naming the offending line; 0 rows committed."""
        count_before = TUSSCode.objects.count()

        with self.assertRaises(CommandError) as ctx:
            call_command("import_tuss", file=_MALFORMED_CSV, tuss_version="2024-01")

        # The error message must mention the TRUE physical line number.
        # tuss_malformed.csv layout:
        #   line 1: # comment (skipped)
        #   line 2: header
        #   line 3: 10101010;FAKE-Consulta basica;... (data row 0, good)
        #   line 4: ;FAKE-Row with missing code;... (data row 1, bad — empty CODIGO)
        # Physical line of the bad row is 4.
        error_msg = str(ctx.exception)
        self.assertIn("Line 4", error_msg)

        # No rows committed — the transaction was rolled back.
        self.assertEqual(TUSSCode.objects.count(), count_before)
