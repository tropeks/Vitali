"""
L1 — Governed CNES bed-type catalog (core.BedType).

Mirrors test_nursing_catalog.py, covering (all local, no network):
  * the governed model (fields, ``system`` default, ``normalized_display`` sync)
  * the CatalogImporter-backed management command import_bed_types: idempotent
    build, dry-run safety, per-line error isolation, provenance logging
  * registration of bed_type in the terminology search registry
    (apps.core.terminology._SYSTEMS + per-system context)
"""

from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import transaction
from django.db.models.deletion import ProtectedError

from apps.core.management.commands.import_bed_types import Command as ImportBedTypes
from apps.core.models import BedType
from apps.core.terminology import UnknownTerminologySystem, search
from apps.core.terminology_base import TerminologyImportLog
from apps.test_utils import TenantTestCase

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _run(cmd, **options):
    out = StringIO()
    call_command(cmd, stdout=out, stderr=out, **options)
    return out.getvalue()


# ─── model ───────────────────────────────────────────────────────────────────


class TestBedTypeModel(TenantTestCase):
    def test_defaults_and_normalized_display_sync(self):
        b = BedType.objects.create(code="74", display="UTI Adulto Tipo II", category="Complementar")
        b.refresh_from_db()
        self.assertEqual(b.system, "bed_type")  # redeclared default
        self.assertTrue(b.active)
        self.assertEqual(b.category, "Complementar")
        self.assertEqual(b.normalized_display, "uti adulto tipo ii")

    def test_str_contains_code(self):
        b = BedType.objects.create(code="02", display="Clínico")
        self.assertIn("02", str(b))


# ─── importer ────────────────────────────────────────────────────────────────


class TestImportBedTypes(TenantTestCase):
    SAMPLE = FIXTURES / "bed_types_sample.csv"
    MALFORMED = FIXTURES / "bed_types_malformed.csv"

    def test_creates_rows_with_all_fields(self):
        _run(ImportBedTypes(), source=str(self.SAMPLE))
        self.assertEqual(BedType.objects.count(), 5)
        b = BedType.objects.get(code="74")
        self.assertEqual(b.display, "FAKE-UTI adulto tipo II")
        self.assertEqual(b.category, "FAKE-Complementar")
        self.assertEqual(b.system, "bed_type")
        self.assertTrue(b.active)

    def test_normalized_display_populated(self):
        _run(ImportBedTypes(), source=str(self.SAMPLE))
        b = BedType.objects.get(code="74")
        self.assertEqual(b.normalized_display, "fake-uti adulto tipo ii")

    def test_idempotent_and_provenance(self):
        _run(ImportBedTypes(), source=str(self.SAMPLE))
        _run(ImportBedTypes(), source=str(self.SAMPLE))
        self.assertEqual(BedType.objects.count(), 5)
        log = TerminologyImportLog.objects.filter(system="bed_type").latest("ran_at")
        self.assertEqual(log.provenance, "CNES")
        self.assertEqual(log.status, TerminologyImportLog.Status.SUCCESS)

    def test_dry_run_writes_nothing(self):
        _run(ImportBedTypes(), source=str(self.SAMPLE), dry_run=True)
        self.assertEqual(BedType.objects.count(), 0)
        log = TerminologyImportLog.objects.filter(system="bed_type").latest("ran_at")
        self.assertTrue(log.dry_run)
        self.assertEqual(log.row_count_added, 5)

    def test_malformed_csv_aborts(self):
        with self.assertRaises(CommandError):
            _run(ImportBedTypes(), source=str(self.MALFORMED))
        self.assertEqual(BedType.objects.count(), 0)


# ─── terminology search registry ─────────────────────────────────────────────


class TestBedTypeSearchService(TenantTestCase):
    def setUp(self):
        BedType.objects.create(code="74", display="UTI adulto tipo II", category="Complementar")
        BedType.objects.create(code="99", display="Inativo antigo", active=False)

    def test_exact_code(self):
        results = search("bed_type", "74")
        self.assertEqual(results[0]["code"], "74")
        self.assertEqual(results[0]["system"], "bed_type")
        self.assertEqual(results[0]["display"], "UTI adulto tipo II")
        self.assertTrue(results[0]["active"])

    def test_accent_insensitive_display(self):
        codes = [r["code"] for r in search("bed_type", "uti")]
        self.assertIn("74", codes)

    def test_active_only(self):
        codes = [r["code"] for r in search("bed_type", "99")]
        self.assertNotIn("99", codes)

    def test_context_fields(self):
        ctx = search("bed_type", "74")[0]["context"]
        self.assertEqual(ctx["category"], "Complementar")

    def test_registered(self):
        self.assertIsInstance(search("bed_type", "zzz-nomatch"), list)

    def test_unknown_system_still_raises(self):
        with self.assertRaises(UnknownTerminologySystem):
            search("bogus-beds", "x")


# ─── cross-schema delete protection (protect_bed_type_deletion) ───────────────


class TestBedTypeDeleteProtection(TenantTestCase):
    def _bed_infra(self):
        from apps.emr.models import Bed, InpatientUnit, Room
        from apps.organization.models import Facility, LegalEntity

        legal = LegalEntity.objects.create(code="LEDEL", name="Hosp Del")
        facility = Facility.objects.create(code="FACDEL", name="Del", legal_entity=legal)
        unit = InpatientUnit.objects.create(facility=facility, name="Ala D", code="ALA-D")
        room = Room.objects.create(unit=unit, name="D1")
        return Bed, unit, room

    def test_delete_blocked_when_referenced_by_bed(self):
        Bed, unit, room = self._bed_infra()
        bt = BedType.objects.create(code="74", display="UTI adulto tipo II")
        Bed.objects.create(room=room, unit=unit, identifier="D1-A", bed_type=bt)
        with self.assertRaises(ProtectedError) as ctx, transaction.atomic():
            bt.delete()
        self.assertIn("BedType", str(ctx.exception))
        self.assertIn("Bed", str(ctx.exception))
        self.assertTrue(BedType.objects.filter(pk=bt.pk).exists())

    def test_delete_blocked_when_referenced_by_unit_default(self):
        _Bed, _unit, _room = self._bed_infra()
        from apps.emr.models import InpatientUnit
        from apps.organization.models import Facility, LegalEntity

        bt = BedType.objects.create(code="02", display="Clínico")
        legal = LegalEntity.objects.create(code="LEDEF", name="Hosp Def")
        facility = Facility.objects.create(code="FACDEF", name="Def", legal_entity=legal)
        InpatientUnit.objects.create(
            facility=facility, name="Ala Def", code="ALA-DEF", default_bed_type=bt
        )
        with self.assertRaises(ProtectedError) as ctx, transaction.atomic():
            bt.delete()
        self.assertIn("InpatientUnit", str(ctx.exception))
        self.assertTrue(BedType.objects.filter(pk=bt.pk).exists())

    def test_delete_allowed_when_unreferenced(self):
        bt = BedType.objects.create(code="00", display="Sem uso")
        bt.delete()
        self.assertFalse(BedType.objects.filter(pk=bt.pk).exists())
