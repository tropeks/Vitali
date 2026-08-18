"""
TISS XML engine — schema conformance tests (billing 2.4).

The central deliverable is validate_xml(...) returning an EMPTY error list
(i.e. real XSD-valid TISS 4.01.00 XML) for the guide/batch types this task
brought to conformance. Guide types that could not be brought to conformance
within this task's scope are xfail(strict=True) with the exact missing model
data documented in the reason — see the class docstrings below.

Run: python manage.py test apps.billing.tests.test_xml_engine
"""

import datetime
from decimal import Decimal
from unittest import mock

import pytest
from django.utils import timezone

from apps.billing.models import (
    Authorization,
    InsuranceProvider,
    TISSBatch,
    TISSGuide,
    TISSGuideItem,
)
from apps.billing.services.xml_engine import (
    TISSXMLGenerationError,
    _format_date,
    _format_time,
    _resolve_internacao_authorization,
    generate_batch_xml,
    generate_guide_xml,
    validate_xml,
)
from apps.core.models import Role, TUSSCode, User
from apps.emr.models import Admission, Encounter, Patient, Professional
from apps.test_utils import TenantTestCase

#: Sentinela para distinguir "internação omitida" (cria uma completa) de
#: ``admission=None`` (guia sem vínculo — ramo de falha estrutural). ``None``
#: é um valor de teste legítimo aqui, então não serve como default.
_UNSET = object()


class XMLEngineTestCase(TenantTestCase):
    """Shared fixtures: one patient/professional/encounter/provider + a single
    "consulta" guide with exactly one item — the minimum ctm_consultaGuia
    (tissGuiasV4_01_00.xsd) needs to be schema-valid."""

    def setUp(self):
        role = Role.objects.create(
            name="faturista_xml", permissions=["billing.read", "billing.write"], is_system=True
        )
        prof_user = User.objects.create_user(
            email="medico_xml@test.com",
            full_name="Dr. XML Test",
            password="Str0ng!Pass#2024",
            role=role,
        )
        self.patient = Patient.objects.create(
            full_name="Maria XML Teste",
            cpf="333.333.333-33",
            birth_date=datetime.date(1980, 5, 12),
            gender="F",
        )
        self.professional = Professional.objects.create(
            user=prof_user,
            council_type="CRM",
            council_number="123456",
            council_state="SP",
        )
        # cbo_code/cnes_code are setter properties (governed FK vs legacy text
        # — see apps/emr/models.py Professional.cbo_code/cnes_code). "225120"
        # (Médico Clínico) is in the XSD's closed dm_CBOS enumeration.
        self.professional.cbo_code = "225120"
        self.professional.cnes_code = "1234567"
        self.professional.save()
        self.encounter = Encounter.objects.create(
            patient=self.patient,
            professional=self.professional,
            encounter_date=datetime.datetime(2026, 8, 10, 9, 0, tzinfo=datetime.UTC),
        )
        self.provider = InsuranceProvider.objects.create(
            name="Operadora XML Teste", ans_code="326305"
        )
        self.tuss_consulta = TUSSCode.objects.create(
            code="10101012",
            description="Consulta em consultório",
            group="procedimento",
            version="2024-01",
        )

    def _make_consulta_guide(self, guide_number_suffix="1", n_items=1):
        guide = TISSGuide.objects.create(
            guide_type="consulta",
            encounter=self.encounter,
            patient=self.patient,
            provider=self.provider,
            insured_card_number="1234567890123456",
            authorization_number="AUTH123",
            competency="2026-08",
        )
        TISSGuide.objects.filter(pk=guide.pk).update(
            guide_number=f"20260800000{guide_number_suffix}"
        )
        guide.refresh_from_db()
        for _i in range(n_items):
            TISSGuideItem.objects.create(
                guide=guide,
                tuss_code=self.tuss_consulta,
                description="Consulta em consultório",
                quantity=Decimal("1"),
                unit_value=Decimal("150.00"),
            )
        return guide


