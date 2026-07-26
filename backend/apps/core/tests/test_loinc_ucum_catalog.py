"""
M2-S3-T1 — LOINC/UCUM catalogs (core.LoincCode / core.UcumUnit) + importers.

Covers the models (governed fields, normalized_display sync, redeclared system
default, optional LOINC axes, UCUM case-sensitivity) and the CatalogImporter-
backed management commands: idempotent build, dry-run safety, per-line error
isolation (malformed CSV), and provenance logging. All local — no network.
"""

from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.loinc_models import LoincCode, UcumUnit
from apps.core.management.commands.import_loinc import Command as ImportLoinc
from apps.core.management.commands.import_ucum import Command as ImportUcum
from apps.core.terminology_base import TerminologyImportLog
from apps.test_utils import TenantTestCase

FIXTURES = Path(__file__).resolve().parent / "fixtures"
LOINC_SAMPLE = FIXTURES / "loinc_sample.csv"
LOINC_MALFORMED = FIXTURES / "loinc_malformed.csv"
UCUM_SAMPLE = FIXTURES / "ucum_sample.csv"
UCUM_MALFORMED = FIXTURES / "ucum_malformed.csv"


def run_loinc(**options):
    out = StringIO()
    call_command(ImportLoinc(), stdout=out, stderr=out, **options)
    return out.getvalue()


def run_ucum(**options):
    out = StringIO()
    call_command(ImportUcum(), stdout=out, stderr=out, **options)
    return out.getvalue()


# ─── LoincCode model ──────────────────────────────────────────────────────────


class TestLoincCodeModel(TenantTestCase):
    def test_defaults_and_normalized_display_sync(self):
        c = LoincCode.objects.create(
            code="718-7", display="Hemoglobin [Mass/volume] in Blood", component="Hemoglobin"
        )
        c.refresh_from_db()
        self.assertEqual(c.system, "loinc")  # redeclared default
        self.assertTrue(c.active)
        self.assertEqual(c.property, "")  # optional axis inert by default
        self.assertEqual(c.normalized_display, "hemoglobin [mass/volume] in blood")

    def test_optional_axes_stored(self):
        c = LoincCode.objects.create(
            code="2345-7",
            display="Glucose",
            component="Glucose",
            property="MCnc",
            loinc_system="Ser/Plas",
        )
        c.refresh_from_db()
        self.assertEqual(c.component, "Glucose")
        self.assertEqual(c.property, "MCnc")
        self.assertEqual(c.loinc_system, "Ser/Plas")


# ─── UcumUnit model ───────────────────────────────────────────────────────────


class TestUcumUnitModel(TenantTestCase):
    def test_defaults_and_case_sensitive_code(self):
        u = UcumUnit.objects.create(code="mg/dL", display="milligram per deciliter")
        u.refresh_from_db()
        self.assertEqual(u.system, "ucum")
        self.assertTrue(u.active)
        # UCUM is case-sensitive: 'mg/dL' and 'MG/DL' are distinct symbols.
        other = UcumUnit.objects.create(code="MG/DL", display="uppercased variant")
        self.assertNotEqual(u.pk, other.pk)


# ─── import_loinc ─────────────────────────────────────────────────────────────


class TestImportLoincValid(TenantTestCase):
    def test_creates_rows_with_all_fields(self):
        run_loinc(source=str(LOINC_SAMPLE))
        self.assertEqual(LoincCode.objects.count(), 3)
        hb = LoincCode.objects.get(code="718-7")
        self.assertEqual(hb.display, "FAKE-Hemoglobin [Mass/volume] in Blood")
        self.assertEqual(hb.component, "Hemoglobin")
        self.assertEqual(hb.property, "MCnc")
        self.assertEqual(hb.loinc_system, "Bld")
        self.assertEqual(hb.system, "loinc")

    def test_idempotent_rerun_updates_not_duplicates(self):
        run_loinc(source=str(LOINC_SAMPLE))
        run_loinc(source=str(LOINC_SAMPLE))
        self.assertEqual(LoincCode.objects.count(), 3)

    def test_provenance_log_written(self):
        run_loinc(source=str(LOINC_SAMPLE), loinc_version="2.77")
        log = TerminologyImportLog.objects.filter(system="loinc").latest("ran_at")
        self.assertEqual(log.provenance, "LOINC")
        self.assertEqual(log.version, "2.77")
        self.assertEqual(log.row_count_added, 3)
        self.assertEqual(log.status, TerminologyImportLog.Status.SUCCESS)
        self.assertFalse(log.dry_run)


class TestImportLoincDryRun(TenantTestCase):
    def test_dry_run_writes_nothing(self):
        run_loinc(source=str(LOINC_SAMPLE), dry_run=True)
        self.assertEqual(LoincCode.objects.count(), 0)
        log = TerminologyImportLog.objects.filter(system="loinc").latest("ran_at")
        self.assertTrue(log.dry_run)
        self.assertEqual(log.row_count_added, 3)  # counts what WOULD happen


class TestImportLoincMalformed(TenantTestCase):
    def test_malformed_csv_aborts_with_line_numbers(self):
        with self.assertRaises(CommandError) as ctx:
            run_loinc(source=str(LOINC_MALFORMED))
        msg = str(ctx.exception)
        self.assertIn("LOINC_NUM is empty", msg)
        self.assertIn("LONG_COMMON_NAME is empty", msg)
        self.assertEqual(LoincCode.objects.count(), 0)

    def test_missing_file_raises(self):
        with self.assertRaises(CommandError):
            run_loinc(source=str(FIXTURES / "does_not_exist.csv"))


# ─── import_ucum ──────────────────────────────────────────────────────────────


class TestImportUcumValid(TenantTestCase):
    def test_creates_rows(self):
        run_ucum(source=str(UCUM_SAMPLE))
        self.assertEqual(UcumUnit.objects.count(), 3)
        u = UcumUnit.objects.get(code="mg/dL")
        self.assertEqual(u.display, "milligram per deciliter")
        self.assertEqual(u.system, "ucum")

    def test_case_sensitive_code_preserved_on_import(self):
        run_ucum(source=str(UCUM_SAMPLE))
        # '10*9/L' preserved verbatim (no case-fold / normalization of the code).
        self.assertTrue(UcumUnit.objects.filter(code="10*9/L").exists())

    def test_idempotent_rerun(self):
        run_ucum(source=str(UCUM_SAMPLE))
        run_ucum(source=str(UCUM_SAMPLE))
        self.assertEqual(UcumUnit.objects.count(), 3)

    def test_provenance_log_written(self):
        run_ucum(source=str(UCUM_SAMPLE), ucum_version="2.1")
        log = TerminologyImportLog.objects.filter(system="ucum").latest("ran_at")
        self.assertEqual(log.provenance, "UCUM")
        self.assertEqual(log.version, "2.1")
        self.assertEqual(log.row_count_added, 3)


class TestImportUcumDryRun(TenantTestCase):
    def test_dry_run_writes_nothing(self):
        run_ucum(source=str(UCUM_SAMPLE), dry_run=True)
        self.assertEqual(UcumUnit.objects.count(), 0)


class TestImportUcumMalformed(TenantTestCase):
    def test_malformed_csv_aborts_with_line_numbers(self):
        with self.assertRaises(CommandError) as ctx:
            run_ucum(source=str(UCUM_MALFORMED))
        msg = str(ctx.exception)
        self.assertIn("UCUM_CODE is empty", msg)
        self.assertIn("DISPLAY is empty", msg)
        self.assertEqual(UcumUnit.objects.count(), 0)
