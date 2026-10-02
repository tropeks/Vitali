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

from typing import Any

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

    vistas: dict[tuple[str, str, str | None], type] = {}

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
            vistas[(cls.__module__, cls.__name__, acao)] = cls

    andar(get_resolver())
    return [(cls, acao) for (_, _, acao), cls in vistas.items()]


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


# ─── Ordem 030: a guarda passa a enxergar view sem queryset ──────────────────

_AGREGADO = (
    "Agregado para painel gerencial: contagens, somas ou médias por período, "
    "sem nenhuma linha que identifique paciente ou pessoa."
)
_FRAMEWORK = (
    "View de framework (documentação OpenAPI, índice do router ou redirect do "
    "admin do Django): não lê dado de paciente nem de pessoa."
)
_PROPRIO_USUARIO = (
    "Devolve dado do próprio usuário autenticado (staff), não de paciente — a "
    "mesma razão de ISENTAS['UserDetailView']."
)
_CONFIG_TENANT = (
    "Configuração ou estado da clínica (tenant): módulos, plano, identidade, "
    "status. Nenhum dado de paciente ou de pessoa física na resposta."
)
_ESTOQUE = (
    "Estoque, alerta de validade ou previsão de demanda por produto. Farmácia "
    "operacional, sem paciente na resposta (faixa 3 de SECURITY.md §3.6.1)."
)
_POLLING = (
    "Tela que repinta sozinha por polling: uma linha por repintura diz que a "
    "tela estava aberta, não quem foi procurar o quê — o precedente da ordem "
    "019 (`AppointmentViewSet.today`, `board`). {detalhe}"
)
_FINANCEIRO = (
    "Financeiro sem guia (valor, status, vencimento, QR do PIX), sem dado "
    "clínico: a faixa 3 que SECURITY.md §3.6.1 já declara sem trilha de "
    "leitura. {detalhe}"
)

