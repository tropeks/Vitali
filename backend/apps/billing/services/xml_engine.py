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
import functools
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
# Lido em runtime para validar CBOS contra dm_CBOS sem transcrever 171 códigos
# para dentro do Python — ver _dm_cbos_validos.
TISS_SIMPLE_TYPES_XSD_PATH = _BILLING_DIR / "schemas" / "tissSimpleTypesV4_01_00.xsd"

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


def _to_local(value):
    """Converte um datetime AWARE para o fuso da clínica (``settings.TIME_ZONE``).

    Este é o ponto de estrangulamento de fuso do TISS: todo ``st_data``/``st_hora``
    do padrão é data e hora LOCAIS, sem offset (``xs:date``/``xs:time`` emitidos
    como ``YYYY-MM-DD``/``HH:MM:SS``), e o Django guarda todo ``DateTimeField`` em
    UTC (``USE_TZ=True``, ``TIME_ZONE="America/Sao_Paulo"``). Formatar o valor
    aware direto emite o horário UTC — um atendimento das 21:30 de São Paulo vira
    ``2026-08-11 00:30:00`` no documento enviado à operadora: **um dia inteiro à
    frente**. Nenhum gate pega isso, porque o XML continua schema-válido; aparece
    como glosa, meses depois, ou como divergência de competência.

    MORA AQUI, e não em cada resolver, de propósito. Uma correção no resolver
    conserta um caminho; esta função está no caminho de TODA data que chega ao
    XML (``_format_date``/``_format_time``), então fecha os três casos medidos de
    uma vez — ``dadosInternacao`` (período de faturamento),
    ``consulta_guide/dataAtendimento`` (``Encounter.encounter_date``, o de maior
    volume) e ``batch_envelope/data-horaRegistroTransacao`` (``timezone.now()``) —
    e impede que um template ou contexto futuro reintroduza o bug sem ninguém
    perceber.

    O que NÃO converte, e por quê:

    * ``datetime.date`` puro (ex.: ``Authorization.valid_from``,
      ``TISSGuide.authorization_date``) — data sem hora não tem fuso a converter,
      e ``timezone.localtime`` sobre ela levanta ``AttributeError``. O teste de
      ``isinstance(datetime.datetime)`` vem ANTES do de aware justamente por
      isso: ``datetime`` é subclasse de ``date``, a checagem inversa passaria
      um ``date`` para ``is_aware`` e estouraria.
    * datetime naive — já está em hora de parede; converter suporia um fuso de
      origem que ninguém declarou. Passa intacto.

    Idempotente: ``localtime`` sobre um valor já local devolve o mesmo instante
    no mesmo fuso, então aplicar duas vezes não dobra o deslocamento.
    """
    if isinstance(value, datetime.datetime) and timezone.is_aware(value):
        return timezone.localtime(value)
    return value


def _format_date(value) -> str:
    """Convert date/datetime to TISS format YYYY-MM-DD.

    A conversão de fuso (``_to_local``) acontece ANTES da redução
    ``datetime``→``date``: reduzir primeiro congelaria o dia em UTC e a conversão
    depois seria no-op sobre um ``date`` — exatamente o dia errado.
    """
    value = _to_local(value)
    if hasattr(value, "date"):
        value = value.date()
    return value.strftime("%Y-%m-%d") if value else ""


def _format_time(value) -> str:
    """Convert datetime to TISS format HH:MM:SS."""
    value = _to_local(value)
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

    # Datetimes saem daqui CRUS, como vieram do banco (aware/UTC). A conversão
    # para o fuso da clínica é do filtro ``_to_local``, por onde toda data do TISS
    # passa — havia uma segunda conversão aqui e ela foi REMOVIDA de propósito:
    # ``localtime`` é idempotente, então não dobrava o deslocamento, mas duas
    # fontes da mesma regra é o jeito de alguém "limpar" uma delas achando que a
    # outra cobre. Uma regra, um lugar.
    return {
        "internacao_carater_atendimento": admission.carater_atendimento,
        "internacao_tipo_faturamento": guide.tipo_faturamento,
        "internacao_inicio": admission.admission_datetime,
        "internacao_fim": admission.actual_discharge_datetime,
        "internacao_tipo": admission.tipo_internacao,
        "internacao_regime": admission.regime_internacao,
        "internacao_motivo_encerramento": admission.disposition_ans_code,
    }


DM_TABELA_VALIDOS = frozenset({"00", "18", "19", "20", "22", "90", "98"})


