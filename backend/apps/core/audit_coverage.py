"""Quais views precisam deixar trilha de leitura — e por quê (ordem 016).

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


def views_registradas() -> list[dict]:
    """Toda view com queryset alcançável pelo roteador, com a classificação."""
    from django.urls import get_resolver

    from apps.core.mixins import AuditReadMixin

    vistas: dict[str, dict] = {}

    def andar(resolver):
        for padrao in resolver.url_patterns:
            if hasattr(padrao, "url_patterns"):
                andar(padrao)
                continue
            cb = getattr(padrao, "callback", None)
            cls = getattr(cb, "cls", None) or getattr(cb, "view_class", None)
            if cls is None or cls.__name__ in vistas:
                continue
            if not hasattr(cls, "get_queryset") and not hasattr(cls, "queryset"):
                continue
            model = _model_da_view(cls)
            vistas[cls.__name__] = {
                "view": cls.__name__,
                "app": cls.__module__.split(".")[1] if cls.__module__.startswith("apps.") else "?",
                "model": f"{model._meta.app_label}.{model.__name__}" if model else None,
                "tem_trilha": issubclass(cls, AuditReadMixin),
                "caminho": caminho_ate_paciente(model) if model else "",
            }

    andar(get_resolver())
    return sorted(vistas.values(), key=lambda v: (v["app"], v["view"]))


def exigem_trilha() -> list[dict]:
    """Views que leem dado ligado a paciente e, por isso, devem deixar trilha."""
    return [v for v in views_registradas() if v["caminho"] and v["view"] not in ISENTAS]
