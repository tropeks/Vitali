"""
N1 — Governed nursing terminology catalogs (NANDA-I / NIC / NOC).

Covers, all local (no network):
  * N1-T1 — the governed models (fields, ``system`` default, ``normalized_display``
    sync) for NandaDiagnosis / NicIntervention / NocOutcome.
  * N1-T2 — the CatalogImporter-backed management commands import_nanda /
    import_nic / import_noc: idempotent build, dry-run safety, per-line error
    isolation (malformed CSV), and provenance logging.
  * N1-T3 — registration of nanda/nic/noc in the terminology search registry
    (apps.core.terminology._SYSTEMS + per-system context).
"""

from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.management.commands.import_nanda import Command as ImportNanda
from apps.core.management.commands.import_nic import Command as ImportNic
from apps.core.management.commands.import_noc import Command as ImportNoc
from apps.core.models import NandaDiagnosis, NicIntervention, NocOutcome
from apps.core.terminology import UnknownTerminologySystem, search
from apps.core.terminology_base import TerminologyImportLog
from apps.test_utils import TenantTestCase

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _run(cmd, **options):
    out = StringIO()
    call_command(cmd, stdout=out, stderr=out, **options)
    return out.getvalue()


# ─── N1-T1: models ───────────────────────────────────────────────────────────


class TestNandaDiagnosisModel(TenantTestCase):
    def test_defaults_and_normalized_display_sync(self):
        d = NandaDiagnosis.objects.create(
            code="00132",
            display="Dor Aguda",
            domain="12 Conforto",
            nanda_class="1 Conforto físico",
            definition="Experiência sensorial desagradável",
            defining_characteristics="Expressão facial de dor",
            related_factors="Agente lesivo",
        )
        d.refresh_from_db()
        self.assertEqual(d.system, "nanda")  # redeclared default
        self.assertTrue(d.active)
        self.assertEqual(d.domain, "12 Conforto")
        self.assertEqual(d.nanda_class, "1 Conforto físico")
        self.assertEqual(d.normalized_display, "dor aguda")

    def test_str_contains_code(self):
        d = NandaDiagnosis.objects.create(code="00132", display="Dor Aguda")
        self.assertIn("00132", str(d))


class TestNicInterventionModel(TenantTestCase):
    def test_defaults_and_fields(self):
        n = NicIntervention.objects.create(
            code="1400",
            display="Controle da Dor",
            definition="Alívio da dor",
            activities="Avaliar a dor",
        )
        n.refresh_from_db()
        self.assertEqual(n.system, "nic")
        self.assertTrue(n.active)
        self.assertEqual(n.definition, "Alívio da dor")
        self.assertEqual(n.activities, "Avaliar a dor")
        self.assertEqual(n.normalized_display, "controle da dor")


class TestNocOutcomeModel(TenantTestCase):
    def test_defaults_and_fields(self):
        o = NocOutcome.objects.create(
            code="2102",
            display="Nível de Dor",
            definition="Gravidade da dor observada",
            indicators="Dor relatada",
        )
        o.refresh_from_db()
        self.assertEqual(o.system, "noc")
        self.assertTrue(o.active)
        self.assertEqual(o.definition, "Gravidade da dor observada")
        self.assertEqual(o.indicators, "Dor relatada")
        self.assertEqual(o.normalized_display, "nivel de dor")


# ─── N1-T2: importers ────────────────────────────────────────────────────────


class TestImportNanda(TenantTestCase):
    SAMPLE = FIXTURES / "nanda_sample.csv"
    MALFORMED = FIXTURES / "nanda_malformed.csv"

    def test_creates_rows_with_all_fields(self):
        _run(ImportNanda(), source=str(self.SAMPLE))
        self.assertEqual(NandaDiagnosis.objects.count(), 3)
        d = NandaDiagnosis.objects.get(code="00132")
        self.assertEqual(d.display, "FAKE-Dor aguda")
        self.assertEqual(d.domain, "12 Conforto")
        self.assertEqual(d.nanda_class, "1 Conforto físico")
        self.assertEqual(d.definition, "FAKE-Experiência sensorial desagradável")
        self.assertIn("Expressão facial", d.defining_characteristics)
        self.assertIn("Agente lesivo", d.related_factors)
        self.assertEqual(d.system, "nanda")
        self.assertTrue(d.active)

    def test_normalized_display_populated(self):
        _run(ImportNanda(), source=str(self.SAMPLE))
        d = NandaDiagnosis.objects.get(code="00132")
        self.assertEqual(d.normalized_display, "fake-dor aguda")

    def test_idempotent_rerun_updates_not_duplicates(self):
        _run(ImportNanda(), source=str(self.SAMPLE))
        _run(ImportNanda(), source=str(self.SAMPLE))
        self.assertEqual(NandaDiagnosis.objects.count(), 3)

    def test_provenance_log_written(self):
        _run(ImportNanda(), source=str(self.SAMPLE), nanda_version="2021-2023")
        log = TerminologyImportLog.objects.filter(system="nanda").latest("ran_at")
        self.assertEqual(log.provenance, "NANDA-I")
        self.assertEqual(log.version, "2021-2023")
        self.assertEqual(log.row_count_added, 3)
        self.assertEqual(log.status, TerminologyImportLog.Status.SUCCESS)
        self.assertFalse(log.dry_run)

    def test_dry_run_writes_nothing(self):
        _run(ImportNanda(), source=str(self.SAMPLE), dry_run=True)
        self.assertEqual(NandaDiagnosis.objects.count(), 0)
        log = TerminologyImportLog.objects.filter(system="nanda").latest("ran_at")
        self.assertTrue(log.dry_run)
        self.assertEqual(log.row_count_added, 3)

    def test_malformed_csv_aborts_with_line_numbers(self):
        with self.assertRaises(CommandError) as ctx:
            _run(ImportNanda(), source=str(self.MALFORMED))
        msg = str(ctx.exception)
        self.assertIn("CODIGO is empty", msg)
        self.assertIn("TITULO is empty", msg)
        self.assertEqual(NandaDiagnosis.objects.count(), 0)

    def test_missing_file_raises(self):
        with self.assertRaises(CommandError):
            _run(ImportNanda(), source=str(FIXTURES / "does_not_exist.csv"))


