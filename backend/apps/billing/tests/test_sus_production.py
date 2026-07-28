"""
S2 — Produção ambulatorial BPA + competência (Faturamento SUS).

Covers (all local, no network):
  * SusCompetencia model + lifecycle (unique per establishment+competencia,
    aberta→fechada via fechar()).
  * The bridge ``gerar_producao_ambulatorial``: creates BPA-I from SUS-coded
    (``sigtap`` set) ambulatorial EncounterProcedures whose encounter falls in the
    competência month, valued via ``(sigtap.valor_sa + sigtap.valor_sp) × qtd``,
    linking ``encounter_procedure`` for traceability. Idempotent (2nd run adds
    nothing). Rejected on a fechada competência.
  * Manual BPA-C entry (sigtap + cbo + idade + quantidade), valued via SIGTAP.
  * Cross-schema SIGTAP delete-protection: a SIGTAP referenced by a BPA line
    cannot be hard-deleted (ProtectedError via pre_delete signal).
  * RBAC: sus.read reads / sus.write writes, no-perm 403, gerar-producao on a
    fechada competência → 409.
"""

from __future__ import annotations

from decimal import Decimal

from django.db.models.deletion import ProtectedError
from django.utils import timezone
from rest_framework.test import APIClient

from apps.billing.services.sus_production import gerar_producao_ambulatorial
from apps.billing.sus_models import BpaConsolidado, BpaIndividualizado, SusCompetencia
from apps.core.models import CBOCode, Role, TUSSCode, User
from apps.core.sigtap_catalog_models import SIGTAPProcedure
from apps.emr.models import Encounter, EncounterProcedure, Patient, Professional
from apps.organization.models import Facility, LegalEntity
from apps.test_utils import TenantTestCase

BASE = "/api/v1/billing"


class SusProductionTestBase(TenantTestCase):
    def setUp(self):
        self.write_role = Role.objects.create(
            name="faturista_sus", permissions=["sus.read", "sus.write"]
        )
        self.read_role = Role.objects.create(name="leitor_sus", permissions=["sus.read"])
        self.none_role = Role.objects.create(name="sem_perm", permissions=[])
        self.writer = User.objects.create_user(email="w@t.com", password="pw", role=self.write_role)
        self.reader = User.objects.create_user(email="r@t.com", password="pw", role=self.read_role)
        self.nobody = User.objects.create_user(email="n@t.com", password="pw", role=self.none_role)

        self.legal = LegalEntity.objects.create(code="LE1", name="Rede SUS")
        self.facility = Facility.objects.create(
            code="FAC1", name="UBS Central", legal_entity=self.legal
        )

        self.cbo = CBOCode.objects.create(code="225125", display="Médico clínico", family="2251")
        self.tuss = TUSSCode.objects.create(
            code="10101012",
            description="Consulta em consultório",
            group="procedimento",
            version="2024-01",
        )

        # Consulta médica atenção básica (BPA-I) — valor SA + SP.
        self.sigtap = SIGTAPProcedure.objects.create(
            code="0301010010",
            display="Consulta médica atenção básica",
            instrumento_registro="bpa_i",
            complexidade="atencao_basica",
            valor_sa=Decimal("10.00"),
            valor_sp=Decimal("5.00"),
        )
        # BPA-C sem paciente.
        self.sigtap_c = SIGTAPProcedure.objects.create(
            code="0301010028",
            display="Curativo grau I",
            instrumento_registro="bpa_c",
            complexidade="atencao_basica",
            valor_sa=Decimal("2.00"),
            valor_sp=Decimal("0.00"),
        )

        self.prof = Professional.objects.create(
            user=self.writer,
            council_type="CRM",
            council_number="12345",
            council_state="SP",
            cbo=self.cbo,
            cns="700000000000001",
        )
        self.patient = Patient.objects.create(
            full_name="João Paciente",
            birth_date="1980-01-01",
            gender="M",
            cpf="52998224725",
            cns="700000000000009",
        )

    def _client(self, user):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user)
        return c

    @staticmethod
    def _rows(resp):
        return resp.data["results"] if "results" in resp.data else resp.data

    def _competencia(self, competencia="2026-07", status="aberta"):
        return SusCompetencia.objects.create(
            establishment=self.facility,
            competencia=competencia,
            status=status,
            created_by=self.writer,
        )

    def _encounter_with_procedure(self, *, competencia="2026-07", sigtap=None, quantity="1"):
        """An ambulatorial encounter in the given competência month with a SUS-coded procedure."""
        year, month = (int(x) for x in competencia.split("-"))
        enc = Encounter.objects.create(
            patient=self.patient,
            professional=self.prof,
            encounter_type="ambulatorial",
            encounter_date=timezone.make_aware(timezone.datetime(year, month, 15, 10, 0)),
        )
        return EncounterProcedure.objects.create(
            encounter=enc,
            tuss_code=self.tuss,
            sigtap=sigtap or self.sigtap,
            quantity=Decimal(quantity),
            performed_by=self.prof,
        )


