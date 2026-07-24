"""
E1-T3 — hierarchical CID-10 importer (core.management.commands.import_cid10).

Invokes the CORE command class DIRECTLY (not by name): `apps.ai` also registers
an `import_cid10` command and, being later in INSTALLED_APPS, shadows the core
one for `manage.py import_cid10`. Tests target the new core Command instance so
they are unambiguous. (Collision flagged for the parent to retire the ai command.)
"""

from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.management.commands.import_cid10 import Command as CoreImportCID10
from apps.core.models import CID10Code
from apps.core.terminology_base import TerminologyImportLog
from apps.test_utils import TenantTestCase

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SAMPLE = FIXTURES / "cid10_sample.csv"
MALFORMED = FIXTURES / "cid10_malformed.csv"


def run_import(**options):
    out = StringIO()
    call_command(CoreImportCID10(), stdout=out, stderr=out, **options)
    return out.getvalue()


class TestImportCID10Valid(TenantTestCase):
    def test_creates_rows_with_hierarchy_labels(self):
        run_import(source=str(SAMPLE))
        self.assertEqual(CID10Code.objects.count(), 4)
        a00 = CID10Code.objects.get(code="A00")
        self.assertEqual(a00.description, "FAKE-Colera")
        self.assertEqual(a00.category, "A00-A09")
        self.assertIn("infecciosas", a00.chapter)
        self.assertTrue(a00.is_notifiable)  # NOTIFICACAO=S
        self.assertTrue(a00.active)

    def test_parent_linked_from_parent_column(self):
        run_import(source=str(SAMPLE))
        a000 = CID10Code.objects.get(code="A000")
        self.assertIsNotNone(a000.parent)
        self.assertEqual(a000.parent.code, "A00")
        # And reverse relation
        self.assertIn(a000, CID10Code.objects.get(code="A00").children.all())

    def test_governed_metadata_imported(self):
        run_import(source=str(SAMPLE))
        o00 = CID10Code.objects.get(code="O00")
        self.assertEqual(o00.sex_allowed, "F")
        p00 = CID10Code.objects.get(code="P00")
        self.assertEqual(p00.age_min, 0)
        self.assertEqual(p00.age_max, 28)

    def test_normalized_description_populated(self):
        run_import(source=str(SAMPLE))
        a00 = CID10Code.objects.get(code="A00")
        self.assertEqual(a00.normalized_description, "fake-colera")

    def test_idempotent_rerun_updates_not_duplicates(self):
        run_import(source=str(SAMPLE))
        run_import(source=str(SAMPLE))
        self.assertEqual(CID10Code.objects.count(), 4)
        # parent still linked after re-run
        self.assertEqual(CID10Code.objects.get(code="A000").parent.code, "A00")

    def test_provenance_log_source_datasus(self):
        run_import(source=str(SAMPLE))
        log = TerminologyImportLog.objects.filter(system="cid10").latest("ran_at")
        self.assertEqual(log.provenance, "DATASUS")
        self.assertEqual(log.source, TerminologyImportLog.Source.MANAGEMENT_COMMAND)
        self.assertEqual(log.row_count_added, 4)
        self.assertFalse(log.dry_run)


class TestImportCID10DryRun(TenantTestCase):
    def test_dry_run_writes_nothing(self):
        run_import(source=str(SAMPLE), dry_run=True)
        self.assertEqual(CID10Code.objects.count(), 0)

    def test_dry_run_logs_dry_run_flag(self):
        run_import(source=str(SAMPLE), dry_run=True)
        log = TerminologyImportLog.objects.filter(system="cid10").latest("ran_at")
        self.assertTrue(log.dry_run)


class TestImportCID10Errors(TenantTestCase):
    def test_missing_file_raises(self):
        with self.assertRaises(CommandError):
            run_import(source=str(FIXTURES / "does_not_exist.csv"))

    def test_blank_code_line_aborts_with_line_number(self):
        with self.assertRaises(CommandError) as ctx:
            run_import(source=str(MALFORMED))
        self.assertIn("4", str(ctx.exception))  # physical line of the blank-code row
        # Fail-loud: nothing committed
        self.assertEqual(CID10Code.objects.count(), 0)
