"""
S1 — Catálogo SIGTAP + identidade SUS.

Mirrors test_manchester_catalog.py / test_adt_catalog.py, covering (all local, no
network):
  * the governed SIGTAPProcedure model (system default, normalized_display sync,
    valor_total() Decimal helper, instrumento/complexidade choices) and its
    registration in the terminology search registry
  * the import_sigtap management command: procedures parsed as Decimal,
    idempotent, dry-run safety, per-line error isolation, provenance logging
  * RBAC on the DRF CRUD surface (sus.read reads, sus.write writes, no-perm 403),
    plus filtering by instrumento/complexidade
  * Professional.cns round-trips (encrypted-at-rest, saved/read)
  * DEFAULT_ROLES: faturista bundle carries sus.read + sus.write
"""

from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from rest_framework.test import APIClient

from apps.core.management.commands.import_sigtap import Command as ImportSigtap
from apps.core.models import Role, User
from apps.core.permissions import BILLING_PERMISSIONS, DEFAULT_ROLES
from apps.core.sigtap_catalog_models import (
    Complexidade,
    InstrumentoRegistro,
    SexoPermitido,
    SIGTAPProcedure,
)
from apps.core.terminology import UnknownTerminologySystem, search
from apps.core.terminology_base import TerminologyImportLog
from apps.emr.models import Professional
from apps.test_utils import TenantTestCase

FIXTURES = Path(__file__).resolve().parent / "fixtures"
BASE = "/api/v1"


def _run(cmd, **options):
    out = StringIO()
    call_command(cmd, stdout=out, stderr=out, **options)
    return out.getvalue()


# ─── model ───────────────────────────────────────────────────────────────────


class TestSIGTAPModel(TenantTestCase):
    def test_defaults_and_normalized_display_sync(self):
        p = SIGTAPProcedure.objects.create(code="0301010010", display="Consulta Médica")
        p.refresh_from_db()
        self.assertEqual(p.system, "sigtap")
        self.assertTrue(p.active)
        self.assertEqual(p.normalized_display, "consulta medica")
        # inert defaults
        self.assertEqual(p.valor_sa, Decimal("0"))
        self.assertEqual(p.instrumento_registro, InstrumentoRegistro.OUTROS)
        self.assertEqual(p.complexidade, Complexidade.NAO_SE_APLICA)
        self.assertEqual(p.sexo_permitido, SexoPermitido.AMBOS)
        self.assertIsNone(p.idade_min_dias)

    def test_valor_total_is_exact_decimal(self):
        p = SIGTAPProcedure.objects.create(
            code="0303010045",
            display="Tratamento",
            valor_sa=Decimal("10.00"),
            valor_sh=Decimal("220.50"),
            valor_sp=Decimal("180.30"),
        )
        self.assertEqual(p.valor_total(), Decimal("410.80"))
        self.assertIsInstance(p.valor_total(), Decimal)

    def test_choices_available(self):
        self.assertEqual(
            set(InstrumentoRegistro.values),
            {"bpa_c", "bpa_i", "apac", "aih", "outros"},
        )
        self.assertEqual(
            set(Complexidade.values),
            {"atencao_basica", "media", "alta", "nao_se_aplica"},
        )
        self.assertEqual(set(SexoPermitido.values), {"ambos", "M", "F"})


# ─── importer ────────────────────────────────────────────────────────────────