# ─── Competência model + lifecycle ────────────────────────────────────────────


class TestSusCompetencia(SusProductionTestBase):
    def test_defaults_aberta(self):
        comp = self._competencia()
        comp.refresh_from_db()
        self.assertEqual(comp.status, SusCompetencia.Status.ABERTA)
        self.assertEqual(comp.establishment_id, self.facility.id)

    def test_unique_per_establishment_competencia(self):
        from django.db import IntegrityError, transaction

        self._competencia()
        with transaction.atomic(), self.assertRaises(IntegrityError):
            SusCompetencia.objects.create(
                establishment=self.facility, competencia="2026-07", created_by=self.writer
            )

    def test_fechar_transitions_aberta_to_fechada(self):
        comp = self._competencia()
        comp.fechar()
        comp.refresh_from_db()
        self.assertEqual(comp.status, SusCompetencia.Status.FECHADA)


# ─── Bridge: gerar_producao_ambulatorial ──────────────────────────────────────


class TestGerarProducao(SusProductionTestBase):
    def test_creates_bpa_i_from_sus_coded_ambulatorial(self):
        comp = self._competencia()
        ep = self._encounter_with_procedure(quantity="2")
        summary = gerar_producao_ambulatorial(comp, actor=self.writer)
        self.assertEqual(summary["bpa_i_count"], 1)
        # (10.00 + 5.00) × 2 = 30.00
        self.assertEqual(summary["total_valor"], Decimal("30.00"))
        line = BpaIndividualizado.objects.get(competencia=comp)
        self.assertEqual(line.valor, Decimal("30.00"))
        self.assertEqual(line.quantidade, 2)
        self.assertEqual(line.cns, "700000000000009")
        self.assertEqual(line.encounter_procedure_id, ep.id)
        self.assertEqual(line.sigtap_id, self.sigtap.id)

    def test_idempotent_second_run_adds_nothing(self):
        comp = self._competencia()
        self._encounter_with_procedure()
        gerar_producao_ambulatorial(comp, actor=self.writer)
        summary2 = gerar_producao_ambulatorial(comp, actor=self.writer)
        self.assertEqual(summary2["bpa_i_count"], 0)
        self.assertEqual(BpaIndividualizado.objects.filter(competencia=comp).count(), 1)

    def test_skips_non_ambulatorial_and_uncoded(self):
        comp = self._competencia()
        # internacao encounter → skipped
        enc = Encounter.objects.create(
            patient=self.patient,
            professional=self.prof,
            encounter_type="internacao",
            encounter_date=timezone.make_aware(timezone.datetime(2026, 7, 10, 9, 0)),
        )
        EncounterProcedure.objects.create(
            encounter=enc, tuss_code=self.tuss, sigtap=self.sigtap, quantity=Decimal("1")
        )
        # ambulatorial but NOT SUS-coded (sigtap null) → skipped
        enc2 = Encounter.objects.create(
            patient=self.patient,
            professional=self.prof,
            encounter_type="ambulatorial",
            encounter_date=timezone.make_aware(timezone.datetime(2026, 7, 11, 9, 0)),
        )
        EncounterProcedure.objects.create(
            encounter=enc2, tuss_code=self.tuss, sigtap=None, quantity=Decimal("1")
        )
        summary = gerar_producao_ambulatorial(comp, actor=self.writer)
        self.assertEqual(summary["bpa_i_count"], 0)

    def test_skips_procedure_outside_competencia_month(self):
        comp = self._competencia("2026-07")
        self._encounter_with_procedure(competencia="2026-08")
        summary = gerar_producao_ambulatorial(comp, actor=self.writer)
        self.assertEqual(summary["bpa_i_count"], 0)

    def test_rejects_on_fechada_competencia(self):
        from django.core.exceptions import ValidationError as DjangoValidationError

        comp = self._competencia(status="fechada")
        self._encounter_with_procedure()
        with self.assertRaises(DjangoValidationError):
            gerar_producao_ambulatorial(comp, actor=self.writer)


# ─── SIGTAP cross-schema delete-protection ────────────────────────────────────


class TestSigtapDeleteProtection(SusProductionTestBase):
    def test_sigtap_referenced_by_bpa_c_cannot_be_deleted(self):
        comp = self._competencia()
        BpaConsolidado.objects.create(
            competencia=comp,
            sigtap=self.sigtap_c,
            cbo=self.cbo,
            idade=40,
            quantidade=3,
            valor=Decimal("6.00"),
        )
        with self.assertRaises(ProtectedError):
            self.sigtap_c.delete()

    def test_sigtap_referenced_by_bpa_i_cannot_be_deleted(self):
        comp = self._competencia()
        self._encounter_with_procedure()
        gerar_producao_ambulatorial(comp, actor=self.writer)
        with self.assertRaises(ProtectedError):
            self.sigtap.delete()