#: Rotas GET de view SEM ``queryset`` que não leem dado de paciente nem dado
#: pessoal sensível — chave ``"modulo.Classe"`` (a classe inteira) ou
#: ``"modulo.Classe.action"`` (uma action de ViewSet sem queryset). Qualificada
#: pelo módulo porque nome de classe se repete: ``SessionListCreateView`` existe
#: na telemedicina e na triagem, ``MeView`` no core e no portal. Mesmo contrato de
#: ``ISENTAS``: sem motivo escrito, vira isenção por hábito.
#:
#: Diferente das views com model, aqui não há grafo para classificar: uma
#: ``APIView`` não diz o que lê. Por isso o padrão é o inverso — toda rota GET
#: sem queryset exige decisão, coberta por ``AuditReadAPIViewMixin`` OU isenta
#: aqui. Nada entra por omissão.
APIVIEWS_ISENTAS: dict[str, str] = {
    # analytics e uso de IA: agregado, sem linha de pessoa
    "apps.ai.views.AIUsageView": _AGREGADO,
    "apps.analytics.views.AppointmentsByDayView": _AGREGADO,
    "apps.analytics.views.AppointmentsByStatusView": _AGREGADO,
    "apps.analytics.views.BatchThroughputView": _AGREGADO,
    "apps.analytics.views.BillingOperationalView": _AGREGADO,
    "apps.analytics.views.BillingOverviewView": _AGREGADO,
    "apps.analytics.views.DenialByInsurerView": _AGREGADO,
    "apps.analytics.views.GlosaAccuracyView": _AGREGADO,
    "apps.analytics.views.MonthlyRevenueView": _AGREGADO,
    "apps.analytics.views.OverviewView": _AGREGADO,
    "apps.analytics.views.PatientsByMonthView": _AGREGADO,
    "apps.analytics.views.WaitingTimeView": _AGREGADO,
    "apps.core.views_telemetry.WedgeTelemetryView": _AGREGADO,
    "apps.pharmacy.views.CurationReadinessView": _AGREGADO,
    "apps.analytics.views.TopProfessionalsView": (
        "Ranking de profissionais (id, nome, especialidade, número de "
        "atendimentos): dado do staff no exercício da função, sem paciente — a "
        "decisão de emr.Professional na ordem 029."
    ),
    # próprio usuário, configuração da clínica
    "apps.core.views.MeView": _PROPRIO_USUARIO,
    "apps.core.views.MeLanguageView": _PROPRIO_USUARIO,
    "apps.core.views_mfa.MFAStatusView": _PROPRIO_USUARIO,
    "apps.mobile.views.MyDevicesView": _PROPRIO_USUARIO,
    "apps.core.views.TenantFeaturesView": _CONFIG_TENANT,
    "apps.core.views_clinic.ClinicProfileView": _CONFIG_TENANT,
    "apps.core.views_platform.TenantSubscriptionView": _CONFIG_TENANT,
    "apps.core.views_onboarding.OnboardingView": _CONFIG_TENANT,
    "apps.emr.views_setup.WizardStatusView": _CONFIG_TENANT,
    "apps.core.views.TUSSSyncStatusView": _CONFIG_TENANT,
    "apps.whatsapp.views.HealthView": _CONFIG_TENANT,
    "apps.core.views_dpa.DPAStatusView": (
        "Status do DPA do tenant, com o nome de quem assinou (administrador da "
        "clínica, no ato de representá-la). Nenhum dado de paciente."
    ),
    "apps.core.views_privacy.PrivacySettingsView": (
        "Configuração de privacidade do tenant: nome e e-mail do encarregado "
        "(DPO), que a LGPD art. 41 §1º manda divulgar publicamente."
    ),
    "apps.mobile.views.AdminDeviceListView": (
        "Aparelhos registrados para push (usuário staff, token, versão). Dado do "
        "staff, sem paciente; o push de hoje é texto livre de administrador."
    ),
    "apps.mobile.views.AdminPushAuditView": (
        "Entregas de push de administrador (título, corpo, destinatário staff). "
        "Não há push clínico hoje; se passar a haver, reclassificar."
    ),
    # catálogo e agenda sem paciente
    "apps.core.views_terminology.TerminologySearchView": (
        "Autocomplete de catálogo de terminologia (CID-10 e afins): códigos e "
        "descrições publicados, sem dado de ninguém."
    ),
    "apps.triage.views.QuestionBankView": (
        "Banco estático de perguntas da triagem: o formulário, não as respostas de nenhum paciente."
    ),
    "apps.emr.views.AvailableSlotsView": (
        "Horários livres de um profissional (início, fim, disponível). Não diz "
        "quem ocupa os horários ocupados."
    ),
    "apps.patient_portal.views_transactional.MeAvailableSlotsView": (
        "Horários livres de um profissional, vistos pelo titular no portal. Não "
        "diz quem ocupa os horários ocupados."
    ),
    "apps.smart_scheduling.views.SuggestSlotsView": (
        "Horários ranqueados (início, fim, score). Usa o histórico do paciente "
        "para ranquear, mas não o devolve: a resposta só ecoa o id pedido."
    ),
    "apps.patient_portal.views_transactional.MePreConsultFormView": (
        "Esquema do formulário pré-consulta (template de catálogo) e o status da "
        "atribuição. Não devolve respostas; o envio (POST) já grava trilha."
    ),
    "apps.signatures.views.SignatureListView": (
        "Registro de assinaturas ICP: signatário (staff), sujeito do "
        "certificado, hash e tipo/id do documento. Não devolve o conteúdo do "
        "documento, que é lido com trilha pela rota própria."
    ),
    # farmácia operacional
    "apps.pharmacy.views.StockAlertsView": _ESTOQUE,
    "apps.pharmacy.views.StockAvailabilityView": _ESTOQUE,
    "apps.pharmacy.views.StockRiskView": _ESTOQUE,
    "apps.pharmacy_ai.views.DrugForecastView": _ESTOQUE,
    # FHIR e SMART sem dado de paciente
    "apps.fhir.views.CapabilityStatementView": (
        "CapabilityStatement FHIR: documento estático de capacidades do "
        "servidor, público por especificação."
    ),
    "apps.fhir.views_smart.SmartConfigurationView": (
        "Discovery SMART-on-FHIR (.well-known): endpoints e escopos suportados, "
        "público por especificação."
    ),
    "apps.fhir.views_smart.AuthorizeView": (
        "Passo de autorização OAuth do SMART: devolve um redirect com código "
        "de autorização. Não lê prontuário; a leitura vem depois, com trilha."
    ),
    "apps.fhir.views.PractitionerReadView": (
        "Cadastro do profissional em FHIR (nome, conselho, contato do usuário "
        "staff). A mesma decisão de emr.Professional na ordem 029: dado do "
        "staff no exercício da função, sem paciente."
    ),
    "apps.fhir.views.PractitionerSearchView": (
        "Busca de profissionais em FHIR. A mesma decisão de "
        "PractitionerReadView e de emr.Professional (ordem 029)."
    ),
    # portões de autorização de imagem
    "apps.patient_portal.views_imaging.MeImagingStudyAuthorizationView": (
        "Devolve 204 ou 404 sem corpo: confirma se o estudo é do titular. O "
        "estudo é listado com trilha em MeImagingStudiesView."
    ),
    "apps.patient_portal.views_imaging.MeImagingViewerAuthorizationView": (
        "Portão auth_request do nginx, chamado a cada request DICOMweb do "
        "visualizador: 204/403 sem corpo. Uma linha por request de imagem é "
        "ruído; quais estudos o leitor abriu fica na trilha da listagem "
        "(StudyListCreateView, MeImagingStudiesView) e do laudo."
    ),
    # polling
    "apps.emr.views.WaitingRoomView": _POLLING.format(
        detalhe="Sala de espera: polling de 30 s (waiting-room/page.tsx)."
    ),
    "apps.emr.views_safety.PrescriptionItemSafetyCheckView": _POLLING.format(
        detalhe=(
            "Veredito de segurança de um item de receita, polling de 2 s "
            "(SafetyBadge.tsx). O item é lido com trilha em PrescriptionItemViewSet."
        )
    ),
    "apps.emr.views_scribe.ScribeStatusView": _POLLING.format(
        detalhe=(
            "Status do scribe, polling de 2 s (ScribeButton.tsx). Ao concluir, "
            "devolve o rascunho de SOAP que a IA gerou da transcrição do próprio "
            "atendimento de quem a pediu: não é releitura de dado armazenado de "
            "outra pessoa. Quando o médico aplica o rascunho, a nota vira "
            "SOAPNote, lida com trilha."
        )
    ),
    # financeiro sem guia
    "apps.billing.views.PIXChargeView": _FINANCEIRO.format(
        detalhe="Cobrança PIX de uma consulta, com polling de 5 s (PIXModal.tsx)."
    ),
    "apps.patient_portal.views_transactional.MeReceivablesView": _FINANCEIRO.format(
        detalhe="Recebíveis em aberto do próprio titular, no portal."
    ),
    # framework
    "django.views.generic.base.RedirectView": _FRAMEWORK,
    "drf_spectacular.views.SpectacularAPIView": _FRAMEWORK,
    "drf_spectacular.views.SpectacularRedocView": _FRAMEWORK,
    "drf_spectacular.views.SpectacularSwaggerView": _FRAMEWORK,
    "rest_framework.routers.APIRootView": _FRAMEWORK,
}