def _resolve_internacao_procedimentos(guide) -> list[dict]:
    """Resolve ``<procedimentosExecutados>`` (ct_procedimentoExecutadoInt).

    POR QUE ISTO EXISTE. O elemento é ``minOccurs="0"`` — o XSD aceita a guia de
    resumo de internação SEM nenhuma linha de procedimento, e era assim que ela
    saía: schema-válida, com ``valorTotalGeral`` e zero discriminação de itens.
    Nenhuma operadora paga um documento desses. Validade de schema nunca foi o
    critério aqui; a guia tem de ser faturável.

    Filhos obrigatórios, na ordem do XSD (medido com lxml sobre
    ``schemas/tissComplexTypesV4_01_00.xsd``)::

        sequencialItem      st_numerico4    posição na guia, 1..N
        dataExecucao        st_data         item.execution_date
        procedimento        ct_procedimentoDados  tabela + código + descrição
        quantidadeExecutada st_numerico3    INTEIRO
        reducaoAcrescimo    st_decimal3-2   item.reduction_increase_factor
        valorUnitario       st_decimal8-2   item.unit_value
        valorTotal          st_decimal8-2   item.total_value

    ``horaInicial``/``horaFinal``, ``viaAcesso``, ``tecnicaUtilizada`` e
    ``identEquipe`` são opcionais e NÃO são emitidos: não há fonte para nenhum
    deles, e emitir opcional inventado é pior que omitir.

    Falha alta (``TISSXMLGenerationError``) em vez de fabricar, em quatro casos
    — todos com o número do item na mensagem, porque o faturista precisa saber
    QUAL linha corrigir:

    1. **Item sem ``execution_date``.** Toda linha faturada antes da Onda 4 está
       assim, e nenhuma fonte honesta diz o dia: nem ``created_at`` (data do
       lançamento, não da execução) nem o período da internação (que só dá o
       intervalo). Carimbar qualquer uma delas seria declarar à operadora um fato
       clínico inventado.
    2. **Quantidade fracionária.** ``st_numerico3`` é ``integer``. Arredondar
       silenciosamente muda o que se cobra — 2,5 diárias viram 3 e ninguém vê.
       ``2.00`` é inteiro e passa; ``2.50`` falha.
    3. **``codigoTabela`` fora de ``dm_tabela``.** Enum fechado; um TUSS
       importado com ``table_number`` fora dele quebraria o XML no envio, e o
       erro do XSD não diria qual código causou.
    4. **Valor ou fator fora da faixa do XSD** (``st_decimal8-2`` até
       99.999.999,99; ``st_decimal3-2`` até 9,99).
    """
    items = list(guide.items.select_related("tuss_code").order_by("id"))
    if not items:
        return []

    procedimentos = []
    for sequencial, item in enumerate(items, start=1):
        if item.execution_date is None:
            raise TISSXMLGenerationError(
                f"Item {sequencial} da guia {guide.guide_number} "
                f"({item.description or item.tuss_code.code}) está sem data de execução: "
                "dataExecucao é obrigatório por item em ct_procedimentoExecutadoInt "
                "(tissComplexTypesV4_01_00.xsd) e não há fonte honesta para deduzi-la — "
                "nem a data do lançamento nem o período da internação dizem em que dia o "
                "item foi executado. Linhas faturadas antes da Onda 4 nascem assim: "
                "informe a data de execução do item antes de gerar o XML."
            )

        quantidade = Decimal(item.quantity)
        if quantidade != quantidade.to_integral_value():
            raise TISSXMLGenerationError(
                f"Item {sequencial} da guia {guide.guide_number} tem quantidade "
                f"fracionária ({quantidade}): quantidadeExecutada "
                "(ct_procedimentoExecutadoInt) é st_numerico3, um INTEIRO. Arredondar "
                "aqui mudaria em silêncio o que se cobra da operadora — ajuste a "
                "quantidade do item ou desmembre a linha."
            )
        quantidade_int = int(quantidade)
        if not (0 <= quantidade_int <= 999):
            raise TISSXMLGenerationError(
                f"Item {sequencial} da guia {guide.guide_number} tem quantidade "
                f"{quantidade_int}, fora da faixa de st_numerico3 (0 a 999)."
            )

        tabela = (item.tuss_code.table_number or "").strip()
        if tabela not in DM_TABELA_VALIDOS:
            raise TISSXMLGenerationError(
                f"Item {sequencial} da guia {guide.guide_number}: o TUSS "
                f"{item.tuss_code.code} tem tabela {tabela!r}, que não está em "
                f"dm_tabela ({', '.join(sorted(DM_TABELA_VALIDOS))}). codigoTabela é um "
                "enum FECHADO do XSD; enviar assim seria rejeitado pela operadora sem "
                "dizer qual item causou. Corrija o table_number do catálogo TUSS."
            )

        fator = Decimal(item.reduction_increase_factor)
        if not (Decimal("0") <= fator < Decimal("10")):
            raise TISSXMLGenerationError(
                f"Item {sequencial} da guia {guide.guide_number} tem fator de "
                f"redução/acréscimo {fator}, fora da faixa de st_decimal3-2 (0,00 a 9,99)."
            )
        for rotulo, valor in (("unitário", item.unit_value), ("total", item.total_value)):
            if Decimal(valor) >= Decimal("100000000"):
                raise TISSXMLGenerationError(
                    f"Item {sequencial} da guia {guide.guide_number} tem valor {rotulo} "
                    f"{valor}, fora da faixa de st_decimal8-2 (até 99.999.999,99)."
                )

        procedimentos.append(
            {
                "sequencial": sequencial,
                "data_execucao": item.execution_date,
                # st_texto150: a descrição do model vai a 300. Truncar perde texto,
                # estourar o XSD perde a guia inteira — trunca, e o código TUSS
                # (codigoProcedimento) segue identificando o item sem ambiguidade.
                "descricao": (item.description or item.tuss_code.description or "")[:150],
                "tabela": tabela,
                "codigo": item.tuss_code.code,
                "quantidade": quantidade_int,
                "fator": fator,
                "valor_unitario": item.unit_value,
                "valor_total": item.total_value,
            }
        )

    return procedimentos


