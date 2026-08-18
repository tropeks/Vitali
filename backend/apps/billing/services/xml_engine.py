"""
TISS XML Engine
================
Generates and validates TISS 4.01.00 XML for guides and batches.

Design notes:
- Uses Jinja2 for templating (already installed with Django; no extra dep).
  Templates live in apps/billing/templates/tiss/*.xml.j2.
- Validates against the ANS XSD schema using lxml. The XSD file must be
  placed at apps/billing/schemas/tissV4_01_00.xsd.
  Download from: https://www.ans.gov.br/images/stories/Prestadores/padrao_tiss.zip
- Path is absolute (relative paths break when cwd != project root).
- If the XSD file is absent, validate_xml() returns a warning rather than
  crashing — useful in development before the schema file is added.
"""

import datetime
import hashlib
import logging
from decimal import Decimal
from pathlib import Path

from django.db.models import Q
from django.utils import timezone
from jinja2 import Environment, FileSystemLoader, select_autoescape

from apps.billing.models import Authorization

logger = logging.getLogger(__name__)


class TISSXMLGenerationError(Exception):
    """Raised when a guide/batch cannot be rendered into schema-valid TISS XML.

    Fail loud instead of silently emitting XML for the wrong guide type (or XML
    that structurally cannot satisfy the ANS XSD) — see the "honorários guide
    falls through to the consulta template" gap fixed by this exception.
    """


# ─── Paths ────────────────────────────────────────────────────────────────────

_BILLING_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = _BILLING_DIR / "templates" / "tiss"
TISS_XSD_PATH = _BILLING_DIR / "schemas" / "tissV4_01_00.xsd"

# ─── Jinja2 environment ───────────────────────────────────────────────────────


def _make_jinja_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    # Custom filters
    env.filters["format_date"] = _format_date
    env.filters["format_time"] = _format_time
    env.filters["format_decimal"] = _format_decimal
    env.filters["format_currency"] = _format_currency
    env.filters["conselho_ans_code"] = _conselho_ans_code
    env.filters["uf_ibge_code"] = _uf_ibge_code
    return env


_jinja_env: Environment | None = None


def _env() -> Environment:
    global _jinja_env
    if _jinja_env is None:
        _jinja_env = _make_jinja_env()
    return _jinja_env


# ─── Jinja2 filters ───────────────────────────────────────────────────────────


def _format_date(value) -> str:
    """Convert date/datetime to TISS format YYYY-MM-DD."""
    if hasattr(value, "date"):
        value = value.date()
    return value.strftime("%Y-%m-%d") if value else ""


def _format_time(value) -> str:
    """Convert datetime to TISS format HH:MM:SS."""
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M:%S")
    return "00:00:00"


def _format_decimal(value) -> str:
    """Format quantity with 2 decimal places."""
    return f"{Decimal(str(value)):.2f}"


def _format_currency(value) -> str:
    """Format monetary value with 2 decimal places."""
    return f"{Decimal(str(value)):.2f}"


# dm_conselhoProfissional (tissSimpleTypesV4_01_00.xsd) — closed 2-digit ANS
# enumeration for professional councils. apps.emr.Professional.council_type
# stores the council acronym (CRM, COREN, ...); this maps it to the code the
# XSD actually requires. Keys are the exact values in
# apps.emr.models.Professional.COUNCIL_CHOICES.
_CONSELHO_ANS_CODE = {
    "CRESS": "01",
    "COREN": "02",
    "CRF": "03",
    "CRFA": "04",
    "CREFITO": "05",
    "CRM": "06",
    "CRN": "07",
    "CRO": "08",
    "CRP": "09",
}

# dm_UF (tissSimpleTypesV4_01_00.xsd) — closed 2-digit IBGE state code
# enumeration. Professional.council_state stores the 2-letter UF (SP, RJ...);
# this maps it to the IBGE numeric code the XSD requires.
_UF_IBGE_CODE = {
    "RO": "11",
    "AC": "12",
    "AM": "13",
    "RR": "14",
    "PA": "15",
    "AP": "16",
    "TO": "17",
    "MA": "21",
    "PI": "22",
    "CE": "23",
    "RN": "24",
    "PB": "25",
    "PE": "26",
    "AL": "27",
    "SE": "28",
    "BA": "29",
    "MG": "31",
    "ES": "32",
    "RJ": "33",
    "SP": "35",
    "PR": "41",
    "SC": "42",
    "RS": "43",
    "MS": "50",
    "MT": "51",
    "GO": "52",
    "DF": "53",
}