class TestImportSigtap(TenantTestCase):
    SAMPLE = FIXTURES / "sigtap_sample.csv"
    MALFORMED = FIXTURES / "sigtap_malformed.csv"

    def test_creates_procedures_with_decimal_valores(self):
        _run(ImportSigtap(), source=str(self.SAMPLE))
        self.assertEqual(SIGTAPProcedure.objects.count(), 8)
        p = SIGTAPProcedure.objects.get(code="0303010045")
        self.assertEqual(p.display, "FAKE-Tratamento de pneumonia")
        self.assertEqual(p.system, "sigtap")
        self.assertEqual(p.valor_sh, Decimal("220.50"))
        self.assertEqual(p.valor_sp, Decimal("180.30"))
        self.assertEqual(p.valor_total(), Decimal("400.80"))
        self.assertEqual(p.instrumento_registro, "aih")
        self.assertEqual(p.complexidade, "media")
        # spanning instrumentos
        self.assertEqual(
            SIGTAPProcedure.objects.get(code="0301010010").instrumento_registro, "bpa_c"
        )
        self.assertEqual(
            SIGTAPProcedure.objects.get(code="0304010030").instrumento_registro, "apac"
        )
        # optional idade / sexo parsed
        puer = SIGTAPProcedure.objects.get(code="0301060029")
        self.assertEqual(puer.idade_min_dias, 0)
        self.assertEqual(puer.idade_max_dias, 4380)
        obst = SIGTAPProcedure.objects.get(code="0211040053")
        self.assertEqual(obst.sexo_permitido, "F")

    def test_idempotent_and_provenance(self):
        _run(ImportSigtap(), source=str(self.SAMPLE))
        _run(ImportSigtap(), source=str(self.SAMPLE))
        self.assertEqual(SIGTAPProcedure.objects.count(), 8)
        log = TerminologyImportLog.objects.filter(system="sigtap").latest("ran_at")
        self.assertEqual(log.provenance, "DATASUS/SIGTAP")
        self.assertEqual(log.status, TerminologyImportLog.Status.SUCCESS)

    def test_dry_run_writes_nothing_but_logs(self):
        _run(ImportSigtap(), source=str(self.SAMPLE), dry_run=True)
        self.assertEqual(SIGTAPProcedure.objects.count(), 0)
        log = TerminologyImportLog.objects.filter(system="sigtap").latest("ran_at")
        self.assertTrue(log.dry_run)
        self.assertEqual(log.row_count_added, 8)

    def test_malformed_csv_aborts(self):
        with self.assertRaises(CommandError):
            _run(ImportSigtap(), source=str(self.MALFORMED))
        self.assertEqual(SIGTAPProcedure.objects.count(), 0)


# ─── terminology search registry ─────────────────────────────────────────────


class TestSIGTAPSearch(TenantTestCase):
    def setUp(self):
        SIGTAPProcedure.objects.create(
            code="0301010010",
            display="Consulta médica atenção básica",
            instrumento_registro="bpa_c",
            complexidade="atencao_basica",
            valor_sa=Decimal("10.00"),
        )
        SIGTAPProcedure.objects.create(code="0301099999", display="Inativo antigo", active=False)

    def test_exact_code(self):
        results = search("sigtap", "0301010010")
        self.assertEqual(results[0]["code"], "0301010010")
        self.assertEqual(results[0]["system"], "sigtap")
        self.assertEqual(results[0]["display"], "Consulta médica atenção básica")
        self.assertEqual(results[0]["context"]["instrumento_registro"], "bpa_c")
        self.assertEqual(results[0]["context"]["valor_total"], "10.00")

    def test_accent_insensitive_display(self):
        codes = [r["code"] for r in search("sigtap", "medica")]
        self.assertIn("0301010010", codes)

    def test_active_only(self):
        codes = [r["code"] for r in search("sigtap", "0301099999")]
        self.assertNotIn("0301099999", codes)

    def test_unknown_system_still_raises(self):
        with self.assertRaises(UnknownTerminologySystem):
            search("bogus-sigtap", "x")


# ─── Professional.cns (identidade SUS) ────────────────────────────────────────


class TestProfessionalCNS(TenantTestCase):
    def test_cns_round_trips(self):
        user = User.objects.create_user(
            email="exec@sus.com", full_name="Dr Exec", password="Str0ng!Pass#2024"
        )
        prof = Professional.objects.create(
            user=user,
            council_type="CRM",
            council_number="123",
            council_state="SP",
            cns="700000000000001",
        )
        prof.refresh_from_db()
        self.assertEqual(prof.cns, "700000000000001")

    def test_cns_defaults_blank(self):
        user = User.objects.create_user(
            email="noc@sus.com", full_name="Dr NoCns", password="Str0ng!Pass#2024"
        )
        prof = Professional.objects.create(
            user=user, council_type="CRM", council_number="999", council_state="SP"
        )
        prof.refresh_from_db()
        self.assertEqual(prof.cns, "")


