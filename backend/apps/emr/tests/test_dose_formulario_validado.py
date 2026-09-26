"""
Ordem 028 — passo 0: três vermelhos.

INTENT v6 §Prioridade 3 / §Resultado: "motor determinístico autoritativo (o LLM
só explica)". Esta ordem fecha três furos medidos em 26/09:

  1. Uma ``DoseRule`` importada e **não validada** é hoje INERTE: o motor filtra
     ``validated=True`` (``dose_checker.py``), então nem sinaliza nem bloqueia.
     Deveria sinalizar (advisory, "caution"/"flagged") e nunca entrar no gate.
  2. ``DoseRuleViewSet.validate`` aceita qualquer usuário com
     ``pharmacy.catalog_manage`` — não exige cadastro profissional CRF (farmacêutico)
     nem grava o retrato do CRF que validou.
  3. ``prescription_safety`` ainda aceita ``type="dose"`` do LLM
     (``VALID_ALERT_TYPES``) e a task ``check_prescription_safety`` grava esse
     alerta mesmo quando o motor determinístico não deu nenhum veredito de dose.

═══════════════════════════════════════════════════════════════════════════════
ILLUSTRATIVE / SYNTHETIC TEST DATA — NOT CLINICAL TRUTH. "Ficticiol" é uma droga
fictícia; a banda 1–2 mg é um valor sintético só para exercitar o motor. Nada
aqui vem de bula ou de literatura, e nada disto pode ser copiado para produção.
═══════════════════════════════════════════════════════════════════════════════

Caminho real (lição da 021 — nada de SQL preparado pela fixture para fabricar a
condição medida):
  * teste 1 importa a regra pelo serviço real ``formulary_import`` (o mesmo
    caminho do comando ``import_formulary`` e da UI de upload) e roda o
    orquestrador real ``DoseCheckService.evaluate_prescription``;
  * teste 2 chama a action real ``DoseRuleViewSet.validate`` pela API;
  * teste 3 chama a task real ``check_prescription_safety``, com o gateway do
    LLM mockado (``apps.ai.gateway.ClaudeGateway.complete``) e o gate de
    consentimento satisfeito de verdade (DPA assinado pelo ``DPASigningService``
    real), exatamente como os testes das ordens 025 e 026.
"""

import datetime
import json
from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import FeatureFlag, Role, User
from apps.core.permissions import DEFAULT_ROLES
from apps.emr.models import (
    AISafetyAlert,
    Encounter,
    Patient,
    Prescription,
    PrescriptionItem,
    Professional,
)
from apps.emr.services.dose_safety import DoseCheckService
from apps.emr.services.prescription_safety_gate import has_blocking_safety_alert
from apps.pharmacy.models import Drug
from apps.test_utils import TenantTestCase

# CSV do formulário no formato de contrato ATUAL do importador (colunas de
# procedência entram só no passo 1 desta ordem — aqui exercitamos só o caminho
# de importação já existente). "Ficticiol" 1–2 mg é sintético.
_FICTICIOL_CSV = (
    "drug_name,drug_generic,strength_value,strength_unit,route,basis,"
    "dose_unit,min_per_dose,max_per_dose,absolute_max_dose,dose_role,enforcement,"
    "fonte_tipo,fonte_ref,fonte_trecho\n"
    "Ficticiol,ficticiolum,100.000,mg,IV,fixed,mg,1,2,2,maintenance,block,"
    "literatura,DOI:10.0000/ficticiol,Trecho ficticio de teste — nao clinico\n"
)