#: Views sem queryset que JÁ gravavam trilha de leitura no próprio ``get()``,
#: antes da 030, cada uma no seu formato — classe → a ``action`` que grava. A
#: guarda conta como coberta e confere, no fonte do ``get()``, que a action
#: continua lá (`trilha_propria_que_sumiu()`): se alguém tirar a gravação, a
#: declaração vira mentira e reprova. Não foram migradas para
#: ``AuditReadAPIViewMixin`` porque a action própria já é contrato de quem lê a
#: trilha (e duplicar a linha por leitura não acrescenta nada).
APIVIEWS_TRILHA_PROPRIA: dict[str, str] = {
    "apps.emr.views_lis.LabOrderORMView": "lis_orm_export",
    "apps.patient_portal.views_imaging.MeImagingReportView": "portal_imaging_report_viewed",
    "apps.patient_portal.views_lab.MeLabReportPDFView": "portal_lab_report_downloaded",
}


def _sem_queryset(cls) -> bool:
    return not hasattr(cls, "get_queryset") and not hasattr(cls, "queryset")


def _kwargs_do_padrao(padrao) -> frozenset[str]:
    padrao_url = padrao.pattern
    convertidos = getattr(padrao_url, "converters", None)
    if convertidos:
        return frozenset(convertidos)
    regex = getattr(padrao_url, "regex", None)
    return frozenset(regex.groupindex) if regex is not None else frozenset()


