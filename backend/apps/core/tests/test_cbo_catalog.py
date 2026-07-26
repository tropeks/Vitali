"""
M2-S1-T1 — CBO occupation catalog (core.CBOCode) + import_cbo importer.

Covers the governed model (fields, ``system`` default, ``normalized_display``
sync) and the CatalogImporter-backed management command: idempotent build,
dry-run safety, per-line error isolation (malformed CSV), and provenance
logging (MTE/DATASUS). All local — no network.
"""

from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.cbo_cnes_models import CBOCode
from apps.core.management.commands.import_cbo import Command as ImportCbo
from apps.core.terminology_base import TerminologyImportLog
from apps.test_utils import TenantTestCase

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SAMPLE = FIXTURES / "cbo_sample.csv"
MALFORMED = FIXTURES / "cbo_malformed.csv"


def run_import(**options):
    out = StringIO()
    call_command(ImportCbo(), stdout=out, stderr=out, **options)
    return out.getvalue()


class TestCBOCodeModel(TenantTestCase):
    def test_defaults_and_normalized_display_sync(self):
        c = CBOCode.objects.create(code="225125", display="Médico Clínico", family="2251")
        c.refresh_from_db()
        self.assertEqual(c.system, "cbo")  # redeclared default
        self.assertTrue(c.active)
        self.assertEqual(c.family, "2251")
        self.assertEqual(c.normalized_display, "medico clinico")

    def test_str_contains_code(self):
        c = CBOCode.objects.create(code="225125", display="Médico Clínico")
        self.assertIn("225125", str(c))


class TestImportCboValid(TenantTestCase):
    def test_creates_rows_with_all_fields(self):
        run_import(source=str(SAMPLE))
        self.assertEqual(CBOCode.objects.count(), 3)
        m = CBOCode.objects.get(code="225125")
        self.assertEqual(m.display, "FAKE-Médico clínico")
        self.assertEqual(m.family, "2251")
        self.assertEqual(m.system, "cbo")
        self.assertTrue(m.active)

    def test_normalized_display_populated(self):
        run_import(source=str(SAMPLE))
        m = CBOCode.objects.get(code="225125")
        self.assertEqual(m.normalized_display, "fake-medico clinico")

    def test_idempotent_rerun_updates_not_duplicates(self):
        run_import(source=str(SAMPLE))
        run_import(source=str(SAMPLE))
        self.assertEqual(CBOCode.objects.count(), 3)

    def test_provenance_log_written(self):
        run_import(source=str(SAMPLE), cbo_version="2024")
        log = TerminologyImportLog.objects.filter(system="cbo").latest("ran_at")
        self.assertEqual(log.provenance, "MTE/DATASUS")
        self.assertEqual(log.version, "2024")
        self.assertEqual(log.row_count_added, 3)
        self.assertEqual(log.status, TerminologyImportLog.Status.SUCCESS)
        self.assertFalse(log.dry_run)


class TestImportCboDryRun(TenantTestCase):
    def test_dry_run_writes_nothing(self):
        run_import(source=str(SAMPLE), dry_run=True)
        self.assertEqual(CBOCode.objects.count(), 0)
        log = TerminologyImportLog.objects.filter(system="cbo").latest("ran_at")
        self.assertTrue(log.dry_run)
        self.assertEqual(log.row_count_added, 3)  # counts what WOULD happen


class TestImportCboMalformed(TenantTestCase):
    def test_malformed_csv_aborts_with_line_numbers(self):
        with self.assertRaises(CommandError) as ctx:
            run_import(source=str(MALFORMED))
        msg = str(ctx.exception)
        self.assertIn("CODIGO is empty", msg)
        self.assertIn("TITULO is empty", msg)
        self.assertEqual(CBOCode.objects.count(), 0)

    def test_missing_file_raises(self):
        with self.assertRaises(CommandError):
            run_import(source=str(FIXTURES / "does_not_exist.csv"))