def _conselho_ans_code(council_type: str) -> str:
    """Map Professional.council_type (CRM, COREN, ...) to dm_conselhoProfissional."""
    return _CONSELHO_ANS_CODE.get(council_type, "")


def _uf_ibge_code(uf: str) -> str:
    """Map a 2-letter UF (SP, RJ, ...) to the dm_UF IBGE numeric code."""
    return _UF_IBGE_CODE.get((uf or "").upper(), "")


def _resolve_internacao_authorization(guide) -> tuple[str, datetime.date] | None:
    """Resolve (senha, dataAutorizacao) for ctm_internacaoResumoGuia's mandatory
    ``dadosAutorizacao`` (ct_autorizacaoInternacao — both ``dataAutorizacao`` and
    ``senha`` are required children, no minOccurs="0"; see
    tissComplexTypesV4_01_00.xsd:77-85).

    REUSES the authorization-resolution rule the glosa-safety engine already
    applies to decide whether a billed line is covered (glosa wedge G3d) —
    same precedence, not a second divergent rule: an approved, in-window
    ``Authorization`` row (patient + provider + status=APPROVED + valid_from
    <= effective date <= valid_until-or-open) with either a matching
    ``tuss_code`` or a generic (NULL) ``tuss_code`` "covers" the guide — see
    ``GlosaSafetyService._approved_authorization_coverage``
    (apps/billing/services/glosa_safety.py:401-432) and the rule as documented
    on the models themselves (models.py:165-176 PriceTableItem.
    requires_authorization docstring; models.py:196-199 Authorization
    docstring). Effective date mirrors that service's primary branch
    (``_guide_effective_date``, glosa_safety.py:338-351): the guide's own
    ``created_at`` date (``auto_now_add`` — always set once saved).

    Unlike the glosa engine (which only needs a yes/no "is this line
    covered"), the XSD wants a concrete ``senha`` + ``dataAutorizacao`` pair,
    so this picks ONE row: prefer a match on one of the guide's item TUSS
    codes, else a generic row, else none. ``senha`` prefers the guide's own
    ``authorization_number`` (TISSGuide.authorization_number, models.py:367)
    when set — it IS the senha regardless of whether an Authorization row
    also exists — and falls back to the resolved row's own
    ``authorization_number``.

    PRECEDENCE (decisão do Capitão, B10) — an approved ``Authorization`` row
    ALWAYS wins over manual digitação when both exist:

    1. A resolvable ``Authorization`` row (as above) → its ``valid_from`` is
       the ``dataAutorizacao``. The registered authorization is the more
       trustworthy source (it went through the operadora's own approval
       workflow and is reused across every guide it covers), so it takes
       priority whenever it resolves — manual digitação never overrides it.
    2. No resolvable row → fall back to the pair typed directly on the guide,
       ``(TISSGuide.authorization_number, TISSGuide.authorization_date)``
       (models.py). This is honest digitação-by-the-faturista of what the
       operadora communicated (phone/portal) when there is no Authorization
       record yet — a fallback of last resort, never an override.
    3. Neither branch produces a COMPLETE ``senha`` + ``dataAutorizacao``
       pair → return None; the caller fails loud instead of fabricating a
       date (e.g. ``authorization_number`` typed with no
       ``authorization_date`` and no matching ``Authorization`` row still
       gives a senha but no honest date).
    """
    effective_date = guide.created_at.date()
    guide_tuss_ids = {item.tuss_code_id for item in guide.items.all()}

    rows = list(
        Authorization.objects.filter(
            patient_id=guide.patient_id,
            provider_id=guide.provider_id,
            status=Authorization.Status.APPROVED,
            valid_from__lte=effective_date,
        )
        .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=effective_date))
        .order_by("-valid_from")
    )

    resolved = next((r for r in rows if r.tuss_code_id in guide_tuss_ids), None)
    if resolved is None:
        resolved = next((r for r in rows if r.tuss_code_id is None), None)

    guide_senha = (guide.authorization_number or "").strip()

    if resolved is not None:
        # Branch 1: registered Authorization wins — senha still prefers the
        # guide's own typed number when present (it IS the senha regardless),
        # but the DATE always comes from the resolved row, never from
        # guide.authorization_date.
        senha = guide_senha or resolved.authorization_number
        data_autorizacao = resolved.valid_from
    else:
        # Branch 2: no registered Authorization resolves — fall back to the
        # manually-typed pair. Both must come from the SAME source (the
        # guide) so we never mix a typed senha with an unrelated date.
        senha = guide_senha
        data_autorizacao = guide.authorization_date

    if not senha or data_autorizacao is None:
        return None
    return senha, data_autorizacao