def _rotas_get_sem_queryset() -> list[tuple[type, str | None, frozenset[str]]]:
    """``(classe, action, kwargs da URL)`` de toda rota GET cuja view não tem
    queryset. Os kwargs somam os de toda a cadeia de ``include()``."""
    from django.urls import get_resolver

    vistas: dict[tuple[str, str, str | None], tuple[type, frozenset[str]]] = {}

    def andar(resolver, kwargs_acima: frozenset[str] = frozenset()):
        for padrao in resolver.url_patterns:
            if hasattr(padrao, "url_patterns"):
                andar(padrao, kwargs_acima | _kwargs_do_padrao(padrao))
                continue
            cb = getattr(padrao, "callback", None)
            cls = getattr(cb, "cls", None) or getattr(cb, "view_class", None)
            if cls is None or not _sem_queryset(cls):
                continue
            actions = getattr(cb, "actions", None)
            if actions is not None:
                acao = actions.get("get")
                if acao is None:
                    continue
            elif hasattr(cls, "get"):
                acao = None
            else:
                continue
            chave = (cls.__module__, cls.__name__, acao)
            kwargs = kwargs_acima | _kwargs_do_padrao(padrao)
            anterior = vistas.get(chave)
            vistas[chave] = (cls, kwargs if anterior is None else anterior[1] & kwargs)

    andar(get_resolver())
    return [(cls, acao, kwargs) for (_, _, acao), (cls, kwargs) in vistas.items()]


def rotas_get_sem_queryset() -> list[dict]:
    """Toda rota GET cuja view não tem ``queryset``/``get_queryset`` (ordem 030).

    Eram invisíveis: ``_classes_do_roteador()``/``views_registradas()`` filtram
    por queryset, e ``_rotas_get_do_roteador()`` descarta ``APIView`` sem
    queryset. Medido em 27/09: 103 classes com GET, entre elas as 22 views FHIR
    de leitura de prontuário. Enumera pelo mesmo roteador, sem filtro de
    queryset, e responde por rota: coberta (a classe herda
    ``AuditReadAPIViewMixin``, que grava todo GET 2xx) ou isenta com motivo.
    """
    from apps.core.mixins import AuditReadAPIViewMixin

    rotas: list[dict] = []
    for cls, acao, kwargs in _rotas_get_sem_queryset():
        qualificado = f"{cls.__module__}.{cls.__name__}"
        chave = f"{qualificado}.{acao}" if acao else qualificado
        rotas.append(
            {
                "view": cls.__name__,
                "action": acao,
                "modulo": cls.__module__,
                "kwargs": kwargs,
                "lookup": getattr(cls, "AUDIT_LOOKUP_KWARG", None),
                "coberta": issubclass(cls, AuditReadAPIViewMixin)
                or qualificado in APIVIEWS_TRILHA_PROPRIA,
                "trilha_propria": qualificado in APIVIEWS_TRILHA_PROPRIA,
                "isenta": qualificado in APIVIEWS_ISENTAS or chave in APIVIEWS_ISENTAS,
            }
        )
    return sorted(rotas, key=lambda r: (r["modulo"], r["view"], r["action"] or ""))


def rotas_sem_queryset_nao_classificadas() -> list[dict]:
    """Rota GET sem queryset que nem grava trilha nem está isenta com motivo."""
    return [r for r in rotas_get_sem_queryset() if not r["coberta"] and not r["isenta"]]