class TestImportNic(TenantTestCase):
    SAMPLE = FIXTURES / "nic_sample.csv"
    MALFORMED = FIXTURES / "nic_malformed.csv"

    def test_creates_rows_with_all_fields(self):
        _run(ImportNic(), source=str(self.SAMPLE))
        self.assertEqual(NicIntervention.objects.count(), 3)
        n = NicIntervention.objects.get(code="1400")
        self.assertEqual(n.display, "FAKE-Controle da dor")
        self.assertIn("Alívio da dor", n.definition)
        self.assertIn("Avaliar a dor", n.activities)
        self.assertEqual(n.system, "nic")

    def test_idempotent_and_provenance(self):
        _run(ImportNic(), source=str(self.SAMPLE))
        _run(ImportNic(), source=str(self.SAMPLE))
        self.assertEqual(NicIntervention.objects.count(), 3)
        log = TerminologyImportLog.objects.filter(system="nic").latest("ran_at")
        self.assertEqual(log.provenance, "NIC")

    def test_dry_run_writes_nothing(self):
        _run(ImportNic(), source=str(self.SAMPLE), dry_run=True)
        self.assertEqual(NicIntervention.objects.count(), 0)

    def test_malformed_csv_aborts(self):
        with self.assertRaises(CommandError):
            _run(ImportNic(), source=str(self.MALFORMED))
        self.assertEqual(NicIntervention.objects.count(), 0)


class TestImportNoc(TenantTestCase):
    SAMPLE = FIXTURES / "noc_sample.csv"
    MALFORMED = FIXTURES / "noc_malformed.csv"

    def test_creates_rows_with_all_fields(self):
        _run(ImportNoc(), source=str(self.SAMPLE))
        self.assertEqual(NocOutcome.objects.count(), 3)
        o = NocOutcome.objects.get(code="2102")
        self.assertEqual(o.display, "FAKE-Nível de dor")
        self.assertIn("Gravidade da dor", o.definition)
        self.assertIn("Dor relatada", o.indicators)
        self.assertEqual(o.system, "noc")

    def test_idempotent_and_provenance(self):
        _run(ImportNoc(), source=str(self.SAMPLE))
        _run(ImportNoc(), source=str(self.SAMPLE))
        self.assertEqual(NocOutcome.objects.count(), 3)
        log = TerminologyImportLog.objects.filter(system="noc").latest("ran_at")
        self.assertEqual(log.provenance, "NOC")

    def test_dry_run_writes_nothing(self):
        _run(ImportNoc(), source=str(self.SAMPLE), dry_run=True)
        self.assertEqual(NocOutcome.objects.count(), 0)

    def test_malformed_csv_aborts(self):
        with self.assertRaises(CommandError):
            _run(ImportNoc(), source=str(self.MALFORMED))
        self.assertEqual(NocOutcome.objects.count(), 0)


# ─── N1-T3: terminology search registry ──────────────────────────────────────


class TestNursingCatalogSearchService(TenantTestCase):
    def setUp(self):
        NandaDiagnosis.objects.create(
            code="00132",
            display="Dor aguda",
            domain="12 Conforto",
            nanda_class="1 Conforto físico",
            definition="Experiência sensorial desagradável",
        )
        NandaDiagnosis.objects.create(code="00999", display="Inativo antigo", active=False)
        NicIntervention.objects.create(
            code="1400", display="Controle da dor", definition="Alívio da dor"
        )
        NocOutcome.objects.create(
            code="2102", display="Nível de dor", definition="Gravidade da dor observada"
        )

    def test_nanda_exact_code(self):
        results = search("nanda", "00132")
        self.assertEqual(results[0]["code"], "00132")
        self.assertEqual(results[0]["system"], "nanda")
        self.assertEqual(results[0]["display"], "Dor aguda")
        self.assertTrue(results[0]["active"])

    def test_nanda_accent_insensitive_display(self):
        codes = [r["code"] for r in search("nanda", "dor")]
        self.assertIn("00132", codes)

    def test_nanda_active_only(self):
        codes = [r["code"] for r in search("nanda", "00999")]
        self.assertNotIn("00999", codes)

    def test_nanda_context_fields(self):
        ctx = search("nanda", "00132")[0]["context"]
        self.assertEqual(ctx["domain"], "12 Conforto")
        self.assertEqual(ctx["class"], "1 Conforto físico")
        self.assertIn("Experiência", ctx["definition"])

    def test_nic_search_and_context(self):
        results = search("nic", "1400")
        self.assertEqual(results[0]["code"], "1400")
        self.assertIn("Alívio", results[0]["context"]["definition"])

    def test_noc_search_and_context(self):
        results = search("noc", "2102")
        self.assertEqual(results[0]["code"], "2102")
        self.assertIn("Gravidade", results[0]["context"]["definition"])

    def test_all_three_registered(self):
        for system in ("nanda", "nic", "noc"):
            self.assertIsInstance(search(system, "zzz-nomatch"), list)

    def test_unknown_system_still_raises(self):
        with self.assertRaises(UnknownTerminologySystem):
            search("bogus-nursing", "x")
