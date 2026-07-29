"""
AI3 — Remessa DATASUS SISAIH (AIH, Faturamento SUS de internação).

Covers (all local, no network):
  * Remessa AIH (positional): header + AIH line + secundário line, fixed widths.
  * motivo_saida → código posicional de 2 dígitos (estruturalmente-fiel).
  * Datas AAAAMMDD; caráter "01"/"02"; determinismo (bytes idênticos).
  * exportar_competencia agora inclui remessa_aih e seta o campo no model.
  * Competência sem AIH → remessa AIH só com header (0 detalhes), sem erro.

Espelha ``test_sus_remessa.py`` (mesmo ``TenantTestCase`` + base de fixtures).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from apps.billing.services import sus_remessa
from apps.billing.services.sus_remessa import (
    AIH_SEC_WIDTH,
    AIH_WIDTH,
    HEADER_COMPETENCIA,
    HEADER_NUM_LINHAS,
    HEADER_WIDTH,
    LINE_TERMINATOR,
    exportar_competencia,
    gerar_remessa_aih,
)
from apps.billing.sus_models import AihAutorizacao, AihProcedimentoSecundario

from .test_sus_remessa import SusRemessaTestBase


class AihRemessaTestBase(SusRemessaTestBase):
    def _aih(
        self,
        comp,
        *,
        numero="2026070000001",
        carater="02",
        motivo="obito",
        data_saida=date(2026, 7, 20),
    ):
        return AihAutorizacao.objects.create(
            competencia=comp,
            numero_aih=numero,
            procedimento_principal=self.sigtap_apac,
            cid_principal="C509",
            patient=self.patient,
            cns="700000000000009",
            professional_solicitante=self.prof,
            professional_responsavel=self.prof,
            data_internacao=date(2026, 7, 10),
            data_saida=data_saida,
            carater_internacao=carater,
            motivo_saida=motivo,
            valor=Decimal("1500.00"),
        )


class TestRemessaAih(AihRemessaTestBase):
    def _lines(self, content):
        return content.split(LINE_TERMINATOR)

    def test_header_plus_aih_and_secondary_lines(self):
        comp = self._competencia()
        aih = self._aih(comp)
        AihProcedimentoSecundario.objects.create(
            aih=aih, sigtap=self.sigtap_c, quantidade=2, valor=Decimal("4.00")
        )
        content = gerar_remessa_aih(comp)
        lines = self._lines(content)
        # header + AIH line + secundário line
        self.assertEqual(len(lines), 3)
        header, aih_line, sec_line = lines
        self.assertEqual(len(header), HEADER_WIDTH)
        self.assertTrue(aih_line.startswith("21"))
        self.assertEqual(len(aih_line), AIH_WIDTH)
        self.assertTrue(sec_line.startswith("22"))
        self.assertEqual(len(sec_line), AIH_SEC_WIDTH)

    def test_header_carries_competencia_and_count(self):
        comp = self._competencia("2026-07")
        self._aih(comp)
        content = gerar_remessa_aih(comp)
        header = self._lines(content)[0]
        off, w = HEADER_COMPETENCIA
        self.assertEqual(header[off : off + w], "202607")
        off, w = HEADER_NUM_LINHAS
        self.assertEqual(header[off : off + w], "000001")

    def test_aih_line_carries_numero_and_sigtap(self):
        comp = self._competencia()
        self._aih(comp, numero="2026070000042")
        aih_line = self._lines(gerar_remessa_aih(comp))[1]
        off, w = sus_remessa.AIH_NUMERO
        self.assertEqual(aih_line[off : off + w], "2026070000042")
        off, w = sus_remessa.AIH_SIGTAP
        self.assertEqual(aih_line[off : off + w], "0304010030")

    def test_dates_and_carater_and_motivo_obito(self):
        comp = self._competencia()
        self._aih(comp, carater="02", motivo="obito", data_saida=date(2026, 7, 20))
        aih_line = self._lines(gerar_remessa_aih(comp))[1]
        off, w = sus_remessa.AIH_DATA_INTERNACAO
        self.assertEqual(aih_line[off : off + w], "20260710")
        off, w = sus_remessa.AIH_DATA_SAIDA
        self.assertEqual(aih_line[off : off + w], "20260720")
        off, w = sus_remessa.AIH_CARATER
        self.assertEqual(aih_line[off : off + w], "02")
        off, w = sus_remessa.AIH_MOTIVO
        self.assertEqual(aih_line[off : off + w], "41")  # obito → 41

    def test_motivo_conversion_table(self):
        cases = {
            "alta_curado": "11",
            "alta_melhorado": "12",
            "transferencia": "31",
            "obito": "41",
            "permanencia": "51",
            "": "00",
        }
        off, w = sus_remessa.AIH_MOTIVO
        for i, (motivo, codigo) in enumerate(cases.items()):
            comp = self._competencia(f"2026-{i + 1:02d}")
            self._aih(comp, numero=f"20260{i}000001", motivo=motivo)
            aih_line = self._lines(gerar_remessa_aih(comp))[1]
            self.assertEqual(aih_line[off : off + w], codigo, motivo)

    def test_carater_eletivo(self):
        comp = self._competencia()
        self._aih(comp, carater="01")
        aih_line = self._lines(gerar_remessa_aih(comp))[1]
        off, w = sus_remessa.AIH_CARATER
        self.assertEqual(aih_line[off : off + w], "01")

    def test_data_saida_null_yields_zeros(self):
        comp = self._competencia()
        self._aih(comp, data_saida=None, motivo="permanencia")
        aih_line = self._lines(gerar_remessa_aih(comp))[1]
        off, w = sus_remessa.AIH_DATA_SAIDA
        self.assertEqual(aih_line[off : off + w], "00000000")

    def test_deterministic_zero_rows_header_only(self):
        comp = self._competencia()
        content = gerar_remessa_aih(comp)
        lines = self._lines(content)
        self.assertEqual(len(lines), 1)
        self.assertEqual(len(lines[0]), HEADER_WIDTH)

    def test_deterministic_byte_identical(self):
        comp = self._competencia()
        aih = self._aih(comp)
        AihProcedimentoSecundario.objects.create(
            aih=aih, sigtap=self.sigtap_c, quantidade=2, valor=Decimal("4.00")
        )
        self.assertEqual(gerar_remessa_aih(comp), gerar_remessa_aih(comp))


class TestExportIncludesAih(AihRemessaTestBase):
    def test_exportar_includes_and_stores_remessa_aih(self):
        comp = self._competencia(status="fechada")
        self._aih(comp)
        result = exportar_competencia(comp, actor=self.exporter)
        self.assertIn("remessa_aih", result)
        self.assertTrue(result["remessa_aih"].startswith("01"))
        self.assertEqual(result["filename_aih"], "AIH_1234567_202607.txt")
        comp.refresh_from_db()
        self.assertEqual(comp.remessa_aih, result["remessa_aih"])
        # BPA/APAC still present (assinatura não quebrada).
        self.assertIn("remessa_bpa", result)
        self.assertIn("remessa_apac", result)

    def test_exportar_endpoint_returns_remessa_aih(self):
        comp = self._competencia(status="fechada")
        self._aih(comp)
        resp = self._client(self.exporter).post(
            f"/api/v1/billing/sus-competencias/{comp.id}/exportar/"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(resp.data["remessa_aih"].startswith("01"))
        self.assertEqual(resp.data["filename_aih"], "AIH_1234567_202607.txt")