# Ordem dos campos em ct_guiaValorTotal (tissComplexTypesV4_01_00.xsd). É uma
# <sequence>, então a ordem NÃO é cosmética: emitir fora dela invalida o XML.
_VALOR_TOTAL_CAMPOS = (
    ("valorProcedimentos", "procedimentos"),
    ("valorDiarias", "diarias"),
    ("valorTaxasAlugueis", "taxas_alugueis"),
    ("valorMateriais", "materiais"),
    ("valorMedicamentos", "medicamentos"),
    ("valorOPME", "opme"),
    ("valorGasesMedicinais", "gases_medicinais"),
)


def _resolve_valor_total(guide) -> list[dict]:
    """Breakdown por categoria de ``<valorTotal>`` (ct_guiaValorTotal).

    Os sete campos de categoria são ``minOccurs="0"`` e só ``valorTotalGeral`` é
    obrigatório — dá para emitir só o total e o XSD aceita. Era o que se fazia
    (Alternativa A do doc §4). O problema nunca foi o schema: **glosa por
    breakdown ausente é prática real de mercado**, principalmente em internação,
    onde a operadora quer ver diária separada de taxa e de gás.

    TUDO-OU-NADA, e esta é a regra que governa a função. O breakdown só é emitido
    quando **todo** item da guia tem categoria E a soma bate com
    ``guide.total_value``. Faltando qualquer uma das duas coisas, devolve lista
    vazia e o template emite só ``valorTotalGeral``.

    Por que não emitir o que dá: um breakdown parcial é PIOR que nenhum. A
    operadora soma os campos, não fecha com o total geral, e glosa a guia
    inteira — trocamos "faltou detalhe" por "a conta está errada". Guia com
    qualquer linha anterior a esta fatia (sem ``billing_category``) cai aqui, de
    propósito, e continua saindo exatamente como saía antes.

    A categoria NUNCA é inferida do TUSS. ``dm_tabela`` não serve: a tabela 18
    contém diárias, taxas e gases medicinais, que são três campos TISS
    diferentes, e ``TUSSCode.group`` é igualmente grosso. Cada ponte clínico→
    faturamento grava o que sabe quando cria o item (ver
    ``TISSGuideItem.billing_category``); o que a origem não sabe distinguir —
    taxa × gás — foi capturado na origem também (``InpatientFee.category``).

    Devolve a lista de ``{"tag", "valor"}`` na ordem da ``<sequence>`` do XSD,
    já sem as categorias zeradas (emitir ``0.00`` para uma categoria inexistente
    afirmaria que a guia tem zero de OPME, quando na verdade não tem OPME).
    """
    items = list(guide.items.all())
    if not items:
        return []

    somas: dict[str, Decimal] = {}
    for item in items:
        categoria = item.billing_category or ""
        if not categoria:
            # Uma linha sem categoria já basta: o breakdown não fecharia.
            return []
        somas[categoria] = somas.get(categoria, Decimal("0")) + Decimal(item.total_value)

    if sum(somas.values()) != Decimal(guide.total_value):
        # Defesa contra divergência silenciosa entre a soma das linhas e o total
        # gravado na guia (ex.: total_value editado por update() direto, sem
        # passar por TISSGuideItem.save/_recalc_guide_total). Sem breakdown a
        # guia continua válida; com um que não fecha, ela vira glosa.
        logger.warning(
            "Guia %s: soma das categorias (%s) diverge de total_value (%s) — "
            "breakdown omitido para não emitir uma conta que não fecha.",
            guide.guide_number,
            sum(somas.values()),
            guide.total_value,
        )
        return []

    return [
        {"tag": tag, "valor": somas[chave]}
        for tag, chave in _VALOR_TOTAL_CAMPOS
        if somas.get(chave)
    ]