def _local_datetime(value: datetime.datetime) -> datetime.datetime:
    """Converte um datetime aware para o fuso da clínica (``settings.TIME_ZONE``).

    Os campos ``st_data``/``st_hora`` do TISS são data e hora LOCAIS, sem offset
    (``xs:date``/``xs:time`` emitidos como ``YYYY-MM-DD``/``HH:MM:SS``). Django
    guarda ``DateTimeField`` em UTC (``USE_TZ=True``); formatar direto o valor
    aware faz uma internação das 21h de São Paulo virar ``00:00:00`` do DIA
    SEGUINTE no documento enviado à operadora — deslocamento silencioso de um
    dia inteiro de estada, que só apareceria como glosa. Mesmo cuidado que o
    commit 8a32034 tomou com ``authorization_date`` no frontend.

    Mesma forma dos precedentes do repo (``apps/hr/roster_integration.py``,
    ``apps/emr/rh_models.py``): valores naive passam intactos, porque não há de
    que converter.
    """
    if timezone.is_aware(value):
        return timezone.localtime(value)
    return value


def _resolve_internacao_dados(guide) -> dict:
    """Resolve ``dadosInternacao`` (ctm_internacaoDados) e ``dadosSaidaInternacao``
    (ctm_internacaoDadosSaida) da guia de resumo de internação.

    MEDIÇÃO (lxml sobre ``apps/billing/schemas/tissGuiasV4_01_00.xsd``, não
    leitura a olho — o arquivo é ISO-8859-1 com linhas de dezenas de KB e grep
    mente por omissão). ``ctm_internacaoDados`` tem OITO filhos obrigatórios em
    sequência, não quatro como o doc de pesquisa §3 listava::

        caraterAtendimento     dm_caraterAtendimento  <- admission.carater_atendimento
        tipoFaturamento        dm_tipoFaturamento     <- guide.tipo_faturamento
        dataInicioFaturamento  st_data                <- admission.admission_datetime
        horaInicioFaturamento  st_hora                <- admission.admission_datetime
        dataFinalFaturamento   st_data                <- admission.actual_discharge_datetime
        horaFinalFaturamento   st_hora                <- admission.actual_discharge_datetime
        tipoInternacao         dm_tipoInternacao      <- admission.tipo_internacao
        regimeInternacao       dm_regimeInternacao    <- admission.regime_internacao
        declaracoes            minOccurs=0            (opcional — não emitido)

    e ``ctm_internacaoDadosSaida`` pede ``diagnostico`` (opcional, não emitido),
    ``indicadorAcidente`` (obrigatório, sem fonte no model — default documentado
    ``"9"`` = não acidente, o mesmo já usado em ``consulta_guide.xml.j2``) e
    ``motivoEncerramento`` (<- ``admission.disposition_ans_code``).

    DIVERGE de ``_resolve_internacao_authorization`` num ponto, de propósito:
    aquele resolver devolve ``None`` e deixa o chamador levantar, porque tem UM
    único modo de falha ("não há par senha+data honesto"). Aqui há SEIS fontes
    independentes que podem faltar, em TRÊS telas diferentes (admissão, alta,
    guia) — devolver ``None`` apagaria justamente a informação que o faturista
    precisa. Então este levanta ``TISSXMLGenerationError`` direto, com a
    mensagem já apontando o que preencher e onde. A regra de fundo é a mesma:
    **nunca fabricar dado**; nenhum destes campos ganha default silencioso.

    Falhas, em ordem de precedência (a primeira que bate interrompe):

    1. ``guide.admission`` vazio. A guia de resumo de internação DESCREVE uma
       estada; sem o vínculo não há nem data de início. É estrutural, não é
       campo em branco — por isso vem antes de tudo e tem mensagem própria.
    2. Internação ainda sem alta (``actual_discharge_datetime`` nulo).
       ``dataFinalFaturamento``/``horaFinalFaturamento`` são obrigatórios; a
       única fonte honesta é a alta efetiva. Isso é a verdade do fluxo atual —
       ``generate_internacao_guide_for_admission`` fatura a estada inteira de
       uma vez — e não um limite artificial: faturar "até agora" uma internação
       aberta exigiria um ciclo parcial que o Vitali não tem (ver o risco aberto
       registrado em docs/research/VITALI_ONDA4_TISS_MODELAGEM.md §8).
    3. Taxonomias em branco. Todas são ``blank=True`` (internações e guias
       anteriores à Onda 4 não as têm), então a checagem é campo a campo — mas
       relatadas TODAS DE UMA VEZ numa só exceção, com o nome do campo e a tela
       que o preenche. Uma exceção por campo faria o faturista descobrir os
       quatro buracos em quatro tentativas.

    ISOLAMENTO MULTI-TENANT: ``guide.admission`` é FK mesma-schema
    (``apps.billing`` e ``apps.emr`` são ambos ``TENANT_APPS``, settings/base.py)
    — a travessia resolve pelo ``search_path`` do schema do tenant corrente, o
    mesmo caminho que ``guide.patient``/``guide.encounter`` já usam neste módulo.
    Não há query nova por ``Admission.objects`` (que também seria escopada, mas
    abriria a porta para um filtro esquecido), não há UUID solto e não há import
    de ``apps.emr`` — só leitura de atributo no FK já existente.
    """
    admission = guide.admission
    if admission is None:
        raise TISSXMLGenerationError(
            f"Guia de resumo de internação {guide.guide_number} não está vinculada "
            "a nenhuma internação: dadosInternacao (ctm_internacaoDados, "
            "tissGuiasV4_01_00.xsd) exige caráter, tipo e regime da internação e o "
            "período de faturamento (datas/horas de início e fim), que só existem "
            "na internação. Gere a guia pela ponte internação→faturamento "
            "(POST /api/v1/billing/guides/from-admission/, que preenche o vínculo) "
            "em vez de criar uma guia de internação avulsa."
        )

    if admission.actual_discharge_datetime is None:
        raise TISSXMLGenerationError(
            f"Guia de resumo de internação {guide.guide_number} é de uma internação "
            "ainda ABERTA (sem alta efetiva registrada): dataFinalFaturamento e "
            "horaFinalFaturamento (ctm_internacaoDados) são obrigatórios e a única "
            "fonte honesta deles é a alta. A guia de resumo só fecha depois da alta "
            "— dê a alta do paciente (tela de internação) e gere o XML em seguida. "
            "Faturamento parcial de internação em andamento não existe no fluxo "
            "atual; se o negócio precisar dele, é ciclo de vida novo, não um campo."
        )

    # (valor, nome do campo, onde se preenche) — ordem = ordem da sequência no XSD.
    required = [
        (
            admission.carater_atendimento,
            "carater_atendimento (dm_caraterAtendimento)",
            "na internação, tela de admissão do paciente",
        ),
        (
            guide.tipo_faturamento,
            "tipo_faturamento (dm_tipoFaturamento)",
            "nesta guia, enquanto ainda estiver em rascunho",
        ),
        (
            admission.tipo_internacao,
            "tipo_internacao (dm_tipoInternacao)",
            "na internação, tela de admissão do paciente",
        ),
        (
            admission.regime_internacao,
            "regime_internacao (dm_regimeInternacao)",
            "na internação, tela de admissão do paciente",
        ),
        (
            admission.disposition_ans_code,
            "disposition_ans_code (dm_motivoSaida)",
            "na internação, tela de alta — é o motivo de encerramento ANS, "
            "ao lado do desfecho clínico",
        ),
    ]
    faltando = [
        f"- {campo}: preencha {onde}."
        for valor, campo, onde in required
        if not (valor or "").strip()
    ]
    if faltando:
        raise TISSXMLGenerationError(
            f"Guia de resumo de internação {guide.guide_number} não tem os dados "
            "obrigatórios de internação/saída (ctm_internacaoDados e "
            "ctm_internacaoDadosSaida, tissGuiasV4_01_00.xsd). Falta(m):\n"
            + "\n".join(faltando)
            + "\nNenhum destes tem default seguro — declarar um caráter, tipo, "
            "regime, motivo de encerramento ou tipo de faturamento errado à "
            "operadora é pior que não enviar a guia."
        )

    inicio = _local_datetime(admission.admission_datetime)
    fim = _local_datetime(admission.actual_discharge_datetime)
    return {
        "internacao_carater_atendimento": admission.carater_atendimento,
        "internacao_tipo_faturamento": guide.tipo_faturamento,
        "internacao_inicio": inicio,
        "internacao_fim": fim,
        "internacao_tipo": admission.tipo_internacao,
        "internacao_regime": admission.regime_internacao,
        "internacao_motivo_encerramento": admission.disposition_ans_code,
    }


