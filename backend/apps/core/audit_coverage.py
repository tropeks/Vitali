"""Quais views precisam deixar trilha de leitura — e por quê (ordens 016 e 017).

**O problema que isto resolve.** `AuditReadMixin` registra leitura de prontuário,
como a Res. CFM 1.821/2007 exige. Saber *quais* views precisam dele não pode ser
memória de quem revisa: em 17/09 a cobertura era 59 de 154, e nada impedia que a
próxima view clínica nascesse sem trilha — nem avisaria.

**Por que a enumeração vem do roteador, e não de `grep`.** Medido no mesmo dia:
contar viewsets por expressão regular sobre o fonte deu 71, depois 75, depois 41,
conforme a janela do casamento — perdia herança quebrada em várias linhas e perdia
`ManyToManyField`. O Django já sabe o que está registrado e como os models se
ligam. Perguntar a ele é a única enumeração que não envelhece com o estilo do
código.

**Por que a aresta de `core.User` é proibida.** Sem essa proibição, a busca por
"alcança `Patient`?" devolve 47 views, das quais 46 chegam lá por
``created_by → core.User → patient_portal.PatientPortalAccess → Patient``. Quem
cria um registro não é o paciente do registro: a aresta existe no grafo e não
existe no significado. Classificador que marca tudo não classifica nada.

**Ordem 017 — faixa 2: dado pessoal sensível fora do prontuário.** O critério
acima ("alcança `Patient`") está certo e continua como está — ele não vê o RH
porque `hr.Employee → core.User` é a mesma aresta proibida, vista do outro lado.
Mas dado pessoal sensível (LGPD art. 5º II: saúde, gravidez) e dado de terceiro
não usuário existem fora do prontuário: a ficha de saúde ocupacional de um
funcionário é dado de saúde tanto quanto um laudo, e ninguém chega nela partindo
de `Patient`. Por isso `exigem_trilha()` é a união de DOIS critérios — alcança
`Patient`, OU o model está em `MODELS_SENSIVEIS` — com o mesmo motivo escrito e
testado que a 016 já exige de `ISENTAS`. **A lista é explícita, nunca heurística
de nome de campo**: o crivo por palavra-chave já foi tentado e marcou
`CostCenter.name` e `Room.name` como dado pessoal.
"""

from __future__ import annotations

#: Models cujo alcance define "leitura de prontuário".
MODELS_CLINICOS: frozenset[str] = frozenset({"emr.Patient"})

#: Arestas que NÃO carregam significado clínico (ver docstring).
ARESTAS_PROIBIDAS: frozenset[str] = frozenset({"core.User", "core.Tenant", "core.Role"})

#: Saltos máximos: o model, e no máximo um intermediário clínico deliberado.
SALTOS_MAXIMOS = 2

#: Views que alcançam `Patient` no grafo mas NÃO leem prontuário — cada uma com o
#: motivo, porque isenção sem motivo escrito vira isenção por hábito.
ISENTAS: dict[str, str] = {
    "UserDetailView": (
        "Devolve o perfil do próprio usuário autenticado. Alcança Patient porque "
        "core.User tem `patient_portal_access` — é a mesma aresta espúria de "
        "ARESTAS_PROIBIDAS, vista do outro lado (o model É User). Ler o próprio "
        "perfil não é ler prontuário."
    ),
}

