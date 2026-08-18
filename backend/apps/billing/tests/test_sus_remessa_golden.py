"""
2.5 — Regressão de layout da remessa DATASUS (BPA-C, BPA-I, APAC, AIH).

``sus_remessa.py`` já documenta no próprio módulo que o layout é
**coerente, estruturalmente-fiel, NÃO o mapa de campos byte-exato oficial
DATASUS** (ver o docstring do módulo e ``gerar_remessa_aih``'s "Design note").
Como não existe XSD/spec formal do DATASUS versionado neste repo para validar
contra, o entregável possível aqui é diferente do 2.4: um teste de
**regressão de layout** — gera a remessa a partir de dados fixos e compara
byte-a-byte com um arquivo de referência versionado
(``apps/billing/tests/golden/*.txt``), para que qualquer mudança acidental de
offset/largura/padding quebre o teste. Não afirma conformidade DATASUS; só
constância do que já existe.

Os arquivos golden foram gerados chamando as MESMAS funções puras
(``gerar_remessa_bpa`` / ``gerar_remessa_apac`` / ``gerar_remessa_aih``) fora
do Django (sem DB) com objetos equivalentes aos criados aqui — não foram
digitados à mão. Ver a lista de divergências conhecidas vs. DATASUS oficial em
``docs/sus_remessa_conformance.md``.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from apps.billing.services.sus_remessa import (
    LINE_TERMINATOR,
    gerar_remessa_aih,
    gerar_remessa_apac,
    gerar_remessa_bpa,
)
from apps.billing.sus_models import (
    AihProcedimentoSecundario,
    ApacProcedimentoSecundario,
    BpaIndividualizado,
)
from apps.core.sigtap_catalog_models import SIGTAPProcedure

from .test_aih_remessa import AihRemessaTestBase
from .test_sus_remessa import SusRemessaTestBase

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"


def _read_golden(name: str) -> str:
    return (GOLDEN_DIR / name).read_bytes().decode("ascii")


class RemessaBpaLayoutRegressionTests(SusRemessaTestBase):
    """BPA-C + BPA-I in one remessa (tipo 02 + tipo 03 detail lines)."""

    def test_bpa_remessa_matches_golden_file(self):
        comp = self._competencia()
        self._bpa_c(comp, quantidade=3)
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

        assert content == _read_golden("remessa_bpa_golden.txt")
        # Belt and suspenders: CRLF terminator, no trailing terminator.
        assert LINE_TERMINATOR in content
        assert not content.endswith(LINE_TERMINATOR)


class RemessaApacLayoutRegressionTests(SusRemessaTestBase):
    """APAC (tipo 11) + procedimento secundário (tipo 12)."""

    def test_apac_remessa_matches_golden_file(self):
        comp = self._competencia()
        apac = self._apac(comp)
        ApacProcedimentoSecundario.objects.create(
            apac=apac, sigtap=self.sigtap_c, quantidade=2, valor=Decimal("4.00")
        )

        content = gerar_remessa_apac(comp)

        assert content == _read_golden("remessa_apac_golden.txt")


class RemessaAihLayoutRegressionTests(AihRemessaTestBase):
    """AIH (tipo 21) + procedimento secundário (tipo 22)."""

    def test_aih_remessa_matches_golden_file(self):
        comp = self._competencia()
        aih = self._aih(comp)
        # AihProcedimentoSecundario.save() RECOMPUTES valor from
        # (sigtap.valor_sh + sigtap.valor_sp) × quantidade — unlike
        # ApacProcedimentoSecundario, the ``valor=`` kwarg below is NOT the
        # final stored value. self.sigtap_c (shared fixture) has valor_sh=0
        # by default; set it here (local update, does not affect other tests)
        # so the computed valor matches the golden file's 4.00 (2.00 × 2).
        SIGTAPProcedure.objects.filter(pk=self.sigtap_c.pk).update(valor_sh=Decimal("2.00"))
        self.sigtap_c.refresh_from_db()
        AihProcedimentoSecundario.objects.create(
            aih=aih, sigtap=self.sigtap_c, quantidade=2, valor=Decimal("4.00")
        )

        content = gerar_remessa_aih(comp)

        assert content == _read_golden("remessa_aih_golden.txt")