class TISSDateTimeFilterTests(XMLEngineTestCase):
    """``format_date``/``format_time`` — conversão de fuso no ponto de
    estrangulamento (``_to_local``).

    POR QUE 21:30, E NÃO MEIO-DIA. Todo teste aqui está ancorado em 2026-08-10
    21:30 America/Sao_Paulo = 2026-08-11 00:30 UTC, o horário que CRUZA A
    MEIA-NOITE UTC. Um teste ao meio-dia passa com o bug presente (12:00 local e
    15:00 UTC caem no mesmo dia, e a asserção de data não vê diferença) — ele
    provaria nada. Só um horário noturno separa "a data está certa" de "a data
    está certa por sorte".

    O BUG QUE ESTES TESTES TRAVAM. ``st_data``/``st_hora`` do TISS são locais e
    sem offset; o Django guarda ``DateTimeField`` em UTC. Sem ``_to_local``, um
    atendimento das 21:30 é declarado à operadora como tendo ocorrido no dia
    seguinte, às 00:30 — e o XML continua schema-válido, então NENHUM gate pega.
    Foi assim que ``consulta_guide/dataAtendimento`` (a guia de maior volume, e
    que já passava conformance) esteve errada até esta correção.
    """

    #: 21:30 em America/Sao_Paulo. O ``.astimezone(UTC)`` correspondente é
    #: 2026-08-11 00:30 — dia seguinte.
    LOCAL_NIGHT = datetime.datetime(2026, 8, 10, 21, 30, 0)

    def _aware_utc(self):
        """O MESMO instante, com tzinfo=UTC — é assim que o valor volta do banco
        e é assim que ``timezone.now()`` devolve. Construir o aware em horário
        local e não normalizar para UTC mascararia o bug: ``strftime`` usa o
        tzinfo do próprio valor, então um aware já em -03:00 imprimiria a hora
        certa mesmo sem conversão nenhuma."""
        return timezone.make_aware(self.LOCAL_NIGHT).astimezone(datetime.UTC)

    def test_format_date_converte_aware_utc_para_o_dia_local(self):
        assert _format_date(self._aware_utc()) == "2026-08-10"

    def test_format_time_converte_aware_utc_para_a_hora_local(self):
        assert _format_time(self._aware_utc()) == "21:30:00"

    def test_conversao_acontece_antes_da_reducao_datetime_para_date(self):
        """``_format_date`` reduz ``datetime``→``date``; se a conversão de fuso
        viesse DEPOIS dessa redução, o dia já estaria congelado em UTC e
        ``localtime`` sobre um ``date`` não teria o que corrigir (e estouraria).
        A ordem é a correção — este teste é o guarda dela."""
        utc_value = self._aware_utc()
        assert utc_value.date() == datetime.date(2026, 8, 11), "premissa: em UTC é dia 11"
        assert _format_date(utc_value) == "2026-08-10"

    def test_date_puro_passa_intacto(self):
        """``datetime.date`` não tem fuso a converter — e ``localtime`` sobre ele
        levanta ``AttributeError``. Guarda de não-regressão dos campos que são
        ``DateField`` de verdade (``Authorization.valid_from``,
        ``TISSGuide.authorization_date``), que passam por este mesmo filtro."""
        assert _format_date(datetime.date(2026, 8, 10)) == "2026-08-10"

    def test_datetime_naive_passa_intacto(self):
        """Naive já é hora de parede; converter suporia um fuso de origem que
        ninguém declarou. Sai exatamente como entrou, sem deslocamento."""
        naive = datetime.datetime(2026, 8, 10, 21, 30, 0)
        assert _format_date(naive) == "2026-08-10"
        assert _format_time(naive) == "21:30:00"

    def test_contrato_de_string_dos_vazios_nao_mudou(self):
        """A assinatura e o contrato de saída são os de antes: ``""`` para data
        vazia, ``"00:00:00"`` para hora sem ``strftime``. A correção de fuso não
        podia mexer nisso — templates já renderizados dependem desses vazios."""
        assert _format_date(None) == ""
        assert _format_time(None) == "00:00:00"

    def test_conversao_e_idempotente(self):
        """``localtime`` sobre um valor já local devolve o mesmo instante — é o
        que garante que a remoção do ``_local_datetime`` do resolver não era
        obrigatória por risco de deslocamento dobrado (foi por clareza), e que
        um futuro resolver que já converta não quebra nada."""
        ja_local = timezone.localtime(self._aware_utc())
        assert _format_date(ja_local) == "2026-08-10"
        assert _format_time(ja_local) == "21:30:00"