#: Segundo critério de `exigem_trilha()` (ordem 017, faixa 2): models que carregam
#: dado pessoal sensível (LGPD art. 5º II) ou dado de terceiro fora do grafo de
#: `Patient` — cada um com o motivo escrito NOS CAMPOS que carregam o dado, nunca
#: por heurística de nome. Decidir que um model novo entra aqui exige escrever
#: por quê.
MODELS_SENSIVEIS: dict[str, str] = {
    "hr.LeaveRequest": (
        '`leave_type` inclui `sick` ("Afastamento médico") e `maternity` '
        '("Licença-maternidade") — dado de saúde e de gravidez, LGPD art. 5º '
        "II. `reason` é `TextField` livre onde entra diagnóstico."
    ),
    "hr.OccupationalHealthExam": (
        "`exam_type`, `result` (`fit`/`unfit`) e `certificate_reference` (o ASO) "
        "são dado de saúde ocupacional; `restrictions` é `TextField` de limitação "
        "funcional escrita — exatamente o achado clínico que o docstring do model "
        'promete não guardar ("without storing clinical findings").'
    ),
    "hr.Dependent": (
        "`full_name`, `birth_date` e `cpf` são dado pessoal de um TERCEIRO — "
        "filho ou cônjuge do funcionário — que não é usuário do sistema e nunca "
        "consentiu com o tratamento aqui."
    ),
    "hr.TimeEntry": (
        "Decisão do Imediato em 17/09: ler o ponto de alguém é vigilância "
        "laboral. Não é LGPD art. 5º II (dado sensível de saúde) — é art. 37 "
        "(o controlador mantém registro das operações de tratamento), e a "
        "trilha custa uma linha."
    ),
}

#: Models do app `hr` que NÃO exigem trilha — organização do trabalho, não
#: pessoa. Declaração explícita, com motivo, para o teste de classificação
#: completa do app `hr` (ordem 017): toda view de RH registrada no roteador é
#: OU exige trilha (e está em `MODELS_SENSIVEIS`) OU consta aqui.
MODELS_SEM_DADO_SENSIVEL: dict[str, str] = {
    "hr.Employee": (
        "O dado pessoal do funcionário vive em `core.User`. Este model só tem "
        "`hire_date`, `employment_status`, `contract_type` e datas de "
        "desligamento — é o vínculo empregatício, não a pessoa."
    ),
    "hr.WorkSchedule": (
        "Carga horária semanal e vigência efetiva — organização do trabalho. "
        "Não diz nada sobre a saúde nem sobre a vida do funcionário."
    ),
    "hr.Position": (
        "Cargo (título + CBO) é a função, não a pessoa que a ocupa. Não há "
        "campo pessoal ou de saúde neste model."
    ),
    "hr.EmployeeAssignment": (
        "Lotação: liga um funcionário a uma unidade organizacional por um "
        "período. É a estrutura de onde alguém trabalha, não dado sensível "
        "sobre quem é."
    ),
    "hr.RosterSlot": (
        "Um turno de escala (data, horário, unidade). Diz quando alguém "
        "trabalha, não algo sobre a saúde ou a vida do funcionário."
    ),
    "hr.DutyRoster": (
        "Nome, período e unidade de uma escala assistencial. Organização do "
        "trabalho do setor, sem dado pessoal de ninguém."
    ),
}


def caminho_ate_paciente(model, visto: set[str] | None = None, prof: int = 0) -> str:
    """Devolve o caminho de relações até `emr.Patient`, ou '' se não houver.

    Percorre ForeignKey, OneToOne e ManyToMany — os três, porque `TISSBatch`
    liga a guias (e portanto a pacientes) só por `ManyToManyField`, e um
    classificador que ignore M2M dá esse viewset como inofensivo.
    """
    if model is None or prof > SALTOS_MAXIMOS:
        return ""
    rotulo = f"{model._meta.app_label}.{model.__name__}"
    visto = visto if visto is not None else set()
    if rotulo in visto:
        return ""
    visto.add(rotulo)
    if rotulo in MODELS_CLINICOS:
        return "é o próprio Patient"
    for campo in model._meta.get_fields():
        alvo = getattr(campo, "related_model", None)
        if alvo is None:
            continue
        if not (campo.many_to_one or campo.one_to_one or campo.many_to_many):
            continue
        rotulo_alvo = f"{alvo._meta.app_label}.{alvo.__name__}"
        if rotulo_alvo in ARESTAS_PROIBIDAS:
            continue
        if rotulo_alvo in MODELS_CLINICOS:
            return f"{campo.name} → {rotulo_alvo}"
        sub = caminho_ate_paciente(alvo, visto, prof + 1)
        if sub:
            return f"{campo.name} → {rotulo_alvo}: {sub}"
    return ""


