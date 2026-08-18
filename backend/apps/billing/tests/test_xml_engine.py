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

import pytest

from apps.billing.models import (
    Authorization,
    InsuranceProvider,
    TISSBatch,
    TISSGuide,
    TISSGuideItem,
)
from apps.billing.services.xml_engine import (
    TISSXMLGenerationError,
    generate_batch_xml,
    generate_guide_xml,
    validate_xml,
)
from apps.core.models import Role, TUSSCode, User
from apps.emr.models import Encounter, Patient, Professional
from apps.test_utils import TenantTestCase


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


class ConsultaGuideXMLConformanceTests(XMLEngineTestCase):
    """guiaConsulta — brought to full TISS 4.01.00 conformance (see 2.4)."""

    def test_batch_envelope_with_one_consulta_guide_is_schema_valid(self):
        guide = self._make_consulta_guide()
        batch = TISSBatch.objects.create(provider=self.provider)
        batch.guides.add(guide)

        xml = generate_batch_xml(batch)
        errors = validate_xml(xml)

        assert errors == [], errors

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


class InternacaoGuideXMLConformanceTests(XMLEngineTestCase):
    """guiaResumoInternacao (ctm_internacaoResumoGuia) — NOT brought to full
    conformance in this slice, but the dadosAutorizacao gap is CLOSED.

    Onda 4 Fatia 0 ported cabecalhoGuia and resolved
    numeroGuiaSolicitacaoInternacao (self-reference, Capitão's product
    decision). This slice resolves <dadosAutorizacao> (ct_autorizacaoInternacao)
    from data that already exists — no new model field:

    - senha ← TISSGuide.authorization_number (models.py:367) when set, else
      the resolved Authorization row's own authorization_number.
    - dataAutorizacao ← the resolved Authorization.valid_from (models.py:241)
      — NEVER fabricated.
    - Resolution reuses the SAME rule the glosa-safety engine already applies
      (G3d — glosa_safety.py:401-432 _approved_authorization_coverage /
      models.py:165-176, :196-199): an APPROVED Authorization row for the
      guide's patient+provider whose validity window contains the guide's
      effective date, matching by TUSS or generic (tuss_code NULL). See
      xml_engine._resolve_internacao_authorization for the adapted (one-row,
      not just coverage-set) version.
    - When guide.authorization_number is filled but NO Authorization row
      resolves, there is a senha but no honest date source. We do NOT invent
      one: generate_guide_xml raises TISSXMLGenerationError (fail loud),
      matching the file's existing pattern for genuine data gaps (honorarios,
      wrong item count, mixed-type batch) instead of emitting a guide with a
      fabricated authorization date.

    Measured before this slice: 1 residual error (missing dadosAutorizacao).
    Measured after, with a resolvable Authorization: 1 residual error, now
    further into the sequence — <dadosBeneficiario> is next, and it is a
    genuine DATA gap, not form. Everything after it (dadosExecutante,
    dadosInternacao, dadosSaidaInternacao, valorTotal breakdown) is unreached
    as a consequence and remains real, separately itemized gaps for Fatia 2+
    — see docs/research/VITALI_ONDA4_TISS_MODELAGEM.md §3.
    """

    def _make_internacao_guide(self, *, authorization_number="AUTH123"):
        guide = TISSGuide.objects.create(
            guide_type="internacao",
            encounter=self.encounter,
            patient=self.patient,
            provider=self.provider,
            insured_card_number="1234567890123456",
            authorization_number=authorization_number,
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

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "ctm_internacaoResumoGuia: cabecalhoGuia, "
            "numeroGuiaSolicitacaoInternacao and dadosAutorizacao now form- "
            "AND data-complete (Onda 4). Residual is a genuine data gap, not "
            "form: <dadosBeneficiario> is the next mandatory element and is "
            "out of this slice's scope. Everything after it (dadosExecutante, "
            "dadosInternacao, dadosSaidaInternacao, valorTotal breakdown) is "
            "unreached as a consequence — see Onda 4 report."
        ),
    )
    def test_batch_envelope_with_internacao_guide_is_schema_valid(self):
        """Guide WITH a resolvable Authorization (senha + honest date)."""
        guide = self._make_internacao_guide()
        Authorization.objects.create(
            patient=self.patient,
            provider=self.provider,
            tuss_code=self.tuss_consulta,
            status=Authorization.Status.APPROVED,
            valid_from=datetime.date(2026, 8, 1),
            authorization_number="AUTH123",
        )
        batch = TISSBatch.objects.create(provider=self.provider)
        batch.guides.add(guide)

        xml = generate_batch_xml(batch)
        errors = validate_xml(xml)

        assert errors == [], errors

    def test_generate_guide_xml_raises_when_authorization_number_has_no_matching_authorization(
        self,
    ):
        """guide.authorization_number alone gives a senha but no honest
        dataAutorizacao source (no matching approved Authorization row) —
        must fail loud instead of fabricating a date."""
        guide = self._make_internacao_guide()

        with pytest.raises(TISSXMLGenerationError, match="autorização resolvível"):
            generate_guide_xml(guide)