class ConsultaGuideXMLConformanceTests(XMLEngineTestCase):
    """guiaConsulta — brought to full TISS 4.01.00 conformance (see 2.4)."""

    def test_batch_envelope_with_one_consulta_guide_is_schema_valid(self):
        guide = self._make_consulta_guide()
        batch = TISSBatch.objects.create(provider=self.provider)
        batch.guides.add(guide)

        xml = generate_batch_xml(batch)
        errors = validate_xml(xml)

        assert errors == [], errors

    def test_data_atendimento_sai_com_o_dia_local_do_encounter(self):
        """``dataAtendimento`` ← ``Encounter.encounter_date``, que é
        ``DateTimeField`` (apps/emr/models.py) e portanto vem do banco em UTC.

        Esta era a pior instância do bug de fuso: a guia de CONSULTA é a de maior
        volume e já passava conformance de schema, então declarava à operadora,
        sem nenhum sinal de erro, que um atendimento das 21:30 aconteceu no dia
        seguinte. Medido antes da correção: ``<ans:dataAtendimento>2026-08-11``.
        A competência/data de atendimento errada é exatamente o tipo de
        divergência que só volta como glosa."""
        local_night = timezone.make_aware(datetime.datetime(2026, 8, 10, 21, 30))
        self.encounter.encounter_date = local_night
        self.encounter.save(update_fields=["encounter_date"])
        guide = self._make_consulta_guide()

        xml = generate_guide_xml(guide)

        assert "<ans:dataAtendimento>2026-08-10</ans:dataAtendimento>" in xml
        assert "2026-08-11" not in xml, "dataAtendimento saiu em UTC (dia seguinte)"

    def test_batch_envelope_registra_transacao_em_hora_local(self):
        """``dataRegistroTransacao``/``horaRegistroTransacao`` ← ``timezone.now()``,
        que devolve aware em UTC — o terceiro caso da mesma classe.

        ``timezone.now`` é mockado no módulo consumidor (mesmo idioma de
        ``apps/core/tests/test_user_invitations.py:28``), e o valor injetado é
        normalizado para ``UTC`` de propósito: é assim que ``now()`` devolve de
        verdade. Injetar um aware já em -03:00 faria o teste passar mesmo com o
        bug presente, porque ``strftime`` usa o tzinfo do próprio valor. Medido
        antes da correção: ``2026-08-11`` / ``00:30:00``."""
        utc_now = timezone.make_aware(datetime.datetime(2026, 8, 10, 21, 30)).astimezone(
            datetime.UTC
        )
        guide = self._make_consulta_guide()
        batch = TISSBatch.objects.create(provider=self.provider)
        batch.guides.add(guide)

        with mock.patch("apps.billing.services.xml_engine.timezone.now", return_value=utc_now):
            xml = generate_batch_xml(batch)

        assert "<ans:dataRegistroTransacao>2026-08-10</ans:dataRegistroTransacao>" in xml
        assert "<ans:horaRegistroTransacao>21:30:00</ans:horaRegistroTransacao>" in xml
        assert validate_xml(xml) == [], "a correção de fuso não pode quebrar o schema"

    def test_batch_envelope_with_multiple_consulta_guides_is_schema_valid(self):
        """ctm_guiaLote allows guiaConsulta to repeat (maxOccurs=100) within
        one homogeneous lote — a multi-guide batch must stay valid too."""
        guide_1 = self._make_consulta_guide("1")
        guide_2 = self._make_consulta_guide("2")
        batch = TISSBatch.objects.create(provider=self.provider)
        batch.guides.add(guide_1, guide_2)

        xml = generate_batch_xml(batch)
        errors = validate_xml(xml)

        assert errors == [], errors

    def test_generate_batch_xml_raises_on_mixed_guide_types(self):
        """ctm_guiaLote/guiasTISS is a <choice>: one lote = one guide type.
        A batch mixing consulta + sadt guides cannot become one valid
        <guiasTISS> — must fail loud instead of emitting invalid XML."""
        consulta_guide = self._make_consulta_guide("1")
        sadt_guide = TISSGuide.objects.create(
            guide_type="sadt",
            encounter=self.encounter,
            patient=self.patient,
            provider=self.provider,
            insured_card_number="1234567890123456",
            competency="2026-08",
        )
        batch = TISSBatch.objects.create(provider=self.provider)
        batch.guides.add(consulta_guide, sadt_guide)

        with pytest.raises(TISSXMLGenerationError, match="mistura tipos de guia"):
            generate_batch_xml(batch)

    def test_generate_guide_xml_raises_when_consulta_has_no_items(self):
        """ctm_consultaGuia models exactly one <procedimento> — zero items
        cannot be rendered validly."""
        guide = self._make_consulta_guide(n_items=0)

        with pytest.raises(TISSXMLGenerationError, match="0 item"):
            generate_guide_xml(guide)

    def test_generate_guide_xml_raises_when_consulta_has_multiple_items(self):
        """ctm_consultaGuia's <procedimento> is not a repeatable list — more
        than one item must fail loud rather than silently drop data or emit
        an invalid repeated element."""
        guide = self._make_consulta_guide(n_items=2)

        with pytest.raises(TISSXMLGenerationError, match="2 item"):
            generate_guide_xml(guide)


class HonorariosGuideXMLTests(XMLEngineTestCase):
    """2.8 — "honorarios" has no template; generate_guide_xml must fail loud
    instead of silently falling through to the consulta template."""

    def test_generate_guide_xml_raises_for_honorarios(self):
        guide = TISSGuide.objects.create(
            guide_type="honorarios",
            encounter=self.encounter,
            patient=self.patient,
            provider=self.provider,
            executor=self.professional,
            insured_card_number="1234567890123456",
            competency="2026-08",
        )

        with pytest.raises(TISSXMLGenerationError, match="no TISS XML template"):
            generate_guide_xml(guide)