@functools.lru_cache(maxsize=1)
def _dm_cbos_validos() -> frozenset[str]:
    """Os códigos de ``dm_CBOS`` (enum FECHADO), lidos do XSD do próprio repo.

    São 171 ``xs:enumeration`` mas **169 valores distintos**: o XSD repete
    ``225121`` e ``225325``. Medido, não suposto — e é a razão de esta função
    devolver um conjunto em vez de uma lista.

    Lidos, e não transcritos: uma cópia da lista no código vira mentira silenciosa
    no dia em que o XSD for atualizado, e o erro apareceria só como rejeição da
    operadora. O arquivo já está aqui e é a fonte — ``validate_xml`` valida contra
    ele. Em cache porque o parse custa e o conjunto não muda em runtime.
    """
    from lxml import etree

    arvore = etree.parse(str(TISS_SIMPLE_TYPES_XSD_PATH))
    ns = {"xs": "http://www.w3.org/2001/XMLSchema"}
    st = arvore.find('.//xs:simpleType[@name="dm_CBOS"]', ns)
    return frozenset(e.get("value") for e in st.iterfind(".//xs:enumeration", ns))


def _resolve_sadt_solicitante(guide) -> dict:
    """Resolve ``<dadosSolicitante>`` de ctm_sp-sadtGuia.

    O ÚLTIMO gap de dado da Onda 4, e o único que exigiu um papel novo no
    domínio. Os três filhos são obrigatórios::

        contratadoSolicitante      ct_contratadoDados (choice)
        nomeContratadoSolicitante  st_texto70
        profissionalSolicitante    ct_contratadoProfissionalDados

    e ``ct_contratadoProfissionalDados`` pede ``conselhoProfissional``
    (dm_conselhoProfissional), ``numeroConselhoProfissional``, ``UF`` (dm_UF) e
    ``CBOS`` (dm_CBOS, enum FECHADO) — ``nomeProfissional`` é o único opcional.

    POR QUE NÃO REUSAR O EXECUTANTE. O template parou aqui desde a Fatia 0 com
    esta justificativa, que segue valendo: `encounter.professional` é quem
    EXECUTOU. Emitir os dados dele em ``dadosSolicitante`` declararia à operadora
    que quem pediu o exame foi quem o fez. Isso não é um placeholder honesto como
    o ``codigoPrestadorNaOperadora`` (campo de texto livre cujo valor real não
    temos); é uma AFIRMAÇÃO CLÍNICA falsa sobre quem indicou o procedimento —
    exatamente o tipo de coisa que gera glosa por inconsistência e, pior, distorce
    o registro de quem responde pela indicação.

    FONTE REAL. ``TISSGuide.requesting_professional``, preenchido pela ponte de
    laboratório a partir de ``LabOrder.requested_by`` (quem pediu o exame É o
    solicitante) e informado à mão nos demais casos — a guia de cirurgia não tem
    fonte, porque ``SurgicalCase.surgeon`` é quem opera, não quem indicou.

    Falha alta, campo a campo, com o que preencher e onde:

    1. sem ``requesting_professional``;
    2. ``council_type`` fora de dm_conselhoProfissional, ou ``council_number``
       vazio;
    3. ``council_state`` que não resolve para o código IBGE de dm_UF;
    4. CBO ausente, ou fora de dm_CBOS — este é o mais provável na
       prática, porque ``Professional.cbo`` é opcional e há
       ``legacy_cbo_text``/``cbo_unmatched`` no model, sinal de que o catálogo
       nem sempre casa;
    5. sem CNES — é o que identifica o contratado solicitante.
    """
    solicitante = guide.requesting_professional
    if solicitante is None:
        raise TISSXMLGenerationError(
            f"Guia SP/SADT {guide.guide_number} não tem profissional solicitante: "
            "dadosSolicitante (ctm_sp-sadtGuia) é obrigatório e exige conselho, número, "
            "UF e CBOS de QUEM PEDIU o procedimento — que não é o executante. Guias "
            "geradas de um pedido de exame herdam o solicitante automaticamente; nos "
            "demais casos, informe o profissional solicitante nesta guia enquanto ela "
            "estiver em rascunho."
        )

    faltando = []

    conselho = _conselho_ans_code(solicitante.council_type)
    if not conselho:
        faltando.append(
            f"conselho profissional ({solicitante.council_type or 'vazio'!r} não está em "
            "dm_conselhoProfissional)"
        )
    if not (solicitante.council_number or "").strip():
        faltando.append("número do conselho")

    uf = _uf_ibge_code(solicitante.council_state)
    if not uf:
        faltando.append(
            f"UF do conselho ({solicitante.council_state or 'vazio'!r} não resolve em dm_UF)"
        )

    cbo = (solicitante.cbo_code or "").strip()
    if not cbo:
        faltando.append("CBO (ocupação)")
    elif cbo not in _dm_cbos_validos():
        faltando.append(
            f"CBO {cbo} fora de dm_CBOS — o XSD aceita apenas os códigos de ocupação "
            "enumerados na tabela ANS, e este não está entre eles"
        )

    cnes = (solicitante.cnes_code or "").strip()
    if not cnes:
        faltando.append("CNES do estabelecimento")

    if faltando:
        raise TISSXMLGenerationError(
            f"Guia SP/SADT {guide.guide_number}: o cadastro do profissional solicitante "
            f"({solicitante}) está incompleto para dadosSolicitante — falta "
            f"{'; '.join(faltando)}. Complete o cadastro do profissional antes de gerar o XML; "
            "nenhum desses campos pode ser suprido pelo executante da guia."
        )

    # nomeContratadoSolicitante: o nome do estabelecimento vem do catálogo CNES
    # governado (core.CNESEstablishment.display). Quando o profissional guarda só
    # o texto legado de CNES, não há nome — cai para o código, que é verdade
    # verificável, em vez de string inventada.
    estabelecimento = solicitante.cnes.display if solicitante.cnes_id else cnes

    return {
        "solicitante_codigo_prestador": cnes,
        "solicitante_nome_contratado": (estabelecimento or cnes)[:70],
        "solicitante_nome_profissional": (getattr(solicitante.user, "full_name", "") or "")[:70],
        "solicitante_conselho": conselho,
        "solicitante_numero_conselho": solicitante.council_number.strip()[:15],
        "solicitante_uf": uf,
        "solicitante_cbos": cbo,
    }


