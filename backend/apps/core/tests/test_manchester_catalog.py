"""
E1 — Governed Manchester triage catalog (core.ManchesterFlowchart /
core.ManchesterDiscriminator + acuidade).

Mirrors test_adt_catalog.py, covering (all local, no network):
  * the AcuityLevel enum + ACUITY_TARGET_MINUTES mapping + acuity_target_minutes()
  * the governed flowchart model (system default, normalized_display sync) and its
    registration in the terminology search registry
  * the discriminator model: FK to flowchart, unique (flowchart, code), acuity
  * the import_manchester management command: fluxogramas + discriminadores,
    idempotent, dry-run safety, per-line error isolation, provenance logging
  * RBAC on the DRF CRUD surface (emergency.read reads, emergency.manage writes,
    no-perm 403)
"""

from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from apps.core.management.commands.import_manchester import Command as ImportManchester
from apps.core.manchester_catalog_models import (
    ACUITY_TARGET_MINUTES,
    AcuityLevel,
    ManchesterDiscriminator,
    ManchesterFlowchart,
    acuity_target_minutes,
)
from apps.core.models import Role, User
from apps.core.terminology import UnknownTerminologySystem, search
from apps.core.terminology_base import TerminologyImportLog
from apps.test_utils import TenantTestCase

FIXTURES = Path(__file__).resolve().parent / "fixtures"
BASE = "/api/v1"


def _run(cmd, **options):
    out = StringIO()
    call_command(cmd, stdout=out, stderr=out, **options)
    return out.getvalue()


# ─── acuidade ────────────────────────────────────────────────────────────────


class TestAcuityLevel(TenantTestCase):
    def test_five_levels(self):
        self.assertEqual(
            set(AcuityLevel.values),
            {"vermelho", "laranja", "amarelo", "verde", "azul"},
        )

    def test_target_minutes_mapping(self):
        self.assertEqual(ACUITY_TARGET_MINUTES[AcuityLevel.VERMELHO], 0)
        self.assertEqual(ACUITY_TARGET_MINUTES[AcuityLevel.LARANJA], 10)
        self.assertEqual(ACUITY_TARGET_MINUTES[AcuityLevel.AMARELO], 60)
        self.assertEqual(ACUITY_TARGET_MINUTES[AcuityLevel.VERDE], 120)
        self.assertEqual(ACUITY_TARGET_MINUTES[AcuityLevel.AZUL], 240)

    def test_helper(self):
        self.assertEqual(acuity_target_minutes("vermelho"), 0)
        self.assertEqual(acuity_target_minutes(AcuityLevel.AZUL), 240)

    def test_helper_unknown_raises(self):
        with self.assertRaises((KeyError, ValueError)):
            acuity_target_minutes("roxo")


# ─── model ───────────────────────────────────────────────────────────────────