class SadtGuideXMLConformanceTests(XMLEngineTestCase):
    """guiaSP-SADT (ctm_sp-sadtGuia) — NOT brought to conformance.

    Onda 4 Fatia 0 ported the proven cabecalhoGuia/dadosBeneficiario form
    from consulta_guide.xml.j2 (the old template emitted fields inside
    <cabecalhoGuia> — numeroGuiaOperadora, dataAutorizacao, senhaAutorizacao,
    numeroCarteira, codigoCBO, CNES, dataInicioFaturamento,
    dataFinalFaturamento — none of which belong to ct_guiaCabecalho, and a
    <dadosSolicitacaoExame>/<procedimentosSolicitados> pair that doesn't
    exist anywhere in ctm_sp-sadtGuia). Measured before the fix: 2 form
    errors (unexpected numeroGuiaOperadora inside cabecalhoGuia; unexpected
    dadosSolicitacaoExame in place of dadosSolicitante). Measured after: 1
    residual error, and it is a genuine DATA gap, not form —

    - <dadosSolicitante> is the very next mandatory element after
      dadosBeneficiario: contratadoSolicitante (CNPJ/CPF/
      codigoPrestadorNaOperadora) + profissionalSolicitante (conselho/UF/CBOS
      of the REQUESTING professional). TISSGuide only tracks the executing
      professional (via encounter); nothing distinguishes solicitante from
      executante, so the template stops right there instead of misattributing
      the executante as solicitante.

    Everything after dadosSolicitante in the schema (dadosSolicitacao.
    caraterAtendimento, dadosAtendimento.tipoAtendimento/regimeAtendimento,
    ct_guiaValorTotal breakdown, per-item reducaoAcrescimo) is unreached by
    the validator as a direct consequence and remains real, separately
    itemized data gaps for Fatia 2+ — see
    docs/research/VITALI_ONDA4_TISS_MODELAGEM.md §2.
    """

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "ctm_sp-sadtGuia: cabecalhoGuia/dadosBeneficiario form fixed "
            "(Fatia 0). Residual is a genuine data gap, not form: "
            "dadosSolicitante (solicitante professional/contratado) has no "
            "model field — TISSGuide only tracks the executante. Everything "
            "after it in the schema (caraterAtendimento, dadosAtendimento, "
            "valorTotal breakdown, reducaoAcrescimo) is unreached as a "
            "consequence — see 2.4/Onda 4 Fatia 0 report."
        ),
    )
    def test_batch_envelope_with_sadt_guide_is_schema_valid(self):
        guide = TISSGuide.objects.create(
            guide_type="sadt",
            encounter=self.encounter,
            patient=self.patient,
            provider=self.provider,
            insured_card_number="1234567890123456",
            authorization_number="AUTH123",
            competency="2026-08",
        )
        TISSGuideItem.objects.create(
            guide=guide,
            tuss_code=self.tuss_consulta,
            description="Consulta em consultório",
            quantity=Decimal("1"),
            unit_value=Decimal("150.00"),
        )
        batch = TISSBatch.objects.create(provider=self.provider)
        batch.guides.add(guide)

        xml = generate_batch_xml(batch)
        errors = validate_xml(xml)

        assert errors == [], errors


class InternacaoFixtureMixin:
    """Fixtures compartilhadas pelas três classes de internação abaixo.

    Antes desta fatia cada classe repetia seu próprio ``_make_internacao_guide``
    e nenhuma criava ``Admission``, porque nada no template lia a internação.
    Agora ``dadosInternacao`` depende dela — e a duplicação viraria três lugares
    para esquecer de preencher um dos campos novos.
    """

    #: Internação de 2026-08-10 21:30 a 2026-08-14 09:15, HORA LOCAL da clínica.
    #: 21:30 em America/Sao_Paulo é 00:30 UTC do DIA SEGUINTE — escolhido de
    #: propósito: é o horário que denuncia formatação em UTC (ver
    #: test_periodo_de_faturamento_sai_em_hora_local_da_clinica).
    ADMISSION_LOCAL = datetime.datetime(2026, 8, 10, 21, 30)
    DISCHARGE_LOCAL = datetime.datetime(2026, 8, 14, 9, 15)

    def _make_admission(
        self,
        *,
        admit=None,
        discharge=None,
        carater_atendimento="1",
        tipo_internacao="1",
        regime_internacao="1",
        disposition_ans_code="11",
    ):
        return Admission.objects.create(
            patient=self.patient,
            admitting_professional=self.professional,
            attending_professional=self.professional,
            encounter=self.encounter,
            admission_datetime=timezone.make_aware(admit or self.ADMISSION_LOCAL),
            actual_discharge_datetime=(
                None
                if discharge is False
                else timezone.make_aware(discharge or self.DISCHARGE_LOCAL)
            ),
            status=(
                Admission.Status.ADMITTED if discharge is False else Admission.Status.DISCHARGED
            ),
            carater_atendimento=carater_atendimento,
            tipo_internacao=tipo_internacao,
            regime_internacao=regime_internacao,
            disposition_ans_code=disposition_ans_code,
        )

    def _make_internacao_guide(
        self,
        *,
        authorization_number="AUTH123",
        admission=_UNSET,
        tipo_faturamento="1",
    ):
        """Guia de internação COMPLETA por padrão (internação com alta + todas as
        taxonomias + tipo_faturamento).

        ``admission`` aceita três coisas: omitido → cria uma internação completa;
        ``None`` → guia sem vínculo (branch de falha estrutural); uma instância →
        usa aquela (branches de campo faltando)."""
        if admission is _UNSET:
            admission = self._make_admission()
        guide = TISSGuide.objects.create(
            guide_type="internacao",
            encounter=self.encounter,
            patient=self.patient,
            provider=self.provider,
            admission=admission,
            insured_card_number="1234567890123456",
            authorization_number=authorization_number,
            tipo_faturamento=tipo_faturamento,
            competency="2026-08",
        )
        TISSGuideItem.objects.create(
            guide=guide,
            tuss_code=self.tuss_consulta,
            description="Consulta em consultório",
            quantity=Decimal("1"),
            unit_value=Decimal("150.00"),
        )
        return guide

    def _approve_authorization(self):
        return Authorization.objects.create(
            patient=self.patient,
            provider=self.provider,
            tuss_code=self.tuss_consulta,
            status=Authorization.Status.APPROVED,
            valid_from=datetime.date(2026, 8, 1),
            authorization_number="AUTH123",
        )