def _resolve_sadt_solicitacao(guide) -> dict:
    """Resolve mandatory ``dadosSolicitacao.caraterAtendimento`` honestly.

    LabOrder has no urgency field, so its status cannot be promoted into a
    clinical assertion. SurgicalCase.priority is the governed source available
    today: elective maps to ANS ``1`` and urgent/emergency to ``2``.
    """
    surgical_case = getattr(guide, "surgical_case", None)
    if surgical_case is None:
        raise TISSXMLGenerationError(
            f"Guia SP/SADT {guide.guide_number} não tem fonte honesta para "
            "dadosSolicitacao.caraterAtendimento: LabOrder não registra caráter "
            "eletivo/urgente. Vincule um caso cirúrgico com prioridade governada "
            "ou informe uma fonte antes de gerar o XML; não é permitido assumir "
            "um valor padrão."
        )
    mapping = {"eletiva": "1", "urgencia": "2", "emergencia": "2"}
    carater = mapping.get(surgical_case.priority)
    if carater is None:
        raise TISSXMLGenerationError(
            f"Guia SP/SADT {guide.guide_number}: prioridade cirúrgica "
            f"{surgical_case.priority!r} não mapeia para dm_caraterAtendimento (1/2)."
        )
    return {"sadt_carater_atendimento": carater}


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

    if guide.guide_type == "sadt":
        # dadosSolicitante — quem PEDIU, distinto de quem executou. Falha alta e
        # acionável quando não há fonte honesta; nunca cai no executante.
        context.update(_resolve_sadt_solicitante(guide))
        context.update(_resolve_sadt_solicitacao(guide))

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
        # <procedimentosExecutados>: a discriminação item a item. Ver o docstring
        # do resolver para por que a guia não pode mais sair sem ela.
        context["procedimentos"] = _resolve_internacao_procedimentos(guide)
        # Breakdown de ct_guiaValorTotal — vazio quando não fecha (ver resolver).
        context["valor_total_breakdown"] = _resolve_valor_total(guide)

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
