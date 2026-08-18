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

from apps.billing.models import InsuranceProvider, TISSBatch, TISSGuide, TISSGuideItem
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

    Residual, itemized blockers found by walking tissGuiasV4_01_00.xsd (none
    fixable inside apps/billing without new data this task's scope excludes):

    - <dadosSolicitante> is mandatory: contratadoSolicitante (CNPJ/CPF/
      codigoPrestadorNaOperadora) + profissionalSolicitante (conselho/UF/CBOS
      of the REQUESTING professional). TISSGuide only tracks the executing
      professional (via encounter); nothing distinguishes solicitante from
      executante.
    - <dadosSolicitacao><caraterAtendimento> (eletivo/urgência, dm_caraterAtendimento)
      has no model field.
    - <valorTotal> is ct_guiaValorTotal — a breakdown (valorProcedimentos,
      valorTaxasAlugueis, valorMateriais, valorMedicamentos, valorOPME,
      valorGasesMedicinais, valorTotalGeral), not a single total_value.
    - ct_procedimentoExecutadoSadt requires reducaoAcrescimo (mandatory %
      discount/increase per item) — no TISSGuideItem field.
    - <dadosAtendimento> (ctm_sp-sadtAtendimento) requires tipoAtendimento
      and regimeAtendimento — no model field.

    Fixing this needs new fields on TISSGuide/TISSGuideItem (solicitante
    professional, caráter de atendimento, reducaoAcrescimo, valor breakdown)
    — a product/data-model decision out of this task's scope
    (backend/apps/billing/services/xml_engine.py + templates only).
    """

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "ctm_sp-sadtGuia requires dadosSolicitante (solicitante professional/"
            "contratado — not tracked), caraterAtendimento, a ct_guiaValorTotal "
            "breakdown, and per-item reducaoAcrescimo. None of these have a "
            "model field; templates only cannot close this gap without new "
            "TISSGuide/TISSGuideItem columns (out of scope — see 2.4 report)."
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
    """guiaResumoInternacao (ctm_internacaoResumoGuia) — NOT brought to
    conformance.

    Residual, itemized blockers (none fixable inside apps/billing without new
    data this task's scope excludes):

    - <numeroGuiaSolicitacaoInternacao> references the prior "guia de
      solicitação de internação" — no such document/number is tracked.
    - <dadosAutorizacao> is ct_autorizacaoInternacao (senha, dataAutorizacao,
      dataValidadeSenha) — partially covered by TISSGuide.authorization_number
      but not structured to match.
    - <dadosInternacao> (ctm_internacaoDados) requires caraterAtendimento,
      tipoFaturamento, tipoInternacao, regimeInternacao — enumerated TISS
      classifications with no equivalent on emr.Admission (which has
      admission_source/disposition, a materially different taxonomy).
    - <dadosSaidaInternacao> requires motivoEncerramento (dm_motivoSaida) —
      Admission.disposition exists but uses a different, non-ANS vocabulary;
      mapping it is a product decision, not a template fix.
    - <valorTotal> is ct_guiaValorTotal (breakdown), not a single total_value.

    Fixing this needs new fields/mappings on TISSGuide (or a documented
    Admission.disposition → dm_motivoSaida mapping) — out of this task's
    scope (backend/apps/billing/services/xml_engine.py + templates only).
    """

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "ctm_internacaoResumoGuia requires numeroGuiaSolicitacaoInternacao, "
            "dadosInternacao (caraterAtendimento/tipoFaturamento/tipoInternacao/"
            "regimeInternacao) and dadosSaidaInternacao (motivoEncerramento), "
            "none of which have a model field or an unambiguous mapping from "
            "emr.Admission. Templates only cannot close this gap (out of "
            "scope — see 2.4 report)."
        ),
    )
    def test_batch_envelope_with_internacao_guide_is_schema_valid(self):
        guide = TISSGuide.objects.create(
            guide_type="internacao",
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