class InternacaoGuideXMLConformanceTests(InternacaoFixtureMixin, XMLEngineTestCase):
    """guiaResumoInternacao (ctm_internacaoResumoGuia) — AGORA EM CONFORMIDADE
    TOTAL. O ``xfail(strict=True)`` que este arquivo carregava desde a Onda 2
    caiu nesta fatia; ``validate_xml`` devolve lista vazia.

    Histórico da sequência, elemento a elemento (cada linha foi uma medição,
    não uma estimativa — é assim que esta onda vem funcionando):

    - ``cabecalhoGuia`` + ``numeroGuiaSolicitacaoInternacao`` — Onda 4 Fatia 0
      (forma portada de ``consulta_guide.xml.j2``; a autorreferência ao próprio
      ``guide_number`` é decisão de produto do Capitão).
    - ``dadosAutorizacao`` — resolvido de dado existente
      (``_resolve_internacao_authorization``): ``senha`` de
      ``TISSGuide.authorization_number`` ou da ``Authorization`` aprovada,
      ``dataAutorizacao`` SEMPRE de fonte real (``Authorization.valid_from`` ou
      a digitação ``authorization_date``), nunca fabricada.
    - ``dadosBeneficiario`` + ``dadosExecutante`` — pura ligação, mesmo dado que
      os outros templates da pasta já resolviam.
    - ``dadosInternacao`` + ``dadosSaidaInternacao`` + ``valorTotal`` — ESTA
      FATIA (ver ``InternacaoDadosResolutionTests`` para os ramos de falha).

    O QUE A MEDIÇÃO DO XSD CORRIGIU NO PLANO. O doc de pesquisa §3 listava
    quatro filhos de ``ctm_internacaoDados``; o XSD tem OITO obrigatórios. Os
    quatro que faltavam na lista são o período de faturamento
    (``dataInicioFaturamento``/``horaInicioFaturamento``/``dataFinalFaturamento``/
    ``horaFinalFaturamento``) — e são justamente eles que provam que este bloco
    descreve a GUIA, não a estada, que é por que ``tipo_faturamento`` nasceu em
    ``TISSGuide`` e não em ``Admission`` (o §5 sugeria ``Admission``).

    O QUE AINDA NÃO É VERDADE, apesar do XML válido:

    - ``procedimentosExecutados`` é ``minOccurs="0"`` e NÃO é emitido, mesmo com
      ``TISSGuideItem`` preenchido: ``ct_procedimentoExecutadoInt`` exige
      ``reducaoAcrescimo`` (campo que ``TISSGuideItem`` não tem — Fatia 1 do doc,
      não landed) e ``dataExecucao`` por item (que ``TISSGuideItem`` também não
      guarda). Emitir seria fabricar os dois.
    - ``valorTotal`` sai pela Alternativa A do doc §4 (só ``valorTotalGeral``,
      sete breakdowns omitidos).

    Ou seja: **XSD-válido não é aceite da operadora**. Uma internação enviada sem
    discriminação de itens e sem separação diária × taxa × gás medicinal é
    candidata natural a glosa. Fechar isso é a Alternativa B do §4 + a Fatia 1,
    e depende de decisão de produto — não de mais uma medição de schema.
    """

    def test_batch_envelope_with_internacao_guide_is_schema_valid(self):
        """Caminho feliz completo: internação com alta, taxonomias preenchidas,
        tipo_faturamento declarado e Authorization aprovada resolvível."""
        guide = self._make_internacao_guide()
        self._approve_authorization()
        batch = TISSBatch.objects.create(provider=self.provider)
        batch.guides.add(guide)

        xml = generate_batch_xml(batch)
        errors = validate_xml(xml)

        assert errors == [], errors

    def test_periodo_de_faturamento_sai_em_hora_local_da_clinica(self):
        """``st_data``/``st_hora`` são data e hora LOCAIS, sem offset — e o banco
        guarda ``DateTimeField`` em UTC.

        A internação da fixture começa às 21:30 de 2026-08-10 em
        America/Sao_Paulo, que é 00:30 de 2026-08-11 em UTC. Formatar o valor
        aware direto (o que ``format_date``/``format_time`` fazem sozinhos)
        empurraria o início do faturamento para o DIA SEGUINTE: um dia inteiro de
        estada some do documento enviado à operadora, e só reaparece como glosa.
        Por isso a conversão mora nos próprios filtros (``_to_local``, chamado
        por ``format_date``/``format_time``) — ponto por onde toda data do TISS
        passa, e não no resolver, que cobriria só este caminho. Este teste é o
        guarda de ponta a ponta dessa conversão para ``dadosInternacao``; os
        guardas unitários dos filtros estão em ``TISSDateTimeFilterTests``."""
        guide = self._make_internacao_guide()
        self._approve_authorization()

        xml = generate_guide_xml(guide)

        assert "<ans:dataInicioFaturamento>2026-08-10</ans:dataInicioFaturamento>" in xml
        assert "<ans:horaInicioFaturamento>21:30:00</ans:horaInicioFaturamento>" in xml
        assert "<ans:dataFinalFaturamento>2026-08-14</ans:dataFinalFaturamento>" in xml
        assert "<ans:horaFinalFaturamento>09:15:00</ans:horaFinalFaturamento>" in xml
        # O erro que este teste existe para pegar, dito explicitamente.
        assert "2026-08-11" not in xml, "período de faturamento saiu em UTC, não em hora local"

    def test_dados_internacao_e_saida_saem_das_fontes_reais(self):
        """Cada filho obrigatório vem do campo que o resolver documenta — e
        ``indicadorAcidente`` sai com o default seguro "9" (não acidente), o
        mesmo já documentado em ``consulta_guide.xml.j2``, porque não existe
        fonte de acidente no model."""
        admission = self._make_admission(
            carater_atendimento="2",
            tipo_internacao="3",
            regime_internacao="2",
            disposition_ans_code="27",
        )
        guide = self._make_internacao_guide(admission=admission, tipo_faturamento="4")
        self._approve_authorization()

        xml = generate_guide_xml(guide)

        assert "<ans:caraterAtendimento>2</ans:caraterAtendimento>" in xml
        assert "<ans:tipoFaturamento>4</ans:tipoFaturamento>" in xml
        assert "<ans:tipoInternacao>3</ans:tipoInternacao>" in xml
        assert "<ans:regimeInternacao>2</ans:regimeInternacao>" in xml
        assert "<ans:indicadorAcidente>9</ans:indicadorAcidente>" in xml
        assert "<ans:motivoEncerramento>27</ans:motivoEncerramento>" in xml

    def test_valor_total_emite_so_o_total_geral_sem_breakdown(self):
        """Alternativa A do doc §4, explicitada em teste para que uma futura
        Fatia 6 (breakdown real) tenha de mexer AQUI e reler o trade-off: os sete
        campos de breakdown são opcionais no XSD e saem ausentes de propósito,
        não por esquecimento."""
        guide = self._make_internacao_guide()
        self._approve_authorization()

        xml = generate_guide_xml(guide)

        assert "<ans:valorTotalGeral>150.00</ans:valorTotalGeral>" in xml
        for breakdown in (
            "valorProcedimentos",
            "valorDiarias",
            "valorTaxasAlugueis",
            "valorMateriais",
            "valorMedicamentos",
            "valorOPME",
            "valorGasesMedicinais",
        ):
            assert breakdown not in xml

    def test_generate_guide_xml_raises_when_authorization_number_has_no_matching_authorization(
        self,
    ):
        """guide.authorization_number alone gives a senha but no honest
        dataAutorizacao source (no matching approved Authorization row nor a
        typed authorization_date) — must fail loud instead of fabricating a
        date."""
        guide = self._make_internacao_guide()

        with pytest.raises(TISSXMLGenerationError, match="autorização resolvível"):
            generate_guide_xml(guide)