class TestManchesterModels(TenantTestCase):
    def test_flowchart_defaults_and_normalized_display_sync(self):
        fc = ManchesterFlowchart.objects.create(code="FL01", display="Dor Torácica")
        fc.refresh_from_db()
        self.assertEqual(fc.system, "manchester_flowchart")
        self.assertTrue(fc.active)
        self.assertEqual(fc.normalized_display, "dor toracica")

    def test_discriminator_fk_and_acuity(self):
        fc = ManchesterFlowchart.objects.create(code="FL01", display="Dor torácica")
        d = ManchesterDiscriminator.objects.create(
            flowchart=fc, code="D001", name="Dor pré-cordial", acuity_level="laranja"
        )
        self.assertEqual(d.flowchart, fc)
        self.assertEqual(d.acuity_level, "laranja")
        self.assertEqual(d.target_minutes, 10)
        self.assertFalse(d.is_general)
        self.assertIn(d, fc.discriminators.all())

    def test_discriminator_unique_per_flowchart(self):
        fc = ManchesterFlowchart.objects.create(code="FL01", display="Dor torácica")
        ManchesterDiscriminator.objects.create(
            flowchart=fc, code="D001", name="A", acuity_level="verde"
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            ManchesterDiscriminator.objects.create(
                flowchart=fc, code="D001", name="B", acuity_level="azul"
            )

    def test_same_code_ok_across_flowcharts(self):
        fc1 = ManchesterFlowchart.objects.create(code="FL01", display="Dor torácica")
        fc2 = ManchesterFlowchart.objects.create(code="FL02", display="Dispneia")
        ManchesterDiscriminator.objects.create(
            flowchart=fc1, code="GEN01", name="Via aérea", acuity_level="vermelho"
        )
        # Same code, different flowchart → allowed.
        ManchesterDiscriminator.objects.create(
            flowchart=fc2, code="GEN01", name="Via aérea", acuity_level="vermelho"
        )
        self.assertEqual(ManchesterDiscriminator.objects.filter(code="GEN01").count(), 2)


# ─── importer ────────────────────────────────────────────────────────────────


class TestImportManchester(TenantTestCase):
    SAMPLE = FIXTURES / "manchester_sample.csv"
    MALFORMED = FIXTURES / "manchester_malformed.csv"

    def test_creates_flowcharts_and_discriminators(self):
        _run(ImportManchester(), source=str(self.SAMPLE))
        self.assertEqual(ManchesterFlowchart.objects.count(), 3)
        self.assertEqual(ManchesterDiscriminator.objects.count(), 7)
        fc = ManchesterFlowchart.objects.get(code="FL01")
        self.assertEqual(fc.display, "FAKE-Dor torácica")
        self.assertEqual(fc.system, "manchester_flowchart")
        d = ManchesterDiscriminator.objects.get(flowchart=fc, code="D001")
        self.assertEqual(d.acuity_level, "laranja")
        self.assertEqual(d.description, "FAKE-Dor retroesternal em aperto")
        gen = ManchesterDiscriminator.objects.get(flowchart=fc, code="GEN01")
        self.assertTrue(gen.is_general)
        self.assertEqual(gen.acuity_level, "vermelho")

    def test_idempotent_and_provenance(self):
        _run(ImportManchester(), source=str(self.SAMPLE))
        _run(ImportManchester(), source=str(self.SAMPLE))
        self.assertEqual(ManchesterFlowchart.objects.count(), 3)
        self.assertEqual(ManchesterDiscriminator.objects.count(), 7)
        log = TerminologyImportLog.objects.filter(system="manchester_flowchart").latest("ran_at")
        self.assertEqual(log.provenance, "GBCR")
        self.assertEqual(log.status, TerminologyImportLog.Status.SUCCESS)

    def test_dry_run_writes_nothing_but_logs(self):
        _run(ImportManchester(), source=str(self.SAMPLE), dry_run=True)
        self.assertEqual(ManchesterFlowchart.objects.count(), 0)
        self.assertEqual(ManchesterDiscriminator.objects.count(), 0)
        log = TerminologyImportLog.objects.filter(system="manchester_flowchart").latest("ran_at")
        self.assertTrue(log.dry_run)
        # 3 flowcharts + 7 discriminators created (rolled back, but counted).
        self.assertEqual(log.row_count_added, 10)

    def test_malformed_csv_aborts(self):
        with self.assertRaises(CommandError):
            _run(ImportManchester(), source=str(self.MALFORMED))
        self.assertEqual(ManchesterFlowchart.objects.count(), 0)
        self.assertEqual(ManchesterDiscriminator.objects.count(), 0)


# ─── terminology search registry ─────────────────────────────────────────────


class TestManchesterFlowchartSearch(TenantTestCase):
    def setUp(self):
        ManchesterFlowchart.objects.create(code="FL01", display="Dor torácica")
        ManchesterFlowchart.objects.create(code="FL99", display="Inativo antigo", active=False)

    def test_exact_code(self):
        results = search("manchester_flowchart", "FL01")
        self.assertEqual(results[0]["code"], "FL01")
        self.assertEqual(results[0]["system"], "manchester_flowchart")
        self.assertEqual(results[0]["display"], "Dor torácica")

    def test_accent_insensitive_display(self):
        codes = [r["code"] for r in search("manchester_flowchart", "toracica")]
        self.assertIn("FL01", codes)

    def test_active_only(self):
        codes = [r["code"] for r in search("manchester_flowchart", "FL99")]
        self.assertNotIn("FL99", codes)

    def test_unknown_system_still_raises(self):
        with self.assertRaises(UnknownTerminologySystem):
            search("bogus-manchester", "x")


# ─── RBAC on the DRF CRUD surface ────────────────────────────────────────────


class TestManchesterRBAC(TenantTestCase):
    def setUp(self):
        self.manage_role = Role.objects.create(
            name="recep_ps", permissions=["emergency.read", "emergency.manage"]
        )
        self.read_role = Role.objects.create(name="enf_class", permissions=["emergency.read"])
        self.none_role = Role.objects.create(name="sem_perm", permissions=[])
        self.manager = User.objects.create_user(
            email="mgr@t.com", password="pw", role=self.manage_role
        )
        self.reader = User.objects.create_user(
            email="rdr@t.com", password="pw", role=self.read_role
        )
        self.nobody = User.objects.create_user(
            email="none@t.com", password="pw", role=self.none_role
        )
        self.fc = ManchesterFlowchart.objects.create(code="FL01", display="Dor torácica")

    def _client(self, user):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user)
        return c

    def test_read_perm_lists_flowcharts(self):
        resp = self._client(self.reader).get(f"{BASE}/manchester-flowcharts/")
        self.assertEqual(resp.status_code, 200)

    def test_filter_discriminators_by_flowchart(self):
        ManchesterDiscriminator.objects.create(
            flowchart=self.fc, code="D001", name="A", acuity_level="verde"
        )
        resp = self._client(self.reader).get(
            f"{BASE}/manchester-discriminators/?flowchart={self.fc.pk}"
        )
        self.assertEqual(resp.status_code, 200)

    def test_no_perm_forbidden(self):
        resp = self._client(self.nobody).get(f"{BASE}/manchester-flowcharts/")
        self.assertEqual(resp.status_code, 403)

    def test_reader_cannot_write(self):
        resp = self._client(self.reader).post(
            f"{BASE}/manchester-flowcharts/",
            {"code": "FL02", "display": "Dispneia"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_manager_can_create_flowchart(self):
        resp = self._client(self.manager).post(
            f"{BASE}/manchester-flowcharts/",
            {"code": "FL02", "display": "Dispneia"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertTrue(ManchesterFlowchart.objects.filter(code="FL02").exists())

    def test_manager_can_create_discriminator(self):
        resp = self._client(self.manager).post(
            f"{BASE}/manchester-discriminators/",
            {
                "flowchart": str(self.fc.pk),
                "code": "D010",
                "name": "SatO2 < 95%",
                "acuity_level": "laranja",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        d = ManchesterDiscriminator.objects.get(code="D010")
        self.assertEqual(d.target_minutes, 10)