class UnvalidatedRuleOnlyFlagsNeverBlocksTest(TenantTestCase):
    """Vermelho 1: regra importada e não validada deve sinalizar (advisory),
    nunca bloquear. Hoje o motor filtra ``validated=True`` e a regra fica
    inteiramente inerte — nenhum alerta nasce."""

    def setUp(self):
        cache.clear()
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="dose_safety",
            defaults={"is_enabled": True},
        )
        role_md = Role.objects.create(name="medico-028a", permissions=DEFAULT_ROLES["medico"])
        self.doctor = User.objects.create_user(
            email="medico.028a@clinica.test",
            password="Medico!028#a",
            full_name="Médico 028a",
            role=role_md,
        )
        self.professional = Professional.objects.create(
            user=self.doctor, council_type="CRM", council_number="280280", council_state="SP"
        )
        self.patient = Patient.objects.create(
            full_name="Paciente 028a",
            cpf="111.444.777-35",
            birth_date=datetime.date(1985, 5, 5),
            gender="M",
        )
        self.encounter = Encounter.objects.create(
            patient=self.patient, professional=self.professional, encounter_date=timezone.now()
        )

    def _import_unvalidated_rule(self):
        """Caminho real: apps.pharmacy.services.formulary_import (não SQL cru)."""
        from apps.pharmacy.services.formulary_import import parse_and_validate, write_rows

        parsed = parse_and_validate(_FICTICIOL_CSV)
        write_rows(parsed)
        return Drug.objects.get(name="Ficticiol")

    def test_unvalidated_rule_signals_advisory_and_never_blocks(self):
        drug = self._import_unvalidated_rule()

        # Sanity: the importer never self-validates.
        from apps.pharmacy.models import DoseRule

        rule = DoseRule.objects.get(formulary__drug=drug)
        self.assertFalse(
            rule.validated, "pré-condição do teste: a regra deveria nascer não validada"
        )

        rx = Prescription.objects.create(
            encounter=self.encounter, patient=self.patient, prescriber=self.professional
        )
        item = PrescriptionItem.objects.create(
            prescription=rx,
            drug=drug,
            quantity=Decimal("1"),
            unit_of_measure="cx",
            dose_amount=Decimal("5"),  # banda sintética 1–2 mg, teto absoluto 2 mg
            dose_unit="mg",
            route="IV",
            frequency_per_day=1,
        )

        service = DoseCheckService(requesting_user=self.doctor)
        service.evaluate_prescription(rx, gate="sign")

        alerts = AISafetyAlert.objects.filter(
            prescription_item=item, source=AISafetyAlert.Source.ENGINE, alert_type="dose"
        )
        self.assertTrue(
            alerts.exists(),
            "esperava um alerta advisory do motor mesmo com a regra não validada; "
            "hoje a regra não validada é filtrada e fica inerte (nenhum alerta nasce)",
        )
        alert = alerts.get()
        self.assertEqual(alert.severity, "caution")
        self.assertEqual(alert.status, "flagged")
        self.assertIn(
            "validada por farmacêutico",
            alert.message,
            "a mensagem deveria citar que a regra ainda não foi validada por farmacêutico",
        )

        self.assertFalse(
            has_blocking_safety_alert(rx),
            "uma regra não validada nunca deve entrar no gate bloqueante",
        )