class InternacaoDadosResolutionTests(InternacaoFixtureMixin, XMLEngineTestCase):
    """Um teste por ramo de falha de ``_resolve_internacao_dados``.

    Todos os ramos existem porque ``ctm_internacaoDados``/
    ``ctm_internacaoDadosSaida`` pedem dado que pode legitimamente não existir
    (campos ``blank=True``, internações abertas, guias sem vínculo), e a política
    do módulo é falhar alto com mensagem acionável em vez de emitir XML com
    default inventado. O que cada teste verifica não é só "levantou": é que a
    mensagem diz ao FATURISTA o que preencher e onde — a mensagem É o produto
    aqui, do mesmo jeito que em ``InternacaoAuthorizationPrecedenceTests``.

    Todos os testes registram uma ``Authorization`` aprovada no setUp para que a
    falha medida seja a de ``dadosInternacao``, e não a de ``dadosAutorizacao``,
    que é resolvida antes e mascararia o ramo sob teste.
    """

    def setUp(self):
        super().setUp()
        self._approve_authorization()

    def test_guia_sem_internacao_vinculada_falha_alto(self):
        """``TISSGuide.admission`` é ``null=True`` (guia de internação avulsa é
        criável pela API) — mas sem ela não há NADA do bloco: nem taxonomia, nem
        período. É falha estrutural, com mensagem própria apontando a ponte que
        cria a guia do jeito certo."""
        guide = self._make_internacao_guide(admission=None)

        with pytest.raises(TISSXMLGenerationError) as exc_info:
            generate_guide_xml(guide)

        message = str(exc_info.value)
        assert "não está vinculada a nenhuma internação" in message
        assert "from-admission" in message

    def test_internacao_ainda_aberta_falha_alto_explicando_a_alta(self):
        """``dataFinalFaturamento``/``horaFinalFaturamento`` só têm fonte honesta
        depois da alta. A mensagem precisa dizer que a guia de resumo fecha
        DEPOIS da alta — e que faturamento parcial não existe no fluxo atual, que
        é a verdade e não uma limitação escondida."""
        admission = self._make_admission(discharge=False)
        guide = self._make_internacao_guide(admission=admission)

        with pytest.raises(TISSXMLGenerationError) as exc_info:
            generate_guide_xml(guide)

        message = str(exc_info.value)
        assert "ainda ABERTA" in message
        assert "só fecha depois da alta" in message
        assert "dataFinalFaturamento" in message

    def test_carater_atendimento_vazio_falha_alto_apontando_a_admissao(self):
        admission = self._make_admission(carater_atendimento="")
        guide = self._make_internacao_guide(admission=admission)

        with pytest.raises(TISSXMLGenerationError) as exc_info:
            generate_guide_xml(guide)

        message = str(exc_info.value)
        assert "carater_atendimento (dm_caraterAtendimento)" in message
        assert "tela de admissão" in message

    def test_tipo_internacao_vazio_falha_alto_apontando_a_admissao(self):
        admission = self._make_admission(tipo_internacao="")
        guide = self._make_internacao_guide(admission=admission)

        with pytest.raises(TISSXMLGenerationError) as exc_info:
            generate_guide_xml(guide)

        assert "tipo_internacao (dm_tipoInternacao)" in str(exc_info.value)

    def test_regime_internacao_vazio_falha_alto_apontando_a_admissao(self):
        admission = self._make_admission(regime_internacao="")
        guide = self._make_internacao_guide(admission=admission)

        with pytest.raises(TISSXMLGenerationError) as exc_info:
            generate_guide_xml(guide)

        assert "regime_internacao (dm_regimeInternacao)" in str(exc_info.value)

    def test_motivo_encerramento_vazio_falha_alto_apontando_a_tela_de_alta(self):
        """``disposition_ans_code`` é o único dos quatro que se preenche na ALTA,
        não na admissão — a mensagem tem de mandar o faturista para a tela certa,
        senão ele procura no lugar errado."""
        admission = self._make_admission(disposition_ans_code="")
        guide = self._make_internacao_guide(admission=admission)

        with pytest.raises(TISSXMLGenerationError) as exc_info:
            generate_guide_xml(guide)

        message = str(exc_info.value)
        assert "disposition_ans_code (dm_motivoSaida)" in message
        assert "tela de alta" in message

    def test_tipo_faturamento_vazio_falha_alto_apontando_a_propria_guia(self):
        """Único dos cinco que mora na GUIA, não na internação — e a mensagem tem
        de dizer isso, incluindo a janela em que ainda dá para preencher
        (rascunho; depois disso a trava de imutabilidade fecha o campo)."""
        guide = self._make_internacao_guide(tipo_faturamento="")

        with pytest.raises(TISSXMLGenerationError) as exc_info:
            generate_guide_xml(guide)

        message = str(exc_info.value)
        assert "tipo_faturamento (dm_tipoFaturamento)" in message
        assert "nesta guia, enquanto ainda estiver em rascunho" in message

    def test_campos_faltando_sao_relatados_todos_de_uma_vez(self):
        """Deliberadamente diferente de ``_resolve_internacao_authorization``,
        que tem um único modo de falha: aqui são cinco fontes independentes, e
        uma exceção por campo faria o faturista descobrir os buracos um a um, em
        cinco tentativas de gerar o XML. Uma exceção, a lista inteira."""
        admission = self._make_admission(
            carater_atendimento="",
            tipo_internacao="",
            regime_internacao="",
            disposition_ans_code="",
        )
        guide = self._make_internacao_guide(admission=admission, tipo_faturamento="")

        with pytest.raises(TISSXMLGenerationError) as exc_info:
            generate_guide_xml(guide)

        message = str(exc_info.value)
        for campo in (
            "carater_atendimento",
            "tipo_faturamento",
            "tipo_internacao",
            "regime_internacao",
            "disposition_ans_code",
        ):
            assert campo in message, campo

    def test_internacao_antiga_sem_taxonomias_nao_quebra_outros_tipos_de_guia(self):
        """Guarda da migration aditiva: o campo novo tem ``default=""`` e nada
        fora da guia de internação o lê. Uma guia de consulta continua válida com
        ``tipo_faturamento`` vazio — o resolver só roda para
        ``guide_type='internacao'``."""
        guide = self._make_consulta_guide()
        assert guide.tipo_faturamento == ""

        errors = validate_xml(generate_batch_xml(self._batch_with(guide)))

        assert errors == [], errors

    def _batch_with(self, guide):
        batch = TISSBatch.objects.create(provider=self.provider)
        batch.guides.add(guide)
        return batch


