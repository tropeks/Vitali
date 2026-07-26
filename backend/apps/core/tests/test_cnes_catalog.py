"""
M2-S1-T2 — CNES establishment catalog (core.CNESEstablishment) + import_cnes.

Covers the governed model (fields, ``system`` default, ``normalized_display``
sync, active status) and the CatalogImporter-backed management command:
idempotent build, dry-run safety, per-line error isolation (malformed CSV), and
provenance logging (CNES/DATASUS). All local — no network.
"""

from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.cbo_cnes_models import CNESEstablishment
from apps.core.management.commands.import_cnes import Command as ImportCnes
from apps.core.terminology_base import TerminologyImportLog
from apps.test_utils import TenantTestCase

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SAMPLE = FIXTURES / "cnes_sample.csv"
MALFORMED = FIXTURES / "cnes_malformed.csv"


def run_import(**options):
    out = StringIO()
    call_command(ImportCnes(), stdout=out, stderr=out, **options)
    return out.getvalue()


class TestCNESEstablishmentModel(TenantTestCase):
    def test_defaults_and_normalized_display_sync(self):
        e = CNESEstablishment.objects.create(
            code="1000001",
            display="Hospital São João",
            establishment_type="HOSPITAL GERAL",
            municipality_ibge="3550308",
        )
        e.refresh_from_db()
        self.assertEqual(e.system, "cnes")  # redeclared default
        self.assertTrue(e.active)
        self.assertEqual(e.establishment_type, "HOSPITAL GERAL")
        self.assertEqual(e.municipality_ibge, "3550308")
        self.assertEqual(e.normalized_display, "hospital sao joao")

    def test_str_contains_code(self):
        e = CNESEstablishment.objects.create(code="1000001", display="Hospital São João")
        self.assertIn("1000001", str(e))


class TestImportCnesValid(TenantTestCase):
    def test_creates_rows_with_all_fields(self):
        run_import(source=str(SAMPLE))
        self.assertEqual(CNESEstablishment.objects.count(), 3)
        h = CNESEstablishment.objects.get(code="1000001")
        self.assertEqual(h.display, "FAKE-Hospital São João")
        self.assertEqual(h.establishment_type, "HOSPITAL GERAL")
        self.assertEqual(h.municipality_ibge, "3550308")
        self.assertEqual(h.system, "cnes")
        self.assertTrue(h.active)

    def test_inactive_row_imported_as_inactive(self):
        run_import(source=str(SAMPLE))
        posto = CNESEstablishment.objects.get(code="1000003")
        self.assertFalse(posto.active)

    def test_normalized_display_populated(self):
        run_import(source=str(SAMPLE))
        h = CNESEstablishment.objects.get(code="1000001")
        self.assertEqual(h.normalized_display, "fake-hospital sao joao")

    def test_idempotent_rerun_updates_not_duplicates(self):
        run_import(source=str(SAMPLE))
        run_import(source=str(SAMPLE))
        self.assertEqual(CNESEstablishment.objects.count(), 3)

    def test_provenance_log_written(self):
        run_import(source=str(SAMPLE), cnes_version="2024")
        log = TerminologyImportLog.objects.filter(system="cnes").latest("ran_at")
        self.assertEqual(log.provenance, "CNES/DATASUS")
        self.assertEqual(log.version, "2024")
        self.assertEqual(log.row_count_added, 3)
        self.assertEqual(log.status, TerminologyImportLog.Status.SUCCESS)
        self.assertFalse(log.dry_run)


class TestImportCnesDryRun(TenantTestCase):
    def test_dry_run_writes_nothing(self):
        run_import(source=str(SAMPLE), dry_run=True)
        self.assertEqual(CNESEstablishment.objects.count(), 0)
        log = TerminologyImportLog.objects.filter(system="cnes").latest("ran_at")
        self.assertTrue(log.dry_run)
        self.assertEqual(log.row_count_added, 3)  # counts what WOULD happen


class TestImportCnesMalformed(TenantTestCase):
    def test_malformed_csv_aborts_with_line_numbers(self):
        with self.assertRaises(CommandError) as ctx:
            run_import(source=str(MALFORMED))
        msg = str(ctx.exception)
        self.assertIn("CNES is empty", msg)
        self.assertIn("NOME is empty", msg)
        self.assertEqual(CNESEstablishment.objects.count(), 0)

    def test_missing_file_raises(self):
        with self.assertRaises(CommandError):
            run_import(source=str(FIXTURES / "does_not_exist.csv"))
