"""
S3 — APAC + remessa DATASUS BPA-Magnético/APAC (Faturamento SUS).

Covers (all local, no network):
  * ApacAutorizacao model + unique numero_apac; secondary procedures;
    cross-schema SIGTAP delete-protection for APAC (principal + secundário).
  * APAC endpoints: CRUD gated sus.read/write (?competencia= / ?apac= filters).
  * Remessa BPA-Magnético (positional): header + one detail line per BPA row,
    each the documented fixed WIDTH; header carries competência AAAAMM + count;
    SIGTAP at the documented offset; CNS/CID present on BPA-I lines.
  * Remessa APAC (positional): header + APAC line + secundário line, fixed widths.
  * exportar lifecycle: requires fechada (aberta → 409), marks exportada, returns
    the stored text; gated sus.export (sus.write-but-not-export → 403).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db.models.deletion import ProtectedError
from rest_framework.test import APIClient

from apps.billing.services import sus_remessa
from apps.billing.services.sus_remessa import (
    APAC_SEC_WIDTH,
    APAC_WIDTH,
    BPA_C_SIGTAP,
    BPA_C_WIDTH,
    BPA_I_CID,
    BPA_I_CNS,
    BPA_I_SIGTAP,
    BPA_I_WIDTH,
    HEADER_COMPETENCIA,
    HEADER_NUM_LINHAS,
    HEADER_WIDTH,
    LINE_TERMINATOR,
    gerar_remessa_apac,
    gerar_remessa_bpa,
)
from apps.billing.sus_models import (
    ApacAutorizacao,
    ApacProcedimentoSecundario,
    BpaConsolidado,
    SusCompetencia,
)
from apps.core.models import CBOCode, Role, TUSSCode, User
from apps.core.sigtap_catalog_models import SIGTAPProcedure
from apps.emr.models import Patient, Professional
from apps.organization.models import Facility, LegalEntity
from apps.test_utils import TenantTestCase

BASE = "/api/v1/billing"


class SusRemessaTestBase(TenantTestCase):
    def setUp(self):
        self.write_role = Role.objects.create(
            name="faturista_sus", permissions=["sus.read", "sus.write"]
        )
        self.export_role = Role.objects.create(
            name="faturista_export", permissions=["sus.read", "sus.write", "sus.export"]
        )
        self.read_role = Role.objects.create(name="leitor_sus", permissions=["sus.read"])
        self.writer = User.objects.create_user(email="w@t.com", password="pw", role=self.write_role)
        self.exporter = User.objects.create_user(
            email="e@t.com", password="pw", role=self.export_role
        )
        self.reader = User.objects.create_user(email="r@t.com", password="pw", role=self.read_role)

        self.legal = LegalEntity.objects.create(code="LE1", name="Rede SUS")
        # legacy_cnes_text supplies the 7-digit CNES used in the remessa header.
        self.facility = Facility.objects.create(
            code="FAC1", name="UBS Central", legal_entity=self.legal, legacy_cnes_text="1234567"
        )

        self.cbo = CBOCode.objects.create(code="225125", display="Médico clínico", family="2251")
        self.tuss = TUSSCode.objects.create(
            code="10101012", description="Consulta", group="procedimento", version="2024-01"
        )
        self.sigtap = SIGTAPProcedure.objects.create(
            code="0301010010",
            display="Consulta médica atenção básica",
            instrumento_registro="bpa_i",
            complexidade="atencao_basica",
            valor_sa=Decimal("10.00"),
            valor_sp=Decimal("5.00"),
        )
        self.sigtap_c = SIGTAPProcedure.objects.create(
            code="0301010028",
            display="Curativo grau I",
            instrumento_registro="bpa_c",
            valor_sa=Decimal("2.00"),
            valor_sp=Decimal("0.00"),
        )
        self.sigtap_apac = SIGTAPProcedure.objects.create(
            code="0304010030",
            display="Quimioterapia",
            instrumento_registro="apac",
            complexidade="alta",
            valor_sa=Decimal("500.00"),
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

    def _bpa_c(self, comp, quantidade=3):
        return BpaConsolidado.objects.create(
            competencia=comp,
            sigtap=self.sigtap_c,
            cbo=self.cbo,
            idade=40,
            quantidade=quantidade,
            valor=Decimal("2.00") * quantidade,
        )

    def _apac(self, comp, numero="1234567890123"):
        return ApacAutorizacao.objects.create(
            competencia=comp,
            numero_apac=numero,
            validade_inicio=date(2026, 7, 1),
            validade_fim=date(2026, 9, 30),
            procedimento_principal=self.sigtap_apac,
            cid_principal="C509",
            patient=self.patient,
            cns="700000000000009",
            professional_solicitante=self.prof,
            professional_executante=self.prof,
            valor=Decimal("500.00"),
        )


# ─── APAC model ───────────────────────────────────────────────────────────────


class TestApacModel(SusRemessaTestBase):
    def test_create_apac_with_secondary(self):
        comp = self._competencia()
        apac = self._apac(comp)
        sec = ApacProcedimentoSecundario.objects.create(
            apac=apac, sigtap=self.sigtap_c, quantidade=2, valor=Decimal("4.00")
        )
        self.assertEqual(apac.competencia_id, comp.id)
        self.assertEqual(list(comp.apacs.all()), [apac])
        self.assertEqual(list(apac.procedimentos_secundarios.all()), [sec])

    def test_numero_apac_unique(self):
        from django.db import IntegrityError, transaction

        comp = self._competencia()
        self._apac(comp, numero="9999999999999")
        with transaction.atomic(), self.assertRaises(IntegrityError):
            self._apac(comp, numero="9999999999999")


# ─── APAC cross-schema SIGTAP delete-protection ───────────────────────────────


class TestApacSigtapProtection(SusRemessaTestBase):
    def test_principal_sigtap_cannot_be_deleted(self):
        comp = self._competencia()
        self._apac(comp)
        with self.assertRaises(ProtectedError):
            self.sigtap_apac.delete()

    def test_secondary_sigtap_cannot_be_deleted(self):
        comp = self._competencia()
        apac = self._apac(comp)
        ApacProcedimentoSecundario.objects.create(
            apac=apac, sigtap=self.sigtap_c, quantidade=1, valor=Decimal("2.00")
        )
        with self.assertRaises(ProtectedError):
            self.sigtap_c.delete()


# ─── APAC endpoints ───────────────────────────────────────────────────────────


class TestApacEndpoints(SusRemessaTestBase):
    def test_writer_creates_apac(self):
        comp = self._competencia()
        resp = self._client(self.writer).post(
            f"{BASE}/apac-autorizacoes/",
            {
                "competencia": comp.id,
                "numero_apac": "1111111111111",
                "validade_inicio": "2026-07-01",
                "validade_fim": "2026-09-30",
                "procedimento_principal": self.sigtap_apac.id,
                "cid_principal": "C509",
                "patient": self.patient.id,
                "valor": "500.00",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        apac = ApacAutorizacao.objects.get(numero_apac="1111111111111")
        self.assertEqual(apac.created_by_id, self.writer.id)
        # cns snapshotted from patient when omitted
        self.assertEqual(apac.cns, "700000000000009")

    def test_reader_cannot_create_apac(self):
        comp = self._competencia()
        resp = self._client(self.reader).post(
            f"{BASE}/apac-autorizacoes/",
            {
                "competencia": comp.id,
                "numero_apac": "2222222222222",
                "validade_inicio": "2026-07-01",
                "validade_fim": "2026-09-30",
                "procedimento_principal": self.sigtap_apac.id,
                "patient": self.patient.id,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_list_filters_by_competencia(self):
        comp = self._competencia("2026-07")
        comp2 = self._competencia("2026-08")
        self._apac(comp, numero="3333333333333")
        self._apac(comp2, numero="4444444444444")
        resp = self._client(self.reader).get(f"{BASE}/apac-autorizacoes/?competencia={comp.id}")
        self.assertEqual(resp.status_code, 200)
        rows = self._rows(resp)
        self.assertEqual([r["numero_apac"] for r in rows], ["3333333333333"])

    def test_secundario_create_computes_valor_and_filters_by_apac(self):
        comp = self._competencia()
        apac = self._apac(comp)
        resp = self._client(self.writer).post(
            f"{BASE}/apac-secundarios/",
            {"apac": apac.id, "sigtap": self.sigtap_c.id, "quantidade": 3},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        sec = ApacProcedimentoSecundario.objects.get(apac=apac)
        # (2.00 + 0.00) × 3 = 6.00
        self.assertEqual(sec.valor, Decimal("6.00"))
        resp = self._client(self.reader).get(f"{BASE}/apac-secundarios/?apac={apac.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(self._rows(resp)), 1)


# ─── Remessa BPA-Magnético (positional) ───────────────────────────────────────


class TestRemessaBpa(SusRemessaTestBase):
    def _lines(self, content):
        return content.split(LINE_TERMINATOR)

    def test_header_plus_one_line_per_row_with_fixed_widths(self):
        comp = self._competencia()
        self._bpa_c(comp, quantidade=3)  # two manual BPA-C rows
        self._bpa_c(comp, quantidade=1)
        content = gerar_remessa_bpa(comp)
        lines = self._lines(content)
        # header + 2 BPA-C lines
        self.assertEqual(len(lines), 3)
        header, *detail = lines
        self.assertEqual(len(header), HEADER_WIDTH)
        for line in detail:
            self.assertTrue(line.startswith("02"))
            self.assertEqual(len(line), BPA_C_WIDTH)

    def test_header_carries_competencia_and_count(self):
        comp = self._competencia("2026-07")
        self._bpa_c(comp)
        content = gerar_remessa_bpa(comp)
        header = self._lines(content)[0]
        off, w = HEADER_COMPETENCIA
        self.assertEqual(header[off : off + w], "202607")
        off, w = HEADER_NUM_LINHAS
        self.assertEqual(header[off : off + w], "000001")

    def test_sigtap_at_documented_offset_bpa_c(self):
        comp = self._competencia()
        self._bpa_c(comp)
        content = gerar_remessa_bpa(comp)
        detail = self._lines(content)[1]
        off, w = BPA_C_SIGTAP
        self.assertEqual(detail[off : off + w], "0301010028")

    def test_bpa_i_line_carries_cns_and_cid_at_offsets(self):
        comp = self._competencia()
        # Build a BPA-I directly (bridge path is covered in test_sus_production).
        from apps.billing.sus_models import BpaIndividualizado

        BpaIndividualizado.objects.create(
            competencia=comp,
            sigtap=self.sigtap,
            cbo=self.cbo,
            patient=self.patient,
            cns="700000000000009",
            cid="J45",
            professional=self.prof,
            quantidade=2,
            valor=Decimal("30.00"),
        )
        content = gerar_remessa_bpa(comp)
        lines = self._lines(content)
        # header + one BPA-I line
        self.assertEqual(len(lines), 2)
        line = lines[1]
        self.assertTrue(line.startswith("03"))
        self.assertEqual(len(line), BPA_I_WIDTH)
        off, w = BPA_I_SIGTAP
        self.assertEqual(line[off : off + w], "0301010010")
        off, w = BPA_I_CNS
        self.assertEqual(line[off : off + w], "700000000000009")
        off, w = BPA_I_CID
        self.assertEqual(line[off : off + w], "J45 ")  # left-justified, space-padded to 4

    def test_deterministic_zero_rows_header_only(self):
        comp = self._competencia()
        content = gerar_remessa_bpa(comp)
        lines = self._lines(content)
        self.assertEqual(len(lines), 1)
        self.assertEqual(len(lines[0]), HEADER_WIDTH)

    def test_control_chars_in_cns_cid_cannot_inject_a_line(self):
        # CSO 2026-07-28 finding #1: a staff-entered CNS/CID with a CR/LF must not
        # inject a forged line into the fixed-width DATASUS remessa.
        from apps.billing.sus_models import BpaIndividualizado

        comp = self._competencia()
        BpaIndividualizado.objects.create(
            competencia=comp,
            sigtap=self.sigtap,
            cbo=self.cbo,
            patient=self.patient,
            cns="7000\r\n03999",
            cid="J4\n9",
            professional=self.prof,
            quantidade=1,
            valor=Decimal("10.00"),
        )
        content = gerar_remessa_bpa(comp)
        lines = self._lines(content)
        # Still exactly header + 1 detail line (no injected line), and the detail
        # line is exactly BPA_I_WIDTH with the control chars scrubbed.
        self.assertEqual(len(lines), 2)
        self.assertEqual(len(lines[1]), BPA_I_WIDTH)
        self.assertNotIn("\n", lines[1])
        self.assertNotIn("\r", lines[1])


# ─── Remessa APAC (positional) ────────────────────────────────────────────────


class TestRemessaApac(SusRemessaTestBase):
    def _lines(self, content):
        return content.split(LINE_TERMINATOR)

    def test_header_plus_apac_and_secondary_lines(self):
        comp = self._competencia()
        apac = self._apac(comp)
        ApacProcedimentoSecundario.objects.create(
            apac=apac, sigtap=self.sigtap_c, quantidade=2, valor=Decimal("4.00")
        )
        content = gerar_remessa_apac(comp)
        lines = self._lines(content)
        # header + APAC line + secundário line
        self.assertEqual(len(lines), 3)
        header, apac_line, sec_line = lines
        self.assertEqual(len(header), HEADER_WIDTH)
        self.assertTrue(apac_line.startswith("11"))
        self.assertEqual(len(apac_line), APAC_WIDTH)
        self.assertTrue(sec_line.startswith("12"))
        self.assertEqual(len(sec_line), APAC_SEC_WIDTH)

    def test_apac_line_carries_numero_and_sigtap(self):
        comp = self._competencia()
        self._apac(comp, numero="1234567890123")
        content = gerar_remessa_apac(comp)
        apac_line = self._lines(content)[1]
        off, w = sus_remessa.APAC_NUMERO
        self.assertEqual(apac_line[off : off + w], "1234567890123")
        off, w = sus_remessa.APAC_SIGTAP
        self.assertEqual(apac_line[off : off + w], "0304010030")


# ─── Export lifecycle ─────────────────────────────────────────────────────────


class TestExportLifecycle(SusRemessaTestBase):
    def test_exportar_requires_fechada_aberta_returns_409(self):
        comp = self._competencia(status="aberta")
        self._bpa_c(comp)
        resp = self._client(self.exporter).post(f"{BASE}/sus-competencias/{comp.id}/exportar/")
        self.assertEqual(resp.status_code, 409, resp.content)
        self.assertIn("feche a competência", resp.data["detail"].lower())

    def test_exportar_marks_exportada_and_returns_text(self):
        comp = self._competencia(status="fechada")
        self._bpa_c(comp)
        resp = self._client(self.exporter).post(f"{BASE}/sus-competencias/{comp.id}/exportar/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(resp.data["remessa_bpa"].startswith("01"))
        self.assertEqual(resp.data["filename_bpa"], "BPA_1234567_202607.txt")
        comp.refresh_from_db()
        self.assertEqual(comp.status, "exportada")
        self.assertIsNotNone(comp.exportada_at)
        # stored (not regenerated) — the stored content equals what was returned
        self.assertEqual(comp.remessa_bpa, resp.data["remessa_bpa"])

    def test_exportar_gated_sus_export(self):
        # writer has sus.read+sus.write but NOT sus.export → 403
        comp = self._competencia(status="fechada")
        self._bpa_c(comp)
        resp = self._client(self.writer).post(f"{BASE}/sus-competencias/{comp.id}/exportar/")
        self.assertEqual(resp.status_code, 403, resp.content)

    def test_exportar_reader_forbidden(self):
        comp = self._competencia(status="fechada")
        resp = self._client(self.reader).post(f"{BASE}/sus-competencias/{comp.id}/exportar/")
        self.assertEqual(resp.status_code, 403)