# ─── Endpoints ────────────────────────────────────────────────────────────────


class TestCompetenciaEndpoints(SusProductionTestBase):
    def test_writer_creates_competencia(self):
        resp = self._client(self.writer).post(
            f"{BASE}/sus-competencias/",
            {"establishment": self.facility.id, "competencia": "2026-07"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        comp = SusCompetencia.objects.get(competencia="2026-07")
        self.assertEqual(comp.status, "aberta")
        self.assertEqual(comp.created_by_id, self.writer.id)

    def test_reader_cannot_create(self):
        resp = self._client(self.reader).post(
            f"{BASE}/sus-competencias/",
            {"establishment": self.facility.id, "competencia": "2026-07"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_no_perm_forbidden_list(self):
        resp = self._client(self.nobody).get(f"{BASE}/sus-competencias/")
        self.assertEqual(resp.status_code, 403)

    def test_list_filters_by_establishment_and_status(self):
        self._competencia("2026-07")
        self._competencia("2026-08", status="fechada")
        resp = self._client(self.reader).get(
            f"{BASE}/sus-competencias/?establishment={self.facility.id}&status=fechada"
        )
        self.assertEqual(resp.status_code, 200)
        rows = self._rows(resp)
        self.assertEqual([r["competencia"] for r in rows], ["2026-08"])

    def test_gerar_producao_endpoint(self):
        comp = self._competencia()
        self._encounter_with_procedure()
        resp = self._client(self.writer).post(f"{BASE}/sus-competencias/{comp.id}/gerar-producao/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["bpa_i_count"], 1)
        self.assertEqual(BpaIndividualizado.objects.filter(competencia=comp).count(), 1)

    def test_gerar_producao_on_fechada_returns_409(self):
        comp = self._competencia(status="fechada")
        self._encounter_with_procedure()
        resp = self._client(self.writer).post(f"{BASE}/sus-competencias/{comp.id}/gerar-producao/")
        self.assertEqual(resp.status_code, 409, resp.content)

    def test_fechar_endpoint(self):
        comp = self._competencia()
        resp = self._client(self.writer).post(f"{BASE}/sus-competencias/{comp.id}/fechar/")
        self.assertEqual(resp.status_code, 200, resp.content)
        comp.refresh_from_db()
        self.assertEqual(comp.status, "fechada")

    def test_fechar_requires_write(self):
        comp = self._competencia()
        resp = self._client(self.reader).post(f"{BASE}/sus-competencias/{comp.id}/fechar/")
        self.assertEqual(resp.status_code, 403)


class TestBpaEndpoints(SusProductionTestBase):
    def test_manual_bpa_c_create(self):
        comp = self._competencia()
        resp = self._client(self.writer).post(
            f"{BASE}/bpa-consolidado/",
            {
                "competencia": comp.id,
                "sigtap": self.sigtap_c.id,
                "cbo": self.cbo.id,
                "idade": 40,
                "quantidade": 3,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        line = BpaConsolidado.objects.get(competencia=comp)
        # (2.00 + 0.00) × 3 = 6.00
        self.assertEqual(line.valor, Decimal("6.00"))
        self.assertEqual(line.quantidade, 3)

    def test_bpa_c_list_filter_by_competencia(self):
        comp = self._competencia("2026-07")
        comp2 = self._competencia("2026-08")
        BpaConsolidado.objects.create(
            competencia=comp,
            sigtap=self.sigtap_c,
            cbo=self.cbo,
            idade=40,
            quantidade=1,
            valor=Decimal("2.00"),
        )
        BpaConsolidado.objects.create(
            competencia=comp2,
            sigtap=self.sigtap_c,
            cbo=self.cbo,
            idade=30,
            quantidade=1,
            valor=Decimal("2.00"),
        )
        resp = self._client(self.reader).get(f"{BASE}/bpa-consolidado/?competencia={comp.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(self._rows(resp)), 1)

    def test_bpa_i_list_read_only(self):
        comp = self._competencia()
        self._encounter_with_procedure()
        gerar_producao_ambulatorial(comp, actor=self.writer)
        resp = self._client(self.reader).get(f"{BASE}/bpa-individualizado/?competencia={comp.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(self._rows(resp)), 1)

    def test_bpa_c_reader_cannot_create(self):
        comp = self._competencia()
        resp = self._client(self.reader).post(
            f"{BASE}/bpa-consolidado/",
            {
                "competencia": comp.id,
                "sigtap": self.sigtap_c.id,
                "cbo": self.cbo.id,
                "idade": 40,
                "quantidade": 1,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 403)
