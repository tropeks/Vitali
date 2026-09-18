"""O guarda muda de granularidade: da CLASSE para a ROTA (ordem 019).

`apps.core.audit_coverage.views_registradas()` responde "esta CLASSE herda
`AuditReadMixin`?" — e o mixin só intercepta `retrieve`/`list`. Enumerando pelo
roteador as rotas `GET` (não as classes), 30 rotas (15 `@action` distintas) de
classes "com trilha" não gravavam nada — sete leitura de prontuário
(`PatientViewSet.medical_history`, `.allergies`, `.timeline`, `.insurance`,
`EncounterViewSet.procedures`, `SurgicalCaseViewSet.timeline`,
`TISSBatchViewSet.download`). `rotas_get_registradas()`/`rotas_sem_cobertura()`
respondem "esta ROTA deixa trilha?", enumerando pelo mesmo roteador um nível
abaixo (`callback.actions`, não `callback.cls`).

**Correção pós-019 — `list` também é rota, e "tem o mixin" não basta.**
A primeira versão desta correção tratava `list` como coberta só por a classe
herdar o mixin — o MESMO defeito que a ordem existe para consertar, um nível
abaixo: `AuditReadMixin.list()` só grava sem filtro quando `AUDIT_LIST_ALWAYS =
True` (ver `apps/core/mixins.py`); sem isso, uma `list` crua de dado sensível
passava pelo guarda sem nunca ter gravado nada. Medido: `hr.LeaveRequestViewSet`
tinha o mixin e não tinha a flag — `frontend/app/(dashboard)/rh/afastamentos/
page.tsx` chama `GET /api/v1/hr/leave-requests/` sem `?employee=`, e cada
abertura de tela lia o afastamento médico do quadro inteiro sem deixar rastro.
Por isso `rotas_get_registradas()` exige, para toda `list` de view sensível:
`AUDIT_LIST_ALWAYS = True` OU isenção declarada em `LIST_ALWAYS_ISENTAS` — com
motivo, mesmo contrato de `ISENTAS`/`ACTIONS_ISENTAS`.
"""

from __future__ import annotations

from apps.core.audit_coverage import ISENTAS, MODELS_SENSIVEIS, _model_da_view, caminho_ate_paciente

#: Rotas GET isentas por AÇÃO, chave `"NomeDaClasse.nome_da_action"` — para
#: `@action` de uma classe que PRECISA de trilha nas outras rotas (por isso
#: não cabe em `ISENTAS`, que isenta a classe inteira). Mesmo contrato: sem
#: motivo escrito, vira isenção por hábito.
ACTIONS_ISENTAS: dict[str, str] = {
    "AdmissionViewSet.census": (
        "Painel de ocupação/censo por unidade — repinta sozinho, não é busca por "
        "um paciente. Uma linha por repintura não diz quem foi procurar o quê, só "
        "que a tela do posto de enfermagem estava aberta."
    ),
    "AdmissionViewSet.planned": (
        "Quadro de altas previstas, ordenado por horário — mesmo painel de "
        "trabalho do censo, sem filtro dirigido a um paciente específico."
    ),
    "AppointmentViewSet.today": (
        "Agenda do dia da recepção. Medido: /waiting-room dispara esta e a lista "
        "de espera a cada 30s — ~240 linhas/hora/aba, ~7.200/dia com três "
        "recepções. Uma linha por repintura de tela de recepção não é trilha, é "
        "ruído com aparência de trilha."
    ),
    "EmergencyEncounterViewSet.board": (
        "Painel de pronto-socorro repintando 24/7 (tela de parede). Medido: "
        "~120 linhas/hora/aba, ~2.900/dia por tela — o mesmo argumento de volume "
        "de `AppointmentViewSet.today`, aqui sem nem haver operador clicando."
    ),
    "SurgicalCaseViewSet.board": (
        "Mapa cirúrgico do dia (salas × casos agendados) — painel de trabalho do "
        "centro cirúrgico, repinta sozinho como os outros board/census/today "
        "desta lista; não é o clínico abrindo UM caso específico."
    ),
    "AccountingEntryViewSet.dre": (
        "DRE agregado (receita, despesa, caixa) por período/unidade/centro de "
        "custo — números somados, nenhum lançamento individual sai na resposta; "
        "não há dado de paciente nem de pessoa aqui."
    ),
    "TISSGuideViewSet.sadt_atendimento_options": (
        "Catálogo estático de códigos ANS (`dm_tipoAtendimento`/"
        "`dm_regimeAtendimento`) para popular um select — não há guia, paciente "
        "nem dado de ninguém na resposta, só as choices do model."
    ),
    "TISSGuideViewSet.tipo_faturamento_options": (
        "Catálogo estático de códigos ANS (`dm_tipoFaturamento`) para popular um "
        "select — mesma natureza de `sadt_atendimento_options`: zero dado de paciente ou de pessoa."
    ),
}