class ValidateRequiresCRFTest(TenantTestCase):
    """Vermelho 2: validar uma DoseRule sem cadastro profissional CRF deve ser
    recusado (403); com CRF ativo, o retrato do CRF (número, UF) e a data devem
    ser gravados. Hoje: qualquer usuário com a permissão valida (200), e não
    existe retrato do CRF."""

    def setUp(self):
        cache.clear()
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="pharmacy",
            defaults={"is_enabled": True},
        )
        self.role_farmaceutico = Role.objects.create(
            name="farmaceutico-028b",
            permissions=DEFAULT_ROLES["farmaceutico"],
        )
        self.user_sem_crf = User.objects.create_user(
            email="sem.crf.028b@clinica.test", password="SemCrf!028#b", role=self.role_farmaceutico
        )
        self.user_com_crf = User.objects.create_user(
            email="com.crf.028b@clinica.test", password="ComCrf!028#b", role=self.role_farmaceutico
        )

    def _client(self, user):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user=user)
        return c

    def _make_dose_rule(self):
        from apps.pharmacy.models import DoseRule, MedicationFormulary

        drug = Drug.objects.create(name="Ficticiol-028b", generic_name="ficticiolum_028b")
        formulary = MedicationFormulary.objects.create(
            drug=drug,
            strength_value=Decimal("100.000"),
            strength_unit="mg",
            route="IV",
            active=True,
        )
        rule = DoseRule.objects.create(
            formulary=formulary,
            basis="fixed",
            dose_unit="mg",
            min_per_dose=Decimal("1.0000"),
            max_per_dose=Decimal("2.0000"),
            absolute_max_dose=Decimal("2.0000"),
            active=True,
            validated=False,
        )
        return rule

    def test_validate_without_crf_is_refused(self):
        rule = self._make_dose_rule()

        resp = self._client(self.user_sem_crf).post(
            f"/api/v1/pharmacy/dose-rules/{rule.id}/validate/"
        )
        self.assertEqual(
            resp.status_code,
            403,
            "usuário sem cadastro profissional CRF não deveria conseguir validar",
        )
        rule.refresh_from_db()
        self.assertFalse(rule.validated, "a regra deve continuar não validada após a recusa")

    def test_validate_with_active_crf_records_portrait(self):
        rule = self._make_dose_rule()
        professional = Professional.objects.create(
            user=self.user_com_crf,
            council_type="CRF",
            council_number="028028",
            council_state="SP",
            is_active=True,
        )

        resp = self._client(self.user_com_crf).post(
            f"/api/v1/pharmacy/dose-rules/{rule.id}/validate/"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        rule.refresh_from_db()
        self.assertTrue(rule.validated)

        # Fase 1 acessava estes campos por getattr (nomes ainda não existiam).
        # Fase 2 (implementação): o retrato do CRF ganhou nomes próprios
        # (validado_crf_numero/uf); "quando" NÃO foi renomeado — continua
        # validated_at, por decisão explícita ("não renomeie coluna à toa").
        crf_numero = getattr(rule, "validado_crf_numero", None)
        crf_uf = getattr(rule, "validado_crf_uf", None)

        self.assertEqual(
            crf_numero,
            professional.council_number,
            "retrato do número do CRF não foi gravado na validação (campo ausente ou vazio)",
        )
        self.assertEqual(
            crf_uf,
            professional.council_state,
            "retrato da UF do CRF não foi gravado na validação (campo ausente ou vazio)",
        )
        self.assertIsNotNone(
            rule.validated_at,
            "data da validação (validated_at) não foi gravada",
        )


class LlmNeverSpeaksDoseWithoutEngineVerdictTest(TenantTestCase):
    """Vermelho 3: o LLM (prescription_safety) não pode produzir
    ``AISafetyAlert(source="llm", alert_type="dose")`` quando o motor
    determinístico não deu nenhum veredito de dose. Hoje ``"dose"`` ainda está
    em ``VALID_ALERT_TYPES`` e a task grava o que o LLM devolver."""

    def setUp(self):
        cache.clear()
        role_md = Role.objects.create(name="medico-028c", permissions=DEFAULT_ROLES["medico"])
        self.doctor = User.objects.create_user(
            email="medico.028c@clinica.test",
            password="Medico!028#c",
            full_name="Médico 028c",
            role=role_md,
        )
        self.professional = Professional.objects.create(
            user=self.doctor, council_type="CRM", council_number="280281", council_state="SP"
        )
        self.patient = Patient.objects.create(
            full_name="Paciente 028c",
            cpf="222.777.444-05",
            birth_date=datetime.date(1975, 3, 3),
            gender="F",
        )
        self.encounter = Encounter.objects.create(
            patient=self.patient, professional=self.professional, encounter_date=timezone.now()
        )
        self.prescription = Prescription.objects.create(
            encounter=self.encounter, patient=self.patient, prescriber=self.professional
        )
        # Droga SEM MedicationFormulary — o motor nunca dá veredito de dose
        # para ela (NOT_APPLICABLE), então não há "veredito do motor" algum.
        drug = Drug.objects.create(name="Ficticiol-028c", generic_name="ficticiolum_028c")
        self.item = PrescriptionItem.objects.create(
            prescription=self.prescription,
            drug=drug,
            generic_name="ficticiolum_028c",
            quantity=Decimal("1"),
            unit_of_measure="cx",
        )

    def _sign_dpa_for_real(self):
        from apps.core.services.dpa import DPASigningService

        signer = User.objects.create_user(
            email="signatario.028c@clinica.test", password="Signat!028#c", full_name="Signatário"
        )
        DPASigningService(requesting_user=signer).sign(tenant=self.__class__.tenant)

    @override_settings(FEATURE_AI_PRESCRIPTION_SAFETY=True)
    def test_llm_does_not_write_a_dose_alert_without_an_engine_verdict(self):
        from apps.emr.tasks import check_prescription_safety

        self._sign_dpa_for_real()

        # Gateway mockado (nunca chama a Anthropic de verdade) devolvendo um
        # alerta type="dose" — o gate de consentimento é satisfeito de verdade,
        # como nas ordens 025/026.
        llm_dose_alert = {
            "type": "dose",
            "severity": "caution",
            "message": "O LLM acha que esta dose sintética é alta.",
            "recommendation": "Confirme a dose.",
        }
        llm_response = json.dumps({"alerts": [llm_dose_alert]})
        with patch(
            "apps.ai.gateway.ClaudeGateway.complete",
            return_value=(llm_response, 40, 10),
        ) as complete:
            check_prescription_safety(str(self.item.id))

        complete.assert_called_once()

        self.assertFalse(
            AISafetyAlert.objects.filter(
                prescription_item=self.item,
                source=AISafetyAlert.Source.LLM,
                alert_type="dose",
            ).exists(),
            "o LLM não deve gravar um alerta de dose quando o motor não deu veredito",
        )
