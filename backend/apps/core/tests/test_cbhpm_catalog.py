"""
M1-S1 (S1-T1) — CBHPM procedure catalog (core.CBHPMItem) + import_cbhpm.

Covers the governed model (defaults, normalized_display sync) and the
CatalogImporter-backed management command: idempotent build, dry-run safety,
per-line error isolation (malformed CSV), provenance logging, and that the
numeric fields persist as exact Decimal without truncation. All local — no
network.
"""

from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.cbhpm_models import CBHPMItem
from apps.core.management.commands.import_cbhpm import Command as ImportCBHPM
from apps.core.terminology_base import TerminologyImportLog
from apps.test_utils import TenantTestCase

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SAMPLE = FIXTURES / "cbhpm_sample.csv"
MALFORMED = FIXTURES / "cbhpm_malformed.csv"


def run_import(**options):
    out = StringIO()
    call_command(ImportCBHPM(), stdout=out, stderr=out, **options)
    return out.getvalue()


class TestCBHPMItemModel(TenantTestCase):
    def test_defaults_and_normalized_display_sync(self):
        item = CBHPMItem.objects.create(code="10101012", display="Consulta em Consultório")
        item.refresh_from_db()
        self.assertEqual(item.system, "cbhpm")  # redeclared default
        self.assertTrue(item.active)
        self.assertEqual(item.porte, Decimal("0"))
        self.assertEqual(item.valor_ch, Decimal("0"))
        self.assertEqual(item.numero_auxiliares, 0)
        self.assertEqual(item.normalized_display, "consulta em consultorio")


class TestImportCBHPMValid(TenantTestCase):
    def test_creates_rows_with_all_fields(self):
        run_import(source=str(SAMPLE))
        self.assertEqual(CBHPMItem.objects.count(), 3)
        consulta = CBHPMItem.objects.get(code="10101012")
        self.assertEqual(consulta.display, "FAKE-Consulta em consultório")
        self.assertEqual(consulta.system, "cbhpm")
        self.assertEqual(consulta.vigencia, "2024")

    def test_decimal_fields_persist_without_truncation(self):
        run_import(source=str(SAMPLE))
        apendice = CBHPMItem.objects.get(code="30715016")
        # Stored + read back exactly — no float drift, comma decimal parsed.
        self.assertEqual(apendice.porte, Decimal("7.2500"))
        self.assertEqual(apendice.valor_ch, Decimal("12.500000"))
        self.assertEqual(apendice.porte_anestesico, "4")
        self.assertEqual(apendice.numero_auxiliares, 1)
        radio = CBHPMItem.objects.get(code="40901165")
        self.assertEqual(radio.numero_filme, Decimal("1.2500"))

    def test_normalized_display_populated(self):
        run_import(source=str(SAMPLE))
        radio = CBHPMItem.objects.get(code="40901165")
        self.assertEqual(radio.normalized_display, "fake-radiografia de torax")

    def test_idempotent_rerun_updates_not_duplicates(self):
        run_import(source=str(SAMPLE))
        run_import(source=str(SAMPLE))
        self.assertEqual(CBHPMItem.objects.count(), 3)

    def test_provenance_log_written(self):
        run_import(source=str(SAMPLE), cbhpm_version="2024")
        log = TerminologyImportLog.objects.filter(system="cbhpm").latest("ran_at")
        self.assertEqual(log.provenance, "CBHPM/AMB")
        self.assertEqual(log.version, "2024")
        self.assertEqual(log.row_count_added, 3)
        self.assertEqual(log.status, TerminologyImportLog.Status.SUCCESS)
        self.assertFalse(log.dry_run)


class TestImportCBHPMDryRun(TenantTestCase):
    def test_dry_run_writes_nothing(self):
        run_import(source=str(SAMPLE), dry_run=True)
        self.assertEqual(CBHPMItem.objects.count(), 0)
        log = TerminologyImportLog.objects.filter(system="cbhpm").latest("ran_at")
        self.assertTrue(log.dry_run)
        self.assertEqual(log.row_count_added, 3)  # counts what WOULD happen


class TestImportCBHPMPerLineIsolation(TenantTestCase):
    def test_bad_rows_isolated_good_row_survives(self):
        run_import(source=str(MALFORMED))
        # Only the single good row commits; the 3 bad rows are skipped.
        self.assertEqual(CBHPMItem.objects.count(), 1)
        self.assertTrue(CBHPMItem.objects.filter(code="10101012").exists())
        log = TerminologyImportLog.objects.filter(system="cbhpm").latest("ran_at")
        self.assertEqual(log.row_count_added, 1)
        self.assertEqual(log.row_count_errors, 3)
        self.assertEqual(log.status, TerminologyImportLog.Status.PARTIAL)

    def test_missing_file_raises(self):
        with self.assertRaises(CommandError):
            run_import(source=str(FIXTURES / "does_not_exist.csv"))