def isencoes_de_apiview_sem_rota() -> list[str]:
    """Chaves de ``APIVIEWS_ISENTAS`` que não casam rota nenhuma, ou que isentam
    uma classe que JÁ grava trilha. Isenção órfã sobrevive ao código que a
    justificava — e depois isenta por engano a próxima view com o mesmo nome."""
    rotas = rotas_get_sem_queryset()
    qualificados = {f"{r['modulo']}.{r['view']}" for r in rotas}
    chaves = qualificados | {
        f"{r['modulo']}.{r['view']}.{r['action']}" for r in rotas if r["action"]
    }
    cobertas = {f"{r['modulo']}.{r['view']}" for r in rotas if r["coberta"]}
    return sorted(
        chave
        for chave in APIVIEWS_ISENTAS
        if chave not in chaves or any(chave.startswith(f"{c}.") or chave == c for c in cobertas)
    )


def apiview_mixin_fora_de_ordem() -> list[str]:
    """``AuditReadAPIViewMixin`` depois de ``APIView`` na MRO: o
    ``finalize_response`` do DRF vence e a trilha morre calada — o mesmo modo de
    falha de ``mixin_fora_de_ordem()``, para a ``APIView``."""
    from rest_framework.views import APIView

    from apps.core.mixins import AuditReadAPIViewMixin

    achados: set[str] = set()
    for cls, _, _ in _rotas_get_sem_queryset():
        mro = cls.__mro__
        if AuditReadAPIViewMixin in mro and mro.index(APIView) < mro.index(AuditReadAPIViewMixin):
            achados.add(
                f"{cls.__module__}.{cls.__name__}: APIView vem antes de AuditReadAPIViewMixin"
            )
    return sorted(achados)


def lookup_que_nao_casa_a_rota() -> list[str]:
    """Rota coberta cujo ``AUDIT_LOOKUP_KWARG`` não bate com a URL.

    Dois erros, os dois silenciosos: o kwarg declarado não existe na rota (a
    trilha grava ``resource_id`` vazio para sempre), ou a rota é de DETALHE
    (tem kwarg) e a view não declarou nenhum (grava ``view_record_list`` sem
    dizer qual recurso foi aberto). Estático: lê a URL e o atributo, não
    executa a view.
    """
    achados: list[str] = []
    for r in rotas_get_sem_queryset():
        if not r["coberta"] or r["trilha_propria"]:
            continue
        nome = f"{r['modulo']}.{r['view']}"
        if r["lookup"] and r["lookup"] not in r["kwargs"]:
            achados.append(
                f"{nome}: AUDIT_LOOKUP_KWARG={r['lookup']!r} não é kwarg da rota "
                f"({sorted(r['kwargs']) or 'nenhum'})"
            )
        elif not r["lookup"] and r["kwargs"]:
            achados.append(
                f"{nome}: rota de detalhe ({sorted(r['kwargs'])}) sem AUDIT_LOOKUP_KWARG"
            )
    return achados


def trilha_propria_que_sumiu() -> list[str]:
    """Entradas de ``APIVIEWS_TRILHA_PROPRIA`` cuja view não existe mais no
    roteador, ou cujo ``get()`` não menciona mais a action declarada.

    Estático, como o resto da guarda: lê o fonte do ``get()``. Não prova que a
    linha é gravada em todo GET 2xx — isso é dos testes de cada view —, mas
    reprova o caso que importa: alguém apagar a gravação e a declaração
    continuar dizendo "coberta".
    """
    import inspect

    # `Any`: são views com `get()` (a enumeração só guarda quem tem), mas o
    # roteador as devolve como `type`.
    classes: dict[str, Any] = {
        f"{cls.__module__}.{cls.__name__}": cls for cls, _, _ in _rotas_get_sem_queryset()
    }
    achados: list[str] = []
    for nome, action in APIVIEWS_TRILHA_PROPRIA.items():
        cls = classes.get(nome)
        if cls is None:
            achados.append(f"{nome}: não está mais no roteador")
            continue
        if f'"{action}"' not in inspect.getsource(cls.get):
            achados.append(f"{nome}: get() não grava mais {action!r}")
    return achados
