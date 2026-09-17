"""
Guarda: toda view que lê dado ligado a paciente deixa trilha de leitura.

**Por que este teste é o entregável desta ordem, e não as edições.** Pôr o mixin em
14 viewsets fecha o buraco de hoje. O que impede o buraco de voltar é este teste:
ele enumera o que está REGISTRADO NO ROTEADOR, classifica pelo grafo de models, e
reprova quando uma view clínica nova nasce sem trilha. Sem ele a cobertura cai
sozinha e ninguém vê — foi assim que ela chegou a 59 de 154.

CFM Res. 1.821/2007 exige rastreabilidade do ACESSO ao prontuário, não só das
alterações. `docs/COMPLIANCE_CHECKLIST.md` §2.1.

Contra o código anterior à ordem 016 este teste falha: 14 views alcançam
`emr.Patient` e não herdam `AuditReadMixin`.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.core.audit_coverage import ISENTAS, exigem_trilha, views_registradas


class CoberturaDeAuditoriaDeLeituraTests(SimpleTestCase):
    def test_toda_view_que_toca_paciente_deixa_trilha(self) -> None:
        faltando = [v for v in exigem_trilha() if not v["tem_trilha"]]
        if faltando:
            detalhe = "\n".join(
                f"  {v['app']}.{v['view']} ({v['model']}) — alcança paciente por: {v['caminho']}"
                for v in faltando
            )
            self.fail(
                f"{len(faltando)} view(s) leem dado ligado a paciente sem deixar trilha.\n"
                f"{detalhe}\n\n"
                "Acrescente `AuditReadMixin` e `audit_resource_type`, ou — se a view "
                "realmente não lê prontuário — declare a isenção em "
                "`apps/core/audit_coverage.ISENTAS` COM O MOTIVO."
            )

    def test_a_enumeracao_enxerga_o_sistema_inteiro(self) -> None:
        """Um classificador que enumera pouco aprova por vacuidade.

        Se um refactor quebrar a travessia do roteador, a lista encolhe e o teste
        acima passa sem verificar nada — o defeito que esta série vem catalogando.
        Este piso não é um número mágico: é muito abaixo das 154 vistas hoje, e
        serve só para acusar colapso da enumeração.
        """
        total = len(views_registradas())
        self.assertGreater(
            total, 100, f"a enumeração devolveu só {total} views — travessia quebrada?"
        )

    def test_toda_isencao_tem_motivo_escrito(self) -> None:
        for view, motivo in ISENTAS.items():
            self.assertGreater(
                len(motivo.strip()),
                40,
                f"a isenção de {view} não explica nada — isenção sem motivo vira hábito",
            )
