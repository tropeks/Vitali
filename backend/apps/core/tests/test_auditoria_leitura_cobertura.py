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

from apps.core.audit_coverage import (
    ISENTAS,
    MODELS_SEM_DADO_SENSIVEL,
    MODELS_SENSIVEIS,
    exigem_trilha,
    mixin_fora_de_ordem,
    views_registradas,
)


class CoberturaDeAuditoriaDeLeituraTests(SimpleTestCase):
    def test_toda_view_que_toca_paciente_deixa_trilha(self) -> None:
        faltando = [v for v in exigem_trilha() if not v["tem_trilha"]]
        if faltando:
            detalhe = "\n".join(
                f"  {v['app']}.{v['view']} ({v['model']}) — exige trilha por: {v['motivo']}"
                for v in faltando
            )
            self.fail(
                f"{len(faltando)} view(s) leem dado sensível sem deixar trilha.\n"
                f"{detalhe}\n\n"
                "Acrescente `AuditReadMixin` e `audit_resource_type`, ou — se a view "
                "realmente não lê dado sensível — declare a isenção em "
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

    def test_todo_model_sensivel_tem_motivo_escrito(self) -> None:
        """Ordem 017: entrar em MODELS_SENSIVEIS exige dizer o campo e a lei."""
        for model, motivo in MODELS_SENSIVEIS.items():
            self.assertGreater(
                len(motivo.strip()),
                40,
                f"{model} está em MODELS_SENSIVEIS sem motivo — "
                "diga qual CAMPO carrega o dado sensível",
            )

    def test_todo_model_sem_dado_sensivel_tem_motivo_escrito(self) -> None:
        """Ordem 017: ficar de fora da trilha é declaração, não esquecimento."""
        for model, motivo in MODELS_SEM_DADO_SENSIVEL.items():
            self.assertGreater(
                len(motivo.strip()),
                40,
                f"{model} está em MODELS_SEM_DADO_SENSIVEL sem motivo — "
                "isenção sem motivo vira hábito",
            )

    def test_toda_view_do_app_hr_esta_classificada(self) -> None:
        """Ordem 017: piso de enumeração da faixa 2, equivalente ao da faixa 1.

        Toda view do app `hr` registrada no roteador precisa estar classificada:
        OU exige trilha e a tem (o model está em `MODELS_SENSIVEIS`, ou alcança
        `Patient`), OU o model dela consta em `MODELS_SEM_DADO_SENSIVEL` com
        motivo. Uma view de RH nova sem nenhuma das duas classificações reprova
        — não fica invisível por omissão.
        """
        views_hr = [v for v in views_registradas() if v["app"] == "hr"]
        self.assertGreater(
            len(views_hr), 0, "nenhuma view do app hr foi enumerada — travessia quebrada?"
        )

        nao_classificadas = [
            v for v in views_hr if not v["motivo"] and v["model"] not in MODELS_SEM_DADO_SENSIVEL
        ]
        if nao_classificadas:
            detalhe = "\n".join(f"  {v['view']} ({v['model']})" for v in nao_classificadas)
            self.fail(
                f"{len(nao_classificadas)} view(s) do app hr sem classificação.\n"
                f"{detalhe}\n\n"
                "Toda view de RH precisa constar de MODELS_SENSIVEIS (com trilha) "
                "ou de MODELS_SEM_DADO_SENSIVEL (sem trilha), ambos com motivo "
                "escrito em apps/core/audit_coverage.py."
            )

    def test_auditreadmixin_e_sempre_a_primeira_base(self) -> None:
        """`tem_trilha` (issubclass) é cego à posição da base — este teste não é.

        Se `AuditReadMixin` deixar de ser a PRIMEIRA base de uma view, os mixins
        do DRF (`RetrieveModelMixin`/`ListModelMixin`) vencem no MRO, o `super()`
        do mixin de auditoria nunca é alcançado, e a trilha morre em silêncio —
        `issubclass(cls, AuditReadMixin)` continua `True` e não acusa nada. É o
        modo de falha que as ordens 016 e 017 nomeiam como lição; vale para o
        sistema inteiro, não só para o RH.
        """
        fora_de_ordem = mixin_fora_de_ordem()
        if fora_de_ordem:
            detalhe = "\n".join(f"  {linha}" for linha in fora_de_ordem)
            self.fail(
                f"{len(fora_de_ordem)} view(s) com AuditReadMixin fora da primeira "
                f"base — a trilha dessas views está morta:\n{detalhe}\n\n"
                "Ponha AuditReadMixin como PRIMEIRA base na declaração da classe."
            )