def _model_da_view(cls):
    qs = getattr(cls, "queryset", None)
    if qs is not None and getattr(qs, "model", None) is not None:
        return qs.model
    serializer = getattr(cls, "serializer_class", None)
    meta = getattr(serializer, "Meta", None)
    return getattr(meta, "model", None)


def _classes_do_roteador() -> list[type]:
    """Toda view class alcançável pelo roteador do Django, uma vez cada.

    Base compartilhada de `views_registradas()` e `mixin_fora_de_ordem()` — a
    mesma travessia, para não haver duas enumerações que possam divergir.
    """
    from django.urls import get_resolver

    vistas: dict[str, type] = {}

    def andar(resolver):
        for padrao in resolver.url_patterns:
            if hasattr(padrao, "url_patterns"):
                andar(padrao)
                continue
            cb = getattr(padrao, "callback", None)
            cls = getattr(cb, "cls", None) or getattr(cb, "view_class", None)
            if cls is None or cls.__name__ in vistas:
                continue
            vistas[cls.__name__] = cls

    andar(get_resolver())
    return list(vistas.values())


def views_registradas() -> list[dict]:
    """Toda view com queryset alcançável pelo roteador, com a classificação."""
    from apps.core.mixins import AuditReadMixin

    vistas: list[dict] = []
    for cls in _classes_do_roteador():
        if not hasattr(cls, "get_queryset") and not hasattr(cls, "queryset"):
            continue
        model = _model_da_view(cls)
        rotulo_model = f"{model._meta.app_label}.{model.__name__}" if model else None
        caminho = caminho_ate_paciente(model) if model else ""
        motivo_sensivel = MODELS_SENSIVEIS.get(rotulo_model, "") if rotulo_model else ""
        vistas.append(
            {
                "view": cls.__name__,
                "app": cls.__module__.split(".")[1] if cls.__module__.startswith("apps.") else "?",
                "model": rotulo_model,
                "tem_trilha": issubclass(cls, AuditReadMixin),
                "caminho": caminho,
                #: Por que esta view exige trilha — o caminho até `Patient`, ou o
                #: motivo do model sensível (ordem 017), o que existir primeiro.
                "motivo": caminho or motivo_sensivel,
            }
        )

    return sorted(vistas, key=lambda v: (v["app"], v["view"]))


def exigem_trilha() -> list[dict]:
    """Views que leem dado sensível e, por isso, devem deixar trilha.

    União dos dois critérios (ordem 017): a view alcança `emr.Patient` no grafo
    de models, OU o model dela está em `MODELS_SENSIVEIS` — descontadas as
    `ISENTAS`.
    """
    return [v for v in views_registradas() if v["motivo"] and v["view"] not in ISENTAS]


def mixin_fora_de_ordem() -> list[str]:
    """Views com `AuditReadMixin` fora da PRIMEIRA base — trilha morta em potencial.

    `issubclass(cls, AuditReadMixin)`, o que `tem_trilha` usa acima, é cego à
    POSIÇÃO na tupla de bases: continua `True` mesmo se um PR futuro empurrar o
    mixin para o fim. Nesse caso `retrieve`/`list` do DRF vencem no MRO (Method
    Resolution Order) — o `super()` de `AuditReadMixin` nunca é alcançado, e a
    trilha some sem que `tem_trilha` acuse nada. A ordem 017 exige o mixin como
    primeira base por exatamente isso; esta função é o teste desse requisito.
    """
    from rest_framework import mixins as drf_mixins

    from apps.core.mixins import AuditReadMixin

    achados: list[str] = []
    for cls in _classes_do_roteador():
        if not issubclass(cls, AuditReadMixin):
            continue
        mro = cls.__mro__
        posicao_audit = mro.index(AuditReadMixin)
        for concorrente in (drf_mixins.RetrieveModelMixin, drf_mixins.ListModelMixin):
            if concorrente in mro and mro.index(concorrente) < posicao_audit:
                achados.append(
                    f"{cls.__module__}.{cls.__name__}: {concorrente.__name__} vem "
                    "antes de AuditReadMixin na MRO — a trilha não intercepta "
                    "retrieve()/list()"
                )
    return achados