#: Views isentas de `AUDIT_LIST_ALWAYS` (correção pós-019) — cada uma com
#: motivo escrito, mesmo contrato de `ISENTAS`/`ACTIONS_ISENTAS`. Vazio hoje,
#: mas a vacuidade cobre só o que foi de fato procurado — não é exaustiva, e
#: dizer o contrário seria a mesma mentira que a ordem 019 existe para
#: consertar.
#:
#: **O que a varredura cobriu.** `frontend/` inteiro por `setInterval`/
#: `refetchInterval` cruzado com a rota `list` (sem sufixo de action) de cada
#: view de `exigem_trilha()` — nenhuma bate; o polling medido na ordem
#: (waiting-room, PS) chama sempre `@action` (`today`, `board`,
#: `waiting-room`), nunca a `list` crua.
#:
#: **O que a varredura NÃO cobriu, e foi achado depois.** Grep por timer não
#: pega disparo por EVENTO DE FOCO: `RemoteCombobox.tsx:84` chama `load('')`
#: no `onFocus` do campo vazio — sem `?search=` (string vazia é falsy, não
#: entra em `AUDIT_LIST_PARAMS`), então só `AUDIT_LIST_ALWAYS` grava. Quatro
#: call sites apontam para `/api/v1/patients/`: `OpenBoletimModal.tsx`,
#: `NewTransfusionRequestModal.tsx`, `ScheduleSurgeryModal.tsx`,
#: `ApacForm.tsx`. **Decisão: aceitar, não isentar.** É evento humano (abrir
#: um modal e clicar no campo de paciente) — mesmo custo de "uma linha por
#: abertura de tela" que a ordem já aceita para list, bem longe do polling por
#: `setInterval` que motivou as isenções de `ACTIONS_ISENTAS`. Registrado
#: aqui para não fingir que a varredura foi exaustiva quando não foi.
LIST_ALWAYS_ISENTAS: dict[str, str] = {}


def _rotas_get_do_roteador() -> list[tuple[type, str | None]]:
    """Toda rota GET do roteador, como `(classe, nome da action)`.

    O nome da action vem de ``callback.actions`` (`{"get": "list", ...}`), o
    dicionário que o Router do DRF já grava no callback — não de suposição
    sobre o nome do método. É o que revela que `PatientViewSet` tem QUATRO
    rotas GET sem trilha (`timeline`, `allergies`, `medical_history`,
    `insurance`) além de `list`/`retrieve`, onde
    `apps.core.audit_coverage._classes_do_roteador()` só enxerga UMA classe.

    Views ligadas por `path()` direto (sem Router, ex. `AuditTrailListView`)
    não têm `.actions`: ficam com action `None`, uma rota por classe, como a
    cobertura por classe já tratava antes da 019.
    """
    from django.urls import get_resolver

    vistas: dict[tuple[str, str | None], type] = {}

    def andar(resolver):
        for padrao in resolver.url_patterns:
            if hasattr(padrao, "url_patterns"):
                andar(padrao)
                continue
            cb = getattr(padrao, "callback", None)
            cls = getattr(cb, "cls", None) or getattr(cb, "view_class", None)
            if cls is None:
                continue
            actions = getattr(cb, "actions", None)
            if actions is not None:
                acao = actions.get("get")
                if acao is None:
                    continue
            else:
                if not hasattr(cls, "get_queryset") and not hasattr(cls, "queryset"):
                    continue
                acao = None
            vistas[(cls.__name__, acao)] = cls

    andar(get_resolver())
    return [(cls, acao) for (_, acao), cls in vistas.items()]


def rotas_get_registradas() -> list[dict]:
    """Toda rota GET, na granularidade que `AuditReadMixin` realmente intercepta.

    Onde `views_registradas()` pergunta "esta CLASSE herda o mixin?", esta
    pergunta "esta ROTA deixa trilha?". Coberta quando: `retrieve` numa classe
    com `AuditReadMixin`; `list` numa classe com o mixin E (a view não é
    sensível, OU `AUDIT_LIST_ALWAYS = True`, OU está isenta por
    `LIST_ALWAYS_ISENTAS`); a action consta de `AUDIT_READ_ACTIONS`
    (`apps/core/mixins.py`); OU está isenta por `ACTIONS_ISENTAS`/`ISENTAS`.
    """
    from apps.core.mixins import AuditReadMixin

    rotas: list[dict] = []
    for cls, acao in _rotas_get_do_roteador():
        model = _model_da_view(cls)
        rotulo_model = f"{model._meta.app_label}.{model.__name__}" if model else None
        caminho = caminho_ate_paciente(model) if model else ""
        motivo_sensivel = MODELS_SENSIVEIS.get(rotulo_model, "") if rotulo_model else ""
        motivo = caminho or motivo_sensivel
        tem_mixin = issubclass(cls, AuditReadMixin)
        acoes_lidas: frozenset[str] = getattr(cls, "AUDIT_READ_ACTIONS", frozenset())
        chave_acao = f"{cls.__name__}.{acao}" if acao else cls.__name__
        isenta_por_classe = cls.__name__ in ISENTAS
        isenta_por_acao = chave_acao in ACTIONS_ISENTAS
        isenta_list_always = acao == "list" and cls.__name__ in LIST_ALWAYS_ISENTAS
        if acao is None or acao == "retrieve":
            coberta = tem_mixin
        elif acao == "list":
            lista_sempre = bool(getattr(cls, "AUDIT_LIST_ALWAYS", False))
            coberta = tem_mixin and (not motivo or lista_sempre)
        elif acao in acoes_lidas:
            coberta = True
        else:
            coberta = False
        rotas.append(
            {
                "view": cls.__name__,
                "action": acao,
                "app": cls.__module__.split(".")[1] if cls.__module__.startswith("apps.") else "?",
                "model": rotulo_model,
                "motivo": motivo,
                "coberta": coberta,
                "isenta": isenta_por_classe or isenta_por_acao or isenta_list_always,
            }
        )
    return sorted(rotas, key=lambda r: (r["app"], r["view"], r["action"] or ""))


def rotas_sem_cobertura() -> list[dict]:
    """Rotas GET que exigem trilha e não estão cobertas/isentas — por rota, o
    que `exigem_trilha()` já fazia por classe: rota nova sem classificação reprova."""
    return [
        r for r in rotas_get_registradas() if r["motivo"] and not r["coberta"] and not r["isenta"]
    ]