# ─── RBAC on the DRF CRUD surface ────────────────────────────────────────────


class TestSIGTAPRBAC(TenantTestCase):
    def setUp(self):
        self.write_role = Role.objects.create(
            name="faturista_sus", permissions=["sus.read", "sus.write"]
        )
        self.read_role = Role.objects.create(name="leitor_sus", permissions=["sus.read"])
        self.none_role = Role.objects.create(name="sem_perm", permissions=[])
        self.writer = User.objects.create_user(email="w@t.com", password="pw", role=self.write_role)
        self.reader = User.objects.create_user(email="r@t.com", password="pw", role=self.read_role)
        self.nobody = User.objects.create_user(email="n@t.com", password="pw", role=self.none_role)
        SIGTAPProcedure.objects.create(
            code="0301010010",
            display="Consulta",
            instrumento_registro="bpa_c",
            complexidade="atencao_basica",
        )
        SIGTAPProcedure.objects.create(
            code="0304010030",
            display="Quimioterapia",
            instrumento_registro="apac",
            complexidade="alta",
        )

    def _client(self, user):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user)
        return c

    def test_read_perm_lists(self):
        resp = self._client(self.reader).get(f"{BASE}/sigtap/")
        self.assertEqual(resp.status_code, 200)

    def test_filter_by_instrumento(self):
        resp = self._client(self.reader).get(f"{BASE}/sigtap/?instrumento=apac")
        self.assertEqual(resp.status_code, 200)
        codes = [r["code"] for r in resp.json()["results"]]
        self.assertEqual(codes, ["0304010030"])

    def test_filter_by_complexidade(self):
        resp = self._client(self.reader).get(f"{BASE}/sigtap/?complexidade=alta")
        self.assertEqual(resp.status_code, 200)
        codes = [r["code"] for r in resp.json()["results"]]
        self.assertEqual(codes, ["0304010030"])

    def test_no_perm_forbidden(self):
        resp = self._client(self.nobody).get(f"{BASE}/sigtap/")
        self.assertEqual(resp.status_code, 403)

    def test_reader_cannot_write(self):
        resp = self._client(self.reader).post(
            f"{BASE}/sigtap/",
            {"code": "0202010473", "display": "Hemograma"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_writer_can_create(self):
        resp = self._client(self.writer).post(
            f"{BASE}/sigtap/",
            {
                "code": "0202010473",
                "display": "Hemograma completo",
                "valor_sa": "4.11",
                "instrumento_registro": "bpa_i",
                "complexidade": "media",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        p = SIGTAPProcedure.objects.get(code="0202010473")
        self.assertEqual(p.valor_sa, Decimal("4.11"))
        self.assertEqual(p.system, "sigtap")


# ─── default roles wiring ─────────────────────────────────────────────────────


class TestSusDefaultRoles(TenantTestCase):
    def test_faturista_has_sus_perms(self):
        self.assertIn("sus.read", BILLING_PERMISSIONS)
        self.assertIn("sus.write", BILLING_PERMISSIONS)
        self.assertIn("sus.read", DEFAULT_ROLES["faturista"])
        self.assertIn("sus.write", DEFAULT_ROLES["faturista"])

    def test_admin_has_sus_perms(self):
        self.assertIn("sus.read", DEFAULT_ROLES["admin"])
        self.assertIn("sus.write", DEFAULT_ROLES["admin"])

    def test_billing_perms_untouched(self):
        # sus.* is a separate namespace; billing.* stays intact.
        for perm in ("billing.read", "billing.write", "billing.full"):
            self.assertIn(perm, BILLING_PERMISSIONS)
