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

**Ordem 019 — o guarda muda de granularidade.** `tem_trilha` responde "esta
CLASSE herda `AuditReadMixin`?", mas o mixin só intercepta `retrieve`/`list`
condicionalmente. A pergunta certa, por ROTA, vive em
`apps.core.audit_coverage_routes` — `rotas_get_registradas()`/
`rotas_sem_cobertura()`, com `ACTIONS_ISENTAS`/`LIST_ALWAYS_ISENTAS`.

**Ordem 029 — a lista explícita só cobre o que alguém lembrou.** Doador de sangue
(`emr.BloodDonor`) e a sorologia RDC 34 da bolsa (`emr.BloodBagSerology`: HIV,
hepatites) entraram no Sprint H2, depois da 017, e ninguém os pôs em
`MODELS_SENSIVEIS`. Os viewsets tinham o mixin, mas a guarda os dava como "não
sensíveis" e por isso aceitava `list` sem `AUDIT_LIST_ALWAYS`: o cadastro inteiro
de doadores saía sem rastro. A classificação continua explícita, mas agora a
guarda PERGUNTA: toda view cujo model tem campo que identifica pessoa natural
(`IDENTIFICADORES_PESSOAIS`) precisa estar classificada, por um dos dois lados, com
motivo (`views_com_identificador_nao_classificadas()`). O nome do campo dispara a
pergunta e não a responde. Isso é o oposto do crivo que a 017 recusou, porque
aquele CLASSIFICAVA por nome.
"""

from __future__ import annotations

#: Models cujo alcance define "leitura de prontuário".
MODELS_CLINICOS: frozenset[str] = frozenset({"emr.Patient"})

#: Arestas que NÃO carregam significado clínico (ver docstring).
ARESTAS_PROIBIDAS: frozenset[str] = frozenset({"core.User", "core.Tenant", "core.Role"})

#: Saltos máximos até `Patient`. Medido variando o limite (revisão pós-019):
#:
#:   saltos=2:  71 views exigem trilha  (valor antigo, truncava cadeia real)
#:   saltos=3:  73  (+ IsolatedOrganismViewSet, + NursingPrescriptionItemViewSet)
#:   saltos=4:  74  (+ AntibiogramEntryViewSet)
#:   saltos=5:  74  (+0)
#:   saltos=6:  74  (+0)
#:
#: Satura em 4 — as três views novas eram prontuário de verdade (organismo
#: isolado em cultura, antibiograma, item de prescrição de enfermagem) fora
#: do crivo não por serem inofensivas, mas porque o orçamento de saltos
#: acabava antes de chegar em `Patient`. Quem barra os 46 falsos positivos da
#: 016 é `ARESTAS_PROIBIDAS` (`core.User`/`Tenant`/`Role`), não a
#: profundidade — subir até 8 não introduziu UM falso positivo (ver
#: `test_saltos_maximos_esta_saturado` em test_auditoria_leitura_cobertura.py,
#: que trava isso: subir +2 não pode acrescentar view nenhuma). 6 = saturação
#: (4) + margem de 2, mesma folga proporcional que os pisos de enumeração já
#: usam.
SALTOS_MAXIMOS = 6

#: Views que alcançam `Patient` no grafo mas NÃO leem prontuário — cada uma com o
#: motivo, porque isenção sem motivo escrito vira isenção por hábito.
ISENTAS: dict[str, str] = {
    "UserDetailView": (
        "Devolve o perfil do próprio usuário autenticado. Alcança Patient porque "
        "core.User tem `patient_portal_access` — é a mesma aresta espúria de "
        "ARESTAS_PROIBIDAS, vista do outro lado (o model É User). Ler o próprio "
        "perfil não é ler prontuário."
    ),
    "UserListCreateView": (
        "Lista/cria usuários (staff) do tenant. Alcança Patient pela MESMA "
        "aresta espúria de UserDetailView (core.User → patient_portal_access) "
        "— o model É User, não um paciente. Revisão pós-019: só ficou visível "
        "depois que VIEW_MODEL_OVERRIDES passou a resolver o model desta view; "
        "antes disso o guarda simplesmente não via a rota, e a isenção nunca "
        "tinha sido decidida."
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
    "emr.BloodDonor": (
        "Ordem 029. `full_name`, `cpf` e `birth_date` identificam um TERCEIRO que "
        "não é paciente (o doador); `apto` e `notes` carregam a inaptidão a doar, "
        "e `abo`/`rh_factor` o tipo sanguíneo — dado de saúde, LGPD art. 5º II. "
        "Fora do grafo de Patient: o doador não tem FK para ninguém."
    ),
    "emr.BloodBagSerology": (
        "Ordem 029. `hiv`, `hbsag`, `anti_hbc`, `anti_hcv`, `sifilis`, `chagas` e "
        "`htlv` (painel RDC 34) são dado de saúde do doador daquela bolsa, LGPD "
        "art. 5º II. A bolsa liga pelo DIN, identificador de doação que o serviço "
        "de hemoterapia reassocia ao doador (a RDC 34 manda convocar o reagente). "
        "Reversível, então não é anonimizado (LGPD art. 12): é pseudonimizado, no "
        "sentido do art. 13 §4º, e continua dado pessoal."
    ),
}

#: Models que NÃO exigem trilha — organização do trabalho, não pessoa.
#: Declaração explícita, com motivo, para dois testes de classificação: o do
#: app `hr` (ordem 017), onde toda view registrada no roteador exige trilha OU
#: consta aqui; e o de `IDENTIFICADORES_PESSOAIS` (ordem 029), onde todo model
#: servido com campo que identifica pessoa natural é sensível OU consta aqui.
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
    "emr.Professional": (
        "Ordem 029 (a pergunta de IDENTIFICADORES_PESSOAIS disparou pelo `cns`). "
        "O `ProfessionalSerializer` NÃO devolve o `cns` — cifrado em repouso, só o "
        "BPA/APAC o consome. A rota devolve conselho, especialidade, CBO e CNES do "
        "profissional no exercício da função; nome e e-mail vêm de `core.User` "
        "(staff, ver ISENTAS). Nenhum dado de saúde."
    ),
    "pharmacy.Supplier": (
        "Ordem 029 (a pergunta disparou por `contact_email`/`contact_phone`). O "
        "fornecedor é pessoa jurídica (`cnpj`); `contact_name`/`contact_email`/"
        "`contact_phone` são o contato comercial do representante. É dado pessoal "
        "comum (LGPD art. 5º I), não sensível, e não é de paciente: fora do "
        "critério de trilha de leitura da Prioridade 4."
    ),
}

#: Ordem 029 — campos que identificam uma pessoa natural. NÃO classificam: um
#: model com um deles, servido por view, só obriga alguém a DECIDIR (e escrever)
#: se o dado é sensível — `MODELS_SENSIVEIS` ou `MODELS_SEM_DADO_SENSIVEL`. Casa
#: o nome exato OU o sufixo `_<nome>` (`contact_phone`, `donor_cpf`,
#: `patient_full_name`); ver `_campos_identificadores`. Nomes inequívocos de
#: pessoa, de propósito: `name`/`nome`/`address` ficam de fora, nem por sufixo,
#: porque sala, centro de custo e clínica também têm (a lição da 017).
IDENTIFICADORES_PESSOAIS: frozenset[str] = frozenset(
    {
        "cpf",
        "rg",
        "cns",
        "birth_date",
        "full_name",
        "mother_name",
        "phone",
        "telefone",
        "email",
    }
)


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


#: Correção pós-019: views cujo `queryset`/`serializer_class` são só métodos
#: dinâmicos (`get_queryset`/`get_serializer_class`), sem atributo estático de
#: fallback — `_model_da_view` não enxerga essas e a view fica INVISÍVEL a
#: `exigem_trilha()`. Sem isto, `PatientViewSet` e `EncounterViewSet` — os
#: dois models mais centrais do prontuário — só tinham `AuditReadMixin` por
#: decisão de quem escreveu a view, não porque o guarda exigisse; se o mixin
#: fosse removido amanhã, nada acusaria. `PriceTableViewSet` e
#: `UserListCreateView` têm o MESMO padrão (achadas na revisão seguinte) —
#: `UserListCreateView` importa de verdade: uma vez visível, o model dela É
#: `core.User`, que alcança Patient pela aresta espúria de
#: `ISENTAS["UserDetailView"]`, e por isso ganhou entrada própria em
#: `ISENTAS` (não vale supor "provavelmente inofensiva" — o motivo tem que
#: estar escrito). Escrito à mão, mesmo espírito de `MODELS_SENSIVEIS`:
#: explícito, nunca inferido chamando o método às cegas.
#:
#: Isto tapa sintomas, não a causa — por isso
#: `test_toda_view_resolve_model_ou_esta_declarada_sem_model` (ver
#: `VIEWS_SEM_MODEL` abaixo) é o guarda permanente: toda view enumerada
#: RESOLVE um model (aqui ou nos atributos estáticos) OU está declarada como
#: "sem model" com motivo. Uma sétima view deste padrão não desaparece mais
#: em silêncio — reprova até alguém decidir.
VIEW_MODEL_OVERRIDES: dict[str, str] = {
    "PatientViewSet": "emr.Patient",
    "EncounterViewSet": "emr.Encounter",
    "TISSGuideViewSet": "billing.TISSGuide",
    "PriceTableViewSet": "billing.PriceTable",
    "UserListCreateView": "core.User",
}

#: Views que passam no filtro `get_queryset`/`queryset` de `views_registradas()`
#: mas GENUINAMENTE não têm model — não é um buraco do classificador, é a view
#: não ser um recurso de banco. Cada uma com motivo, mesmo contrato de
#: `ISENTAS`: sem isto, `test_toda_view_resolve_model_ou_esta_declarada_sem_model`
#: falharia para qualquer view deste tipo, inclusive as legítimas.
VIEWS_SEM_MODEL: dict[str, str] = {
    "TokenRefreshView": (
        "POST /auth/refresh — wrapper do SimpleJWT. `queryset = None` é o "
        "default herdado de `GenericAPIView`, não um recurso real; a view não "
        "lê nem lista nada, só troca um token por outro."
    ),
}


def _model_da_view(cls):
    rotulo_override = VIEW_MODEL_OVERRIDES.get(cls.__name__)
    if rotulo_override:
        from django.apps import apps as django_apps

        return django_apps.get_model(rotulo_override)
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


def views_sem_model_nao_declaradas() -> list[dict]:
    """Views que `_model_da_view` não resolve e que NÃO estão em `VIEWS_SEM_MODEL`.

    Fecha a classe do defeito, não a instância: `PatientViewSet`,
    `EncounterViewSet`, `TISSGuideViewSet`, `PriceTableViewSet` e
    `UserListCreateView` tinham o MESMO padrão (só `get_queryset`/
    `get_serializer_class` dinâmicos) e cada uma só apareceu depois de alguém
    ir procurar à mão. Sem este guarda, uma sexta view assim nasce invisível a
    `exigem_trilha()` de novo — não é isenta, é INVISÍVEL, e ninguém decidiu.
    """
    achados: list[dict] = []
    for v in views_registradas():
        if v["model"] is None and v["view"] not in VIEWS_SEM_MODEL:
            achados.append(v)
    return achados


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


def _campos_identificadores(model) -> list[str]:
    """Campos concretos do model que casam `IDENTIFICADORES_PESSOAIS`, por nome
    exato ou por sufixo `_<identificador>` (revisão da 029: `Supplier` tinha
    `contact_phone`/`contact_email` e escapava do casamento exato)."""
    achados = []
    for campo in model._meta.concrete_fields:
        nome = campo.name
        if nome in IDENTIFICADORES_PESSOAIS or any(
            nome.endswith(f"_{ident}") for ident in IDENTIFICADORES_PESSOAIS
        ):
            achados.append(nome)
    return sorted(achados)


def views_com_identificador() -> list[dict]:
    """Toda view registrada cujo model tem campo de `IDENTIFICADORES_PESSOAIS`.

    Olha só os campos concretos do próprio model (`concrete_fields`), nunca os
    do model alcançado por FK: o dado do usuário que criou o registro é
    `core.User`, a mesma aresta espúria de `ARESTAS_PROIBIDAS`.
    """
    from django.apps import apps as django_apps

    achadas: list[dict] = []
    for v in views_registradas():
        if v["model"] is None:
            continue
        identificadores = _campos_identificadores(django_apps.get_model(v["model"]))
        if identificadores:
            achadas.append({**v, "identificadores": identificadores})
    return achadas


def views_com_identificador_nao_classificadas() -> list[dict]:
    """Views com identificador de pessoa que ninguém classificou (ordem 029).

    Classificada = tem `motivo` (alcança `Patient` ou está em
    `MODELS_SENSIVEIS`), OU está em `ISENTAS`, OU o model está em
    `MODELS_SEM_DADO_SENSIVEL`. O resto é a próxima tabela de doador: dado de
    pessoa fora do grafo de `Patient` que a guarda não exigiria.
    """
    return [
        v
        for v in views_com_identificador()
        if not v["motivo"]
        and v["view"] not in ISENTAS
        and v["model"] not in MODELS_SEM_DADO_SENSIVEL
    ]