# ─── Guide XML generation ─────────────────────────────────────────────────────


_TEMPLATE_BY_GUIDE_TYPE = {
    "consulta": "consulta_guide.xml.j2",
    "sadt": "sadt_guide.xml.j2",
    "internacao": "internacao_guide.xml.j2",
    # "honorarios" is intentionally ABSENT: no ctm_honorarioIndividualGuia
    # template exists yet (see TISSXMLGenerationError below). It used to fall
    # through to consulta_guide.xml.j2 via a dict .get() default, silently
    # emitting a wrong guide type — 2.8 closes that hole.
}


def generate_guide_xml(guide) -> str:
    """
    Generate the XML fragment for a single TISSGuide.
    Returns the rendered XML string (no envelope, no XSD declaration).

    Raises TISSXMLGenerationError for guide types with no schema-conformant
    template (currently "honorarios") or with data the ANS XSD requires but
    the guide does not have (e.g. more than one procedure on a guia de
    consulta, which the XSD models as exactly one <procedimento>).
    """
    template_name = _TEMPLATE_BY_GUIDE_TYPE.get(guide.guide_type)
    if template_name is None:
        raise TISSXMLGenerationError(
            f"guide_type={guide.guide_type!r} has no TISS XML template. "
            "Rendering it as another guide type would silently produce the "
            "wrong ANS guide — see billing/models.py TISSGuide.guide_type "
            "choices and apps/billing/templates/tiss/."
        )
    template = _env().get_template(template_name)

    # Resolve professional from encounter
    professional = None
    try:
        professional = guide.encounter.professional
    except Exception:
        pass

    context: dict = {"guide": guide, "professional": professional}

    if guide.guide_type == "consulta":
        # ctm_consultaGuia (tissGuiasV4_01_00.xsd) models exactly ONE
        # <procedimento> per guia de consulta — not a repeatable list. Fail
        # loud rather than silently dropping items or emitting an invalid
        # repeated element.
        items = list(guide.items.all())
        if len(items) != 1:
            raise TISSXMLGenerationError(
                f"Guia de consulta {guide.guide_number} tem {len(items)} item(ns); "
                "o XSD TISS 4.01.00 (ctm_consultaGuia) permite exatamente um "
                "<procedimento> por guia de consulta."
            )
        context["item"] = items[0]

    if guide.guide_type == "internacao":
        # dadosAutorizacao (ct_autorizacaoInternacao) is mandatory — see
        # _resolve_internacao_authorization for the resolution rule reused
        # from the glosa-safety engine. Fail loud rather than emit a guide
        # with a fabricated date when no honest source resolves.
        resolved_auth = _resolve_internacao_authorization(guide)
        if resolved_auth is None:
            raise TISSXMLGenerationError(
                f"Guia de resumo de internação {guide.guide_number} não tem "
                "autorização resolvível: ct_autorizacaoInternacao exige "
                "dataAutorizacao E senha (tissComplexTypesV4_01_00.xsd, "
                "ct_autorizacaoInternacao). Para corrigir, faça UMA das duas "
                "coisas: (1) registre uma Authorization aprovada cobrindo "
                "este paciente/operadora/janela (genérica ou por TUSS) — é a "
                "fonte preferida e cobre qualquer guia futura da mesma "
                "autorização; ou (2) preencha, nesta guia (enquanto ainda "
                "estiver em rascunho), tanto authorization_number (senha) "
                "quanto authorization_date (data informada pela operadora) — "
                "os dois campos juntos, um sozinho não basta."
            )
        context["autorizacao_senha"], context["autorizacao_data"] = resolved_auth

        # dadosInternacao (ctm_internacaoDados) + dadosSaidaInternacao
        # (ctm_internacaoDadosSaida) — os dois blocos obrigatórios que vêm logo
        # depois de dadosExecutante na sequência. Mesma política do bloco de
        # autorização: falha alta e acionável em vez de XML com dado inventado.
        context.update(_resolve_internacao_dados(guide))

    return template.render(**context)