class InternacaoAuthorizationPrecedenceTests(InternacaoFixtureMixin, XMLEngineTestCase):
    """B10 — ``TISSGuide.authorization_date`` (digitação manual) as the
    LAST-RESORT fallback source for ``dataAutorizacao``, used ONLY when no
    approved ``Authorization`` resolves. One test per branch of the
    precedence documented on ``_resolve_internacao_authorization``'s
    docstring (xml_engine.py): resolved Authorization always wins; typed
    pair is a fallback, never an override; either field alone (with no
    resolvable Authorization) is not enough — fail loud with an actionable
    message telling the faturista what to do.
    """

    def test_resolved_authorization_wins_over_typed_date(self):
        """A resolvable Authorization row wins even when the guide ALSO
        carries a typed authorization_date — the typed decoy date must be
        ignored, not blended or preferred."""
        guide = self._make_internacao_guide()
        guide.authorization_date = datetime.date(2099, 1, 1)  # decoy, must be ignored
        guide.save(update_fields=["authorization_date"])
        Authorization.objects.create(
            patient=self.patient,
            provider=self.provider,
            tuss_code=self.tuss_consulta,
            status=Authorization.Status.APPROVED,
            valid_from=datetime.date(2026, 8, 1),
            authorization_number="AUTH123",
        )

        resolved = _resolve_internacao_authorization(guide)

        assert resolved == ("AUTH123", datetime.date(2026, 8, 1))

    def test_typed_date_used_as_fallback_when_no_authorization_resolves(self):
        """No resolvable Authorization → falls back to the guide's own typed
        (authorization_number, authorization_date) pair."""
        guide = self._make_internacao_guide(authorization_number="AUTH999")
        guide.authorization_date = datetime.date(2026, 8, 5)
        guide.save(update_fields=["authorization_date"])

        resolved = _resolve_internacao_authorization(guide)

        assert resolved == ("AUTH999", datetime.date(2026, 8, 5))

    def test_number_without_date_and_no_authorization_resolves_to_none(self):
        guide = self._make_internacao_guide(authorization_number="AUTH999")
        # authorization_date left unset (None), no Authorization row exists.
        assert _resolve_internacao_authorization(guide) is None

    def test_date_without_number_and_no_authorization_resolves_to_none(self):
        guide = self._make_internacao_guide(authorization_number="")
        guide.authorization_date = datetime.date(2026, 8, 5)
        guide.save(update_fields=["authorization_date"])
        assert _resolve_internacao_authorization(guide) is None

    def test_neither_number_nor_date_resolves_to_none(self):
        guide = self._make_internacao_guide(authorization_number="")
        assert _resolve_internacao_authorization(guide) is None

    def test_error_message_is_actionable_when_neither_source_resolves(self):
        """The failure message must tell the faturista what to DO (register
        an Authorization OR type both fields), not just name a missing
        field."""
        guide = self._make_internacao_guide(authorization_number="")

        with pytest.raises(TISSXMLGenerationError) as exc_info:
            generate_guide_xml(guide)

        message = str(exc_info.value)
        assert "registre uma authorization aprovada" in message.lower()
        assert "authorization_number" in message
        assert "authorization_date" in message

    def test_existing_guide_without_authorization_date_still_valid(self):
        """Pre-existing guides (created before this field existed) have
        authorization_date=None by default — the resolvable-Authorization
        path must keep working unmodified (regression guard for the
        aditiva/no-backfill migration)."""
        guide = self._make_internacao_guide()
        assert guide.authorization_date is None
        Authorization.objects.create(
            patient=self.patient,
            provider=self.provider,
            tuss_code=self.tuss_consulta,
            status=Authorization.Status.APPROVED,
            valid_from=datetime.date(2026, 8, 1),
            authorization_number="AUTH123",
        )

        resolved = _resolve_internacao_authorization(guide)

        assert resolved == ("AUTH123", datetime.date(2026, 8, 1))

    def test_typed_date_fallback_renders_dadosautorizacao_without_error(self):
        """Sanity: o caminho da data digitada está ligado de ponta a ponta em
        generate_batch_xml, não só no resolver isolado.

        MUDOU NESTA FATIA, e a mudança é o ponto: antes este teste só podia
        afirmar "sobrou o residual pré-existente de dadosBeneficiario, mas
        nenhum erro é de autorização", porque a guia ainda não fechava. Agora a
        guia fecha inteira — então a asserção honesta passou a ser XML
        totalmente válido pelo caminho da digitação, exatamente como pelo
        caminho da Authorization registrada."""
        guide = self._make_internacao_guide(authorization_number="AUTH-TYPED")
        guide.authorization_date = datetime.date(2026, 8, 1)
        guide.save(update_fields=["authorization_date"])
        batch = TISSBatch.objects.create(provider=self.provider)
        batch.guides.add(guide)

        xml = generate_batch_xml(batch)
        errors = validate_xml(xml)

        assert errors == [], errors
