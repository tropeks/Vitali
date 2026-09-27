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

from unittest import mock

from django.test import SimpleTestCase

import apps.core.audit_coverage as audit_coverage
from apps.core.audit_coverage import (
    ISENTAS,
    MODELS_SEM_DADO_SENSIVEL,
    MODELS_SENSIVEIS,
    VIEWS_SEM_MODEL,
    exigem_trilha,
    mixin_fora_de_ordem,
    views_registradas,
    views_sem_model_nao_declaradas,
)
from apps.core.audit_coverage_routes import (
    ACTIONS_ISENTAS,
    LIST_ALWAYS_ISENTAS,
    rotas_get_registradas,
    rotas_sem_cobertura,
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

    def test_toda_rota_get_que_exige_trilha_esta_coberta_ou_isenta(self) -> None:
        """Ordem 019 — o entregável durável: o guarda muda de granularidade.

        `tem_trilha`, acima, é cego à AÇÃO: uma classe com `AuditReadMixin`
        passava mesmo que uma `@action` de detalhe (`medical_history`,
        `download` do lote TISS...) nunca gravasse nada, porque o mixin só
        intercepta `retrieve`/`list`. Este teste enumera por ROTA — o mesmo
        roteador, um nível abaixo — e reprova a mesma rota que a 016 daria
        como coberta por engano.

        **Correção pós-019: `list` também é cego assim, um nível mais fundo.**
        A primeira versão deste guarda dava `list` como coberta só por a classe
        ter o mixin — sem checar `AUDIT_LIST_ALWAYS` — e por isso ainda dava
        verde com 70 views sensíveis cuja `list` sem filtro nunca gravava nada
        (`hr.LeaveRequestViewSet` incluída: `/rh/afastamentos` lê o afastamento
        médico do quadro inteiro da clínica sem deixar rastro). Agora `list`
        de view sensível só conta como coberta com `AUDIT_LIST_ALWAYS = True`
        ou isenção declarada em `LIST_ALWAYS_ISENTAS`.
        """
        faltando = rotas_sem_cobertura()
        if faltando:
            detalhe = "\n".join(
                f"  {r['app']}.{r['view']}.{r['action']} ({r['model']}) — exige "
                f"trilha por: {r['motivo']}"
                for r in faltando
            )
            self.fail(
                f"{len(faltando)} rota(s) GET leem dado sensível sem deixar trilha.\n"
                f"{detalhe}\n\n"
                "Para `list`: ligue `AUDIT_LIST_ALWAYS = True` no viewset, ou "
                "declare a isenção em audit_coverage_routes.LIST_ALWAYS_ISENTAS "
                "COM O MOTIVO. Para outra action: cubra com `AUDIT_READ_ACTIONS` "
                "(apps/core/mixins.py) se ela lê o mesmo recurso do "
                "retrieve/list, ou declare em ACTIONS_ISENTAS COM O MOTIVO."
            )

    def test_a_enumeracao_de_rotas_enxerga_o_sistema_inteiro(self) -> None:
        """Piso da enumeração por ROTA — equivalente ao de `views_registradas()`
        acima, um nível abaixo. Um roteador que quebre encolhe a lista e o
        teste acima passa por vacuidade; este piso acusa o colapso.

        Margem coerente com a do piso de classe (100 contra 154 hoje, ~35% de
        folga) — não um número que quase encosta no total real: 321 rotas
        hoje, 321 × 0,65 ≈ 208, arredondado para 210. Um piso a 7% do total
        (300 contra 321, o que este teste tinha antes desta correção) dispara
        por ruído de qualquer refactor pequeno ou não dispara para um colapso
        parcial — as duas falhas que um piso deveria evitar.
        """
        total = len(rotas_get_registradas())
        self.assertGreater(
            total, 210, f"a enumeração de rotas devolveu só {total} — travessia quebrada?"
        )

    def test_toda_isencao_de_acao_tem_motivo_escrito(self) -> None:
        """Ordem 019: isentar uma ROTA (não a classe inteira) exige o mesmo
        motivo escrito que `ISENTAS` já exige por classe."""
        for chave, motivo in ACTIONS_ISENTAS.items():
            self.assertGreater(
                len(motivo.strip()),
                40,
                f"a isenção de {chave} não explica nada — isenção sem motivo vira hábito",
            )

    def test_toda_isencao_de_list_always_tem_motivo_escrito(self) -> None:
        """Correção pós-019: isentar uma `list` de `AUDIT_LIST_ALWAYS` exige o
        mesmo motivo escrito que `ISENTAS`/`ACTIONS_ISENTAS` já exigem. Hoje
        `LIST_ALWAYS_ISENTAS` está vazio (nenhuma `list` de view sensível bateu
        em polling na varredura do frontend) — este teste protege a próxima
        entrada, não a de hoje."""
        for chave, motivo in LIST_ALWAYS_ISENTAS.items():
            self.assertGreater(
                len(motivo.strip()),
                40,
                f"a isenção de {chave} não explica nada — isenção sem motivo vira hábito",
            )

    def test_saltos_maximos_esta_saturado(self) -> None:
        """Revisão pós-019: `SALTOS_MAXIMOS` truncava cadeia real de prontuário.

        Medido variando o limite: saltos=2 dava 71 views, saltos=3 dava 73 (+
        `IsolatedOrganismViewSet`, `NursingPrescriptionItemViewSet`), saltos=4
        dava 74 (+ `AntibiogramEntryViewSet`), e saturava — 5, 6, 7, 8 todos em
        74. As três novas eram prontuário de verdade fora do crivo só porque o
        orçamento de saltos acabava antes de chegar em `Patient`; nenhuma delas
        é falso positivo (quem barra os 46 falsos positivos da 016 é
        `ARESTAS_PROIBIDAS`, não a profundidade).

        Este teste converte a medição pontual em garantia permanente: subir o
        limite atual (`SALTOS_MAXIMOS`, hoje saturação+margem) em +2 não pode
        acrescentar NENHUMA view. Se acrescentar, uma cadeia mais longa até
        `Patient` nasceu no código — o teste reprova e obriga alguém a decidir
        (subir o limite de novo, ou isentar), em vez de a view sumir do crivo
        em silêncio.
        """
        base = {v["view"] for v in exigem_trilha()}
        with mock.patch.object(audit_coverage, "SALTOS_MAXIMOS", audit_coverage.SALTOS_MAXIMOS + 2):
            com_margem = {v["view"] for v in exigem_trilha()}
        novos = com_margem - base
        self.assertFalse(
            novos,
            f"subir SALTOS_MAXIMOS em +2 acrescentou {len(novos)} view(s): {sorted(novos)} — "
            "há uma cadeia até Patient mais longa que o limite atual enxerga. Decida: suba "
            "SALTOS_MAXIMOS (com o motivo medido, como no comentário da constante) ou declare "
            "a(s) view(s) em ISENTAS.",
        )

    def test_toda_view_resolve_model_ou_esta_declarada_sem_model(self) -> None:
        """Revisão pós-019: fecha a CLASSE do defeito do `model=None`, não só
        as instâncias que a revisão achou (`PatientViewSet`, `EncounterViewSet`,
        `TISSGuideViewSet`, `PriceTableViewSet`, `UserListCreateView` — todas
        só com `get_queryset`/`get_serializer_class` dinâmicos, sem atributo
        estático, e por isso invisíveis a `exigem_trilha()` até alguém ir
        procurar à mão). Toda view enumerada resolve um model (direto ou via
        `VIEW_MODEL_OVERRIDES`), ou está em `VIEWS_SEM_MODEL` com motivo — uma
        sétima view deste padrão não desaparece mais em silêncio.
        """
        faltando = views_sem_model_nao_declaradas()
        if faltando:
            detalhe = "\n".join(f"  {v['app']}.{v['view']}" for v in faltando)
            self.fail(
                f"{len(faltando)} view(s) sem model resolvido e sem declaração.\n"
                f"{detalhe}\n\n"
                "Se a view tem um model de verdade (provável: `get_queryset`/"
                "`get_serializer_class` são só métodos dinâmicos), acrescente em "
                "apps/core/audit_coverage.VIEW_MODEL_OVERRIDES. Se genuinamente não "
                "tem model, declare em VIEWS_SEM_MODEL COM O MOTIVO."
            )

    def test_toda_view_sem_model_tem_motivo_escrito(self) -> None:
        """Mesmo contrato de `ISENTAS`: declarar que uma view não tem model
        exige dizer por quê, não só apagar o alerta."""
        for view, motivo in VIEWS_SEM_MODEL.items():
            self.assertGreater(
                len(motivo.strip()),
                40,
                f"{view} está em VIEWS_SEM_MODEL sem motivo — isenção sem motivo vira hábito",
            )


class DadoPessoalForaDoGrafoDePatientTests(SimpleTestCase):
    """Ordem 029 — doador de sangue e sorologia: dado pessoal sensível de quem
    NÃO é paciente, fora do grafo de `emr.Patient`.

    Os dois viewsets herdavam `AuditReadMixin`, e a guarda dava as quatro rotas
    GET como cobertas — mas só porque não as considerava sensíveis: `motivo=''`,
    e `list` de view "não sensível" passa sem `AUDIT_LIST_ALWAYS`. A `list` sem
    filtro não gravava nada, e tirar o mixin amanhã não reprovaria nada. Verde
    que não significa verde (INTENT v6, §Limites).
    """

    VIEWS_DO_DOADOR = ("BloodDonorViewSet", "BloodBagSerologyViewSet")

    def test_doador_e_sorologia_exigem_trilha(self) -> None:
        exigem = {v["view"] for v in exigem_trilha()}
        for view in self.VIEWS_DO_DOADOR:
            self.assertIn(
                view,
                exigem,
                f"{view} lê dado pessoal sensível de doador (LGPD art. 5º II) e a guarda "
                "não a exige — está fora do grafo de Patient e fora de MODELS_SENSIVEIS",
            )

    def test_toda_rota_get_do_doador_exige_e_tem_trilha(self) -> None:
        rotas = [r for r in rotas_get_registradas() if r["view"] in self.VIEWS_DO_DOADOR]
        acoes = sorted((r["view"], r["action"]) for r in rotas)
        self.assertEqual(
            acoes,
            [
                ("BloodBagSerologyViewSet", "list"),
                ("BloodBagSerologyViewSet", "retrieve"),
                ("BloodDonorViewSet", "list"),
                ("BloodDonorViewSet", "retrieve"),
            ],
        )
        for r in rotas:
            self.assertTrue(r["motivo"], f"{r['view']}.{r['action']} sem motivo de trilha")
            self.assertTrue(r["coberta"], f"{r['view']}.{r['action']} exige trilha e não grava")
            self.assertFalse(r["isenta"], f"{r['view']}.{r['action']} isenta — não pode")

    def test_toda_view_com_identificador_pessoal_esta_classificada(self) -> None:
        """O entregável durável da 029: a guarda passa a PERGUNTAR.

        `MODELS_SENSIVEIS` é lista explícita e só cobre o que alguém lembrou de
        pôr nela; doador entrou no Sprint H2, depois da 017, e ninguém lembrou.
        Toda view cujo model tem campo que identifica pessoa natural
        (`IDENTIFICADORES_PESSOAIS`) precisa estar classificada — alcança
        `Patient`, OU `MODELS_SENSIVEIS`, OU `MODELS_SEM_DADO_SENSIVEL` com
        motivo. O nome do campo dispara a pergunta; não a responde.
        """
        faltando = audit_coverage.views_com_identificador_nao_classificadas()
        if faltando:
            detalhe = "\n".join(
                f"  {v['app']}.{v['view']} ({v['model']}) — campos: {', '.join(v['identificadores'])}"
                for v in faltando
            )
            self.fail(
                f"{len(faltando)} view(s) servem model com identificador de pessoa e "
                f"ninguém decidiu se o dado é sensível.\n{detalhe}\n\n"
                "Decida e escreva o motivo em apps/core/audit_coverage.py: "
                "MODELS_SENSIVEIS (exige trilha) ou MODELS_SEM_DADO_SENSIVEL (não exige)."
            )

    def test_a_pergunta_por_identificador_enxerga_o_prontuario(self) -> None:
        """Piso contra vacuidade: se a detecção de campo quebrar, a lista de
        views com identificador encolhe e o teste acima passa sem verificar
        nada. `PatientViewSet` (cpf, cns, birth_date) e `BloodDonorViewSet`
        (cpf) têm de aparecer."""
        vistas = {v["view"] for v in audit_coverage.views_com_identificador()}
        for view in ("PatientViewSet", "BloodDonorViewSet"):
            self.assertIn(view, vistas, f"a pergunta por identificador não viu {view}")


class ViewSemQuerysetTests(SimpleTestCase):
    """Ordem 030 — a guarda passa a enxergar view sem `queryset`.

    `views_registradas()` e `_rotas_get_do_roteador()` só viam view com
    `queryset`/`get_queryset`. Medido em 27/09: 103 classes com GET ficavam de
    fora, entre elas as 22 views FHIR de leitura de prontuário
    (`/api/v1/fhir/Patient/`, `Condition`, `Observation`, `DocumentReference`...),
    que não gravavam trilha nenhuma. Não eram isentas: eram invisíveis, e
    ninguém tinha decidido nada.
    """

    def test_toda_rota_get_sem_queryset_grava_trilha_ou_esta_isenta(self) -> None:
        from apps.core.audit_coverage_routes import rotas_sem_queryset_nao_classificadas

        faltando = rotas_sem_queryset_nao_classificadas()
        if faltando:
            detalhe = "\n".join(
                f"  {r['modulo']}.{r['view']}" + (f".{r['action']}" if r["action"] else "")
                for r in faltando
            )
            self.fail(
                f"{len(faltando)} rota(s) GET de view sem queryset sem classificação.\n"
                f"{detalhe}\n\n"
                "Se lê dado de paciente ou dado pessoal sensível: `AuditReadAPIViewMixin` "
                "como PRIMEIRA base (apps/core/mixins.py), com `audit_resource_type` e, "
                "se a rota for de detalhe, `AUDIT_LOOKUP_KWARG`. Se não lê: declare em "
                "apps/core/audit_coverage_routes.APIVIEWS_ISENTAS COM O MOTIVO."
            )

    def test_toda_leitura_fhir_de_paciente_grava_trilha(self) -> None:
        """Nomeado de propósito, além do teste geral: o FHIR é a porta de
        interoperabilidade — o prontuário sai do sistema por ela. Das 22 views
        de leitura, 20 leem prontuário e gravam; `Practitioner` (read/search) é
        o cadastro do profissional, a mesma decisão de `emr.Professional` na
        ordem 029, e fica isento com motivo."""
        from apps.core.audit_coverage_routes import rotas_get_sem_queryset

        fhir = [r for r in rotas_get_sem_queryset() if r["modulo"] == "apps.fhir.views"]
        leituras = [r for r in fhir if r["view"] != "CapabilityStatementView"]
        self.assertEqual(len(leituras), 22, sorted(r["view"] for r in leituras))
        profissional = {"PractitionerReadView", "PractitionerSearchView"}
        sem_trilha = sorted(
            r["view"] for r in leituras if r["view"] not in profissional and not r["coberta"]
        )
        self.assertFalse(sem_trilha, f"leitura FHIR de prontuário sem trilha: {sem_trilha}")
        for r in leituras:
            if r["view"] in profissional:
                self.assertTrue(r["isenta"], f"{r['view']} precisa de isenção com motivo")

    def test_a_enumeracao_sem_queryset_enxerga_o_sistema(self) -> None:
        """Piso contra vacuidade, na mesma folga dos outros (~35%): 103 classes
        com GET medidas em 27/09 → piso 67."""
        from apps.core.audit_coverage_routes import rotas_get_sem_queryset

        total = len(rotas_get_sem_queryset())
        self.assertGreater(total, 67, f"a enumeração sem queryset devolveu só {total}")

    def test_toda_isencao_de_apiview_tem_motivo_escrito(self) -> None:
        from apps.core.audit_coverage_routes import APIVIEWS_ISENTAS

        for chave, motivo in APIVIEWS_ISENTAS.items():
            self.assertGreater(
                len(motivo.strip()),
                40,
                f"a isenção de {chave} não explica nada — isenção sem motivo vira hábito",
            )

    def test_nenhuma_isencao_de_apiview_e_orfa(self) -> None:
        from apps.core.audit_coverage_routes import isencoes_de_apiview_sem_rota

        orfas = isencoes_de_apiview_sem_rota()
        self.assertFalse(
            orfas,
            f"isenção sem rota, ou de view que já grava trilha: {orfas} — apague a entrada",
        )

    def test_auditreadapiviewmixin_vem_antes_de_apiview(self) -> None:
        from apps.core.audit_coverage_routes import apiview_mixin_fora_de_ordem

        fora = apiview_mixin_fora_de_ordem()
        self.assertFalse(fora, "trilha morta por ordem de base:\n" + "\n".join(fora))

    def test_lookup_da_trilha_casa_o_kwarg_da_rota(self) -> None:
        from apps.core.audit_coverage_routes import lookup_que_nao_casa_a_rota

        erros = lookup_que_nao_casa_a_rota()
        self.assertFalse(erros, "\n".join(erros))