# ─── Batch XML generation ─────────────────────────────────────────────────────


def generate_batch_xml(batch) -> str:
    """
    Generate the full TISS batch XML envelope for a TISSBatch.
    Includes all guides in the batch. Returns the complete XML string.
    """
    template = _env().get_template("batch_envelope.xml.j2")

    guides = list(batch.guides.select_related("patient", "provider", "encounter").all())

    # ctm_guiaLote (tissGuiasV4_01_00.xsd) wraps <guiasTISS> in a <choice>: a
    # single lote may contain guides of exactly ONE ANS guide type (repeated),
    # not a mix. A mixed-type batch cannot be expressed as one schema-valid
    # <guiasTISS> element — fail loud instead of emitting an invalid document.
    guide_types = {guide.guide_type for guide in guides}
    if len(guide_types) > 1:
        raise TISSXMLGenerationError(
            f"Lote {batch.batch_number} mistura tipos de guia {sorted(guide_types)}; "
            "o XSD TISS 4.01.00 (ctm_guiaLote/guiasTISS) exige um único tipo de "
            "guia por lote. Separe em lotes homogêneos antes de gerar o XML."
        )

    # Generate each guide's XML fragment
    guide_xml: dict[str, str] = {}
    for guide in guides:
        try:
            guide_xml[guide.guide_number] = generate_guide_xml(guide)
        except Exception as exc:
            logger.error("Failed to generate XML for guide %s: %s", guide.guide_number, exc)
            guide_xml[guide.guide_number] = f"<!-- ERROR guide {guide.guide_number}: {exc} -->"

    # Clinic CNES — derive from first guide's professional CNES if available
    clinic_cnes = ""
    if guides:
        try:
            clinic_cnes = guides[0].encounter.professional.cnes_code or ""
        except Exception:
            pass

    now = timezone.now()
    rendered = template.render(
        batch=batch,
        guides=guides,
        guide_xml=guide_xml,
        clinic_cnes=clinic_cnes,
        now=now,
        xml_hash="",  # placeholder — hash computed below
    )

    # Compute MD5 hash of the content body for epilogo (TISS spec)
    content_hash = hashlib.md5(rendered.encode()).hexdigest()
    rendered = rendered.replace("<ans:hash></ans:hash>", f"<ans:hash>{content_hash}</ans:hash>")

    return rendered


# ─── XSD Validation ───────────────────────────────────────────────────────────


def validate_xml(xml_string: str) -> list[str]:
    """
    Validate an XML string against the TISS 4.01.00 XSD.
    Returns a list of validation error strings (empty = valid).

    If the XSD file is not found, returns a single warning message instead
    of crashing — allows development without the ANS schema file.
    """
    if not TISS_XSD_PATH.exists():
        logger.warning(
            "TISS XSD not found at %s — skipping validation. "
            "Download from ANS and place at that path.",
            TISS_XSD_PATH,
        )
        return [
            f"[WARNING] XSD schema file not found at {TISS_XSD_PATH}. "
            "Validation skipped. Download from ANS padrao.tiss.ans.gov.br."
        ]

    from lxml import etree  # lazy import — lxml may be absent in test envs

    schema = etree.XMLSchema(file=str(TISS_XSD_PATH))
    try:
        _parser = etree.XMLParser(resolve_entities=False, no_network=True)
        doc = etree.fromstring(xml_string.encode(), parser=_parser)
    except etree.XMLSyntaxError as exc:
        return [f"XML parse error: {exc}"]

    schema.validate(doc)
    return [str(e) for e in schema.error_log]
