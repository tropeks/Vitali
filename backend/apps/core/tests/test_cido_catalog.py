"""
CID-O morphology — governed catalog (core.CIDOMorphology).

Mirrors test_adt_catalog.py: the governed model, the CatalogImporter-backed
import_cido command (idempotency, dry-run safety, per-line error isolation,
provenance logging, behaviour derived from code), and registration in the
terminology search registry.
"""

from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.cido_models import CIDOMorphology
from apps.core.management.commands.import_cido import Command as ImportCido
from apps.core.terminology import UnknownTerminologySystem, search
from apps.core.terminology_base import TerminologyImportLog
from apps.test_utils import TenantTestCase

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _run(cmd, **options):
    out = StringIO()
    call_command(cmd, stdout=out, stderr=out, **options)
    return out.getvalue()


class TestCIDOMorphologyModel(TenantTestCase):
    def test_defaults_and_normalized_display_sync(self):
        m = CIDOMorphology.objects.create(
            code="8500/3", display="Carcinoma Ductal Invasivo", behaviour="3"
        )
        m.refresh_from_db()
        self.assertEqual(m.system, "cid_o")
        self.assertTrue(m.active)
        self.assertEqual(m.behaviour, "3")
        self.assertEqual(m.normalized_display, "carcinoma ductal invasivo")

    def test_str_contains_code(self):
        m = CIDOMorphology.objects.create(code="8000/0", display="Neoplasia benigna")
        self.assertIn("8000/0", str(m))


class TestImportCido(TenantTestCase):
    SAMPLE = FIXTURES / "cido_sample.csv"
    MALFORMED = FIXTURES / "cido_malformed.csv"

    def test_creates_rows_with_all_fields(self):
        _run(ImportCido(), source=str(self.SAMPLE))
        self.assertEqual(CIDOMorphology.objects.count(), 4)
        m = CIDOMorphology.objects.get(code="8500/3")
        self.assertEqual(m.display, "FAKE-Carcinoma ductal invasivo")
        self.assertEqual(m.behaviour, "3")
        self.assertEqual(m.cid10_ref, "C50.9")
        self.assertEqual(m.system, "cid_o")

    def test_behaviour_derived_from_code_when_column_blank(self):
        # cido_sample has explicit COMPORTAMENTO; assert the importer would also
        # derive it from the code suffix by importing a code with a blank column.
        from tempfile import NamedTemporaryFile

        with NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as fh:
            fh.write(
                "CODIGO;TITULO;COMPORTAMENTO;CID10_REF\n8140/6;FAKE-Adenocarcinoma metastático;;\n"
            )
            path = fh.name
        _run(ImportCido(), source=path)
        m = CIDOMorphology.objects.get(code="8140/6")
        self.assertEqual(m.behaviour, "6")  # derived from "/6"

    def test_idempotent_and_provenance(self):
        _run(ImportCido(), source=str(self.SAMPLE))
        _run(ImportCido(), source=str(self.SAMPLE))
        self.assertEqual(CIDOMorphology.objects.count(), 4)
        log = TerminologyImportLog.objects.filter(system="cid_o").latest("ran_at")
        self.assertEqual(log.provenance, "DATASUS")
        self.assertEqual(log.status, TerminologyImportLog.Status.SUCCESS)

    def test_dry_run_writes_nothing(self):
        _run(ImportCido(), source=str(self.SAMPLE), dry_run=True)
        self.assertEqual(CIDOMorphology.objects.count(), 0)
        log = TerminologyImportLog.objects.filter(system="cid_o").latest("ran_at")
        self.assertTrue(log.dry_run)
        self.assertEqual(log.row_count_added, 4)

    def test_malformed_csv_aborts(self):
        with self.assertRaises(CommandError):
            _run(ImportCido(), source=str(self.MALFORMED))
        self.assertEqual(CIDOMorphology.objects.count(), 0)


class TestCIDOSearchService(TenantTestCase):
    def setUp(self):
        CIDOMorphology.objects.create(
            code="8500/3", display="Carcinoma ductal invasivo", behaviour="3", cid10_ref="C50.9"
        )
        CIDOMorphology.objects.create(code="9999/9", display="Inativo antigo", active=False)

    def test_exact_code(self):
        results = search("cid_o", "8500/3")
        self.assertEqual(results[0]["code"], "8500/3")
        self.assertEqual(results[0]["system"], "cid_o")

    def test_context_fields(self):
        ctx = search("cid_o", "8500/3")[0]["context"]
        self.assertEqual(ctx["behaviour"], "3")
        self.assertEqual(ctx["cid10_ref"], "C50.9")

    def test_active_only(self):
        codes = [r["code"] for r in search("cid_o", "9999/9")]
        self.assertNotIn("9999/9", codes)

    def test_unknown_system_still_raises(self):
        with self.assertRaises(UnknownTerminologySystem):
            search("bogus-cido", "x")
