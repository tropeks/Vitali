"""
E1-T1 — Terminology backbone (abstract catalog + import engine).

Tests exercise the reusable pieces against a tiny throwaway concrete subclass
(`_FakeCatalog`) whose table is created/dropped via schema_editor — no migration
is committed for the fixture model.
"""

from django.db import connection
from django_tenants.utils import get_public_schema_name, schema_context

from apps.core.terminology_base import (
    CatalogImporter,
    TerminologyCatalog,
    TerminologyImportLog,
    normalize_text,
)
from apps.test_utils import TenantTestCase


# ── Throwaway concrete catalog used only by these tests ──────────────────────
# `managed = False` keeps `_FakeCatalog` out of makemigrations AND out of the
# TransactionTestCase flush / serialized_rollback machinery (which FastTenantTest
# uses to restore the tenant row) — both only touch *managed* models. We create
# its table ourselves in the PUBLIC schema (core is SHARED) around each class and
# clear its rows per test for isolation.
class _FakeCatalog(TerminologyCatalog):
    class Meta:
        app_label = "core"
        managed = False


class _FakeImporter(CatalogImporter):
    model = _FakeCatalog
    system = "fake"

    def build_defaults(self, row):
        # Deliberately raise on a sentinel so per-row isolation can be tested.
        if row.get("boom"):
            raise ValueError("intentional row failure")
        return {"display": row["display"], "active": row.get("active", True)}


class _CatalogTestBase(TenantTestCase):
    """Creates/drops the throwaway `_FakeCatalog` table around the class.

    The table is created in the PUBLIC schema (core is SHARED) so it is visible
    from every schema via the search_path AND so the per-test fixture flush /
    serialization that enumerates core models never hits a missing relation.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with schema_context(get_public_schema_name()), connection.schema_editor() as editor:
            editor.create_model(_FakeCatalog)

    @classmethod
    def tearDownClass(cls):
        try:
            with schema_context(get_public_schema_name()), connection.schema_editor() as editor:
                editor.delete_model(_FakeCatalog)
        except Exception:
            pass
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        # Unmanaged table is not flushed between tests — clear it ourselves.
        _FakeCatalog.objects.all().delete()


class TestNormalizeText(_CatalogTestBase):
    def test_strips_accents_and_lowercases(self):
        self.assertEqual(
            normalize_text("Diabetes Melito Não-Especificado"),
            normalize_text("diabetes melito nao-especificado"),
        )
        self.assertEqual(normalize_text("Hipertensão"), "hipertensao")
        self.assertEqual(normalize_text("ÁÉÍÓÚÇ"), "aeiouc")

    def test_empty_and_none(self):
        self.assertEqual(normalize_text(""), "")
        self.assertEqual(normalize_text(None), "")


class TestTerminologyCatalogModel(_CatalogTestBase):
    def test_save_syncs_normalized_display(self):
        obj = _FakeCatalog.objects.create(
            code="A1", display="Hipertensão Essencial", system="fake", version="v1"
        )
        obj.refresh_from_db()
        self.assertEqual(obj.normalized_display, "hipertensao essencial")

    def test_normalized_display_updates_on_change(self):
        obj = _FakeCatalog.objects.create(code="A2", display="Foo", system="fake", version="v1")
        obj.display = "Coração"
        obj.save()
        obj.refresh_from_db()
        self.assertEqual(obj.normalized_display, "coracao")

    def test_str(self):
        obj = _FakeCatalog(code="A3", display="Something", system="fake")
        self.assertIn("A3", str(obj))


class TestCatalogImporter(_CatalogTestBase):
    def _rows(self):
        return [
            {"code": "A00", "display": "Cólera"},
            {"code": "A01", "display": "Febre tifoide"},
        ]

    def test_idempotent_upsert(self):
        imp = _FakeImporter(version="2024", provenance="TESTSRC")
        r1 = imp.run(self._rows())
        self.assertEqual((r1.created, r1.updated), (2, 0))
        self.assertEqual(_FakeCatalog.objects.count(), 2)

        # Re-running the same rows updates in place — no duplicates.
        r2 = _FakeImporter(version="2024", provenance="TESTSRC").run(self._rows())
        self.assertEqual((r2.created, r2.updated), (0, 2))
        self.assertEqual(_FakeCatalog.objects.count(), 2)

    def test_upsert_keyed_on_system_code_version(self):
        _FakeImporter(version="2024").run([{"code": "A00", "display": "Cólera"}])
        # Same code, different version → a NEW row (natural key includes version).
        _FakeImporter(version="2025").run([{"code": "A00", "display": "Cólera 2025"}])
        self.assertEqual(_FakeCatalog.objects.filter(code="A00").count(), 2)

    def test_per_row_error_isolation(self):
        rows = [
            {"code": "B00", "display": "ok one"},
            {"boom": True, "code": "B01", "display": "will fail"},
            {"code": "B02", "display": "ok two"},
        ]
        result = _FakeImporter(version="2024").run(rows)
        self.assertEqual(result.created, 2)
        self.assertEqual(result.skipped, 1)
        self.assertEqual(result.error_count, 1)
        self.assertEqual(result.status, TerminologyImportLog.Status.PARTIAL)
        # Good rows persisted despite the bad one.
        self.assertTrue(_FakeCatalog.objects.filter(code="B00").exists())
        self.assertTrue(_FakeCatalog.objects.filter(code="B02").exists())
        self.assertFalse(_FakeCatalog.objects.filter(code="B01").exists())

    def test_dry_run_writes_nothing(self):
        result = _FakeImporter(version="2024", dry_run=True).run(self._rows())
        self.assertEqual(result.created, 2)  # counts what WOULD happen
        self.assertTrue(result.dry_run)
        self.assertEqual(_FakeCatalog.objects.count(), 0)  # rolled back

    def test_provenance_log_written(self):
        imp = _FakeImporter(version="2024", provenance="DATASUS")
        result = imp.run(self._rows())
        log = TerminologyImportLog.objects.get(id=result.log_id)
        self.assertEqual(log.system, "fake")
        self.assertEqual(log.version, "2024")
        self.assertEqual(log.provenance, "DATASUS")
        self.assertEqual(log.row_count_added, 2)
        self.assertEqual(log.status, TerminologyImportLog.Status.SUCCESS)

    def test_all_rows_failing_is_error_status(self):
        rows = [{"boom": True, "code": "C00", "display": "x"}]
        result = _FakeImporter(version="2024").run(rows)
        self.assertEqual(result.status, TerminologyImportLog.Status.ERROR)
        self.assertEqual(result.created, 0)

    def test_subclass_must_set_model_and_system(self):
        with self.assertRaises(ValueError):
            CatalogImporter(version="2024")
