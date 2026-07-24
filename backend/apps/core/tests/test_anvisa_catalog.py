"""
E3-T1 — ANVISA drug catalog (core.AnvisaProduct) + import_anvisa importer.

Covers the model (governed fields, normalized_display sync, is_controlled, the
by_ean lookup) and the CatalogImporter-backed management command: idempotent
build, dry-run safety, per-line error isolation (malformed CSV), provenance
logging, and EAN lookup. All local — no network.
"""

from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.catalog_models import AnvisaProduct
from apps.core.management.commands.import_anvisa import Command as ImportAnvisa
from apps.core.terminology_base import TerminologyImportLog
from apps.test_utils import TenantTestCase

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SAMPLE = FIXTURES / "anvisa_sample.csv"
MALFORMED = FIXTURES / "anvisa_malformed.csv"


def run_import(**options):
    out = StringIO()
    call_command(ImportAnvisa(), stdout=out, stderr=out, **options)
    return out.getvalue()


class TestAnvisaProductModel(TenantTestCase):
    def test_defaults_and_normalized_display_sync(self):
        p = AnvisaProduct.objects.create(
            code="R1", display="Amoxicilina Não-Genérico", dcb="Amoxicilina"
        )
        p.refresh_from_db()
        self.assertEqual(p.system, "anvisa")  # redeclared default
        self.assertTrue(p.active)
        self.assertEqual(p.controlled_class, "none")
        self.assertFalse(p.is_controlled)
        self.assertEqual(p.normalized_display, "amoxicilina nao-generico")

    def test_is_controlled_true_for_tarja(self):
        p = AnvisaProduct.objects.create(code="R2", display="Morfina", controlled_class="A1")
        self.assertTrue(p.is_controlled)

    def test_by_ean_lookup(self):
        p = AnvisaProduct.objects.create(code="R3", display="X", ean="7890000000000")
        self.assertEqual(AnvisaProduct.by_ean("7890000000000"), p)
        self.assertEqual(AnvisaProduct.by_ean(" 7890000000000 "), p)  # trimmed
        self.assertIsNone(AnvisaProduct.by_ean(""))
        self.assertIsNone(AnvisaProduct.by_ean(None))
        self.assertIsNone(AnvisaProduct.by_ean("0000000000000"))

    def test_by_ean_ignores_inactive(self):
        AnvisaProduct.objects.create(
            code="R4", display="Inactive", ean="7891231231231", active=False
        )
        self.assertIsNone(AnvisaProduct.by_ean("7891231231231"))


class TestImportAnvisaValid(TenantTestCase):
    def test_creates_rows_with_all_fields(self):
        run_import(source=str(SAMPLE))
        self.assertEqual(AnvisaProduct.objects.count(), 3)
        amox = AnvisaProduct.objects.get(code="1000000000001")
        self.assertEqual(amox.display, "FAKE-Amoxicilina 500mg")
        self.assertEqual(amox.dcb, "Amoxicilina")
        self.assertEqual(amox.ean, "7891111111111")
        self.assertEqual(amox.therapeutic_class, "ANTIBACTERIANOS")
        self.assertEqual(amox.controlled_class, "none")
        self.assertEqual(amox.system, "anvisa")

    def test_tarja_imported_for_controlled(self):
        run_import(source=str(SAMPLE))
        morfina = AnvisaProduct.objects.get(code="1000000000002")
        self.assertEqual(morfina.controlled_class, "A1")
        self.assertTrue(morfina.is_controlled)

    def test_normalized_display_populated(self):
        run_import(source=str(SAMPLE))
        p = AnvisaProduct.objects.get(code="1000000000002")
        self.assertEqual(p.normalized_display, "fake-morfina 10mg/ml")

    def test_ean_lookup_after_import(self):
        run_import(source=str(SAMPLE))
        p = AnvisaProduct.by_ean("7893333333333")
        self.assertIsNotNone(p)
        self.assertEqual(p.code, "1000000000003")

    def test_idempotent_rerun_updates_not_duplicates(self):
        run_import(source=str(SAMPLE))
        run_import(source=str(SAMPLE))
        self.assertEqual(AnvisaProduct.objects.count(), 3)

    def test_provenance_log_written(self):
        run_import(source=str(SAMPLE), anvisa_version="2024")
        log = TerminologyImportLog.objects.filter(system="anvisa").latest("ran_at")
        self.assertEqual(log.provenance, "ANVISA")
        self.assertEqual(log.version, "2024")
        self.assertEqual(log.row_count_added, 3)
        self.assertEqual(log.status, TerminologyImportLog.Status.SUCCESS)
        self.assertFalse(log.dry_run)


class TestImportAnvisaDryRun(TenantTestCase):
    def test_dry_run_writes_nothing(self):
        run_import(source=str(SAMPLE), dry_run=True)
        self.assertEqual(AnvisaProduct.objects.count(), 0)
        log = TerminologyImportLog.objects.filter(system="anvisa").latest("ran_at")
        self.assertTrue(log.dry_run)
        self.assertEqual(log.row_count_added, 3)  # counts what WOULD happen


class TestImportAnvisaMalformed(TenantTestCase):
    def test_malformed_csv_aborts_with_line_numbers(self):
        # Parse-time validation fails loud: nothing committed, both bad lines named.
        with self.assertRaises(CommandError) as ctx:
            run_import(source=str(MALFORMED))
        msg = str(ctx.exception)
        self.assertIn("REGISTRO is empty", msg)
        self.assertIn("PRODUTO is empty", msg)
        self.assertEqual(AnvisaProduct.objects.count(), 0)

    def test_missing_file_raises(self):
        with self.assertRaises(CommandError):
            run_import(source=str(FIXTURES / "does_not_exist.csv"))
