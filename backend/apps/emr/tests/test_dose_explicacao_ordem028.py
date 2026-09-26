"""
Ordem 028 passo 3 — "o LLM só explica, nunca decide" sobre dose.

INTENT v6 §Resultado: "motor determinístico autoritativo (o LLM só explica)".

Cobre:
  * sem veredito do motor (SAFE/NOT_APPLICABLE, ou nenhum veredito de dose
    algum), nenhuma linha ``dose*`` do LLM nasce;
  * com veredito (bloqueante ou advisory), a task
    ``apps.emr.tasks.explain_dose_verdict`` grava UMA linha
    ``AISafetyAlert(source="llm", alert_type="dose_explicacao")`` com FK
    ``explica`` para o alerta do motor, e o gate é idêntico com e sem ela;
  * o gate de consentimento fechado (flag global off, sem DPA, circuito
    aberto) não produz explicação nenhuma, e o veredito do motor fica intacto;
  * guarda por AST (mirror da 026): nenhum código de produção grava
    ``AISafetyAlert`` com ``source="llm"`` e ``alert_type="dose"``.

═══════════════════════════════════════════════════════════════════════════════
ILLUSTRATIVE TEST DATA — NOT CLINICAL TRUTH. Droga e banda fabricadas.
═══════════════════════════════════════════════════════════════════════════════
"""

import ast
import datetime
import json
import pathlib
from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone

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
from apps.pharmacy.models import DoseRule, Drug, MedicationFormulary
from apps.test_utils import TenantTestCase


def _make_validated_perkg_drug(name="FAKE-Explica-PerKg"):
    """ILLUSTRATIVE per_kg formulary: band [0.5,1.0] mg/kg, abs cap 50mg. NOT clinical."""
    drug = Drug.objects.create(name=name, generic_name="fake_explica_perkg")
    formulary = MedicationFormulary.objects.create(
        drug=drug,
        strength_value=Decimal("10.000"),
        strength_unit="mg",
        route="IV",
        active=True,
    )
    DoseRule.objects.create(
        formulary=formulary,
        basis="per_kg",
        dose_unit="mg",
        min_per_kg=Decimal("0.5000"),
        max_per_kg=Decimal("1.0000"),
        absolute_max_dose=Decimal("50.0000"),
        active=True,
        validated=True,
    )
    return drug


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
class DoseExplanationTest(TenantTestCase):
    def setUp(self):
        cache.clear()
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant, module_key="dose_safety", defaults={"is_enabled": True}
        )
        role = Role.objects.create(name="medico-028explica", permissions=DEFAULT_ROLES["medico"])
        self.doctor = User.objects.create_user(
            email="medico.028explica@clinica.test", password="Medico!028#x", role=role
        )
        self.professional = Professional.objects.create(
            user=self.doctor, council_type="CRM", council_number="028777", council_state="SP"
        )
        self.patient = Patient.objects.create(
            full_name="Paciente 028explica",
            cpf="333.222.111-99",
            birth_date=datetime.date(1990, 1, 1),
            gender="M",
        )
        self.encounter = Encounter.objects.create(
            patient=self.patient, professional=self.professional, encounter_date=timezone.now()
        )

    def _sign_dpa_and_enable(self):
        from apps.core.services.dpa import DPASigningService

        signer = User.objects.create_user(
            email=f"signatario.{self.id()}@clinica.test", password="Signat!028#x"
        )
        DPASigningService(requesting_user=signer).sign(tenant=self.__class__.tenant)

    def _make_rx(self, *, dose, drug=None):
        drug = drug or _make_validated_perkg_drug()
        rx = Prescription.objects.create(
            encounter=self.encounter, patient=self.patient, prescriber=self.professional
        )
        item = PrescriptionItem.objects.create(
            prescription=rx,
            drug=drug,
            quantity=Decimal("5"),
            unit_of_measure="un",
            dose_amount=dose,
            dose_unit="mg",
            route="IV",
            frequency_per_day=1,
        )
        # Fresh weight so the per-kg band resolves.
        from apps.emr.models import VitalSigns

        VitalSigns.objects.create(encounter=self.encounter, weight_kg=Decimal("10.00"))
        return rx, item

    @override_settings(FEATURE_AI_PRESCRIPTION_SAFETY=True)
    def test_out_of_range_verdict_gets_an_explanation_row_linked_to_the_engine_alert(self):
        self._sign_dpa_and_enable()
        rx, item = self._make_rx(dose=Decimal("40"))  # band [5,10] → OUT_OF_RANGE

        llm_response = json.dumps({"explanation": "A dose está acima da faixa esperada."})
        with patch(
            "apps.ai.gateway.ClaudeGateway.complete", return_value=(llm_response, 30, 20)
        ) as complete:
            with self.captureOnCommitCallbacks(execute=True):
                DoseCheckService(requesting_user=self.doctor).evaluate_prescription(rx, gate="sign")

        complete.assert_called_once()

        engine_alert = AISafetyAlert.objects.get(
            prescription_item=item, source=AISafetyAlert.Source.ENGINE, alert_type="dose"
        )
        explanation = AISafetyAlert.objects.get(
            prescription_item=item, source=AISafetyAlert.Source.LLM, alert_type="dose_explicacao"
        )
        self.assertEqual(explanation.explica_id, engine_alert.id)
        self.assertEqual(explanation.severity, "caution")
        self.assertIn("faixa esperada", explanation.message)

        # The gate is IDENTICAL with the explanation present: it never blocks
        # or unblocks anything by itself.
        from apps.emr.services.prescription_safety_gate import has_blocking_safety_alert

        self.assertTrue(has_blocking_safety_alert(rx))  # still blocked by the ENGINE alert
        explanation.delete()
        self.assertTrue(has_blocking_safety_alert(rx))  # unaffected by the explanation's absence

    def test_safe_verdict_produces_no_explanation(self):
        """SAFE never reaches ``_raise_blocking_alert``/``_raise_advisory_alert``
        — no scheduling call happens at all, so no explanation is written."""
        self._sign_dpa_and_enable()
        with override_settings(FEATURE_AI_PRESCRIPTION_SAFETY=True):
            rx, item = self._make_rx(dose=Decimal("7"))  # band [5,10] → SAFE
            with patch("apps.ai.gateway.ClaudeGateway.complete") as complete:
                with self.captureOnCommitCallbacks(execute=True):
                    DoseCheckService(requesting_user=self.doctor).evaluate_prescription(
                        rx, gate="sign"
                    )
            complete.assert_not_called()

        self.assertFalse(
            AISafetyAlert.objects.filter(
                prescription_item=item, alert_type="dose_explicacao"
            ).exists()
        )

    def test_not_applicable_produces_no_explanation(self):
        """A drug with no MedicationFormulary → NOT_APPLICABLE → no engine
        alert at all → no explanation."""
        self._sign_dpa_and_enable()
        drug = Drug.objects.create(name="FAKE-Explica-NoFormulary", generic_name="fake_nf")
        with override_settings(FEATURE_AI_PRESCRIPTION_SAFETY=True):
            rx, item = self._make_rx(dose=Decimal("7"), drug=drug)
            with patch("apps.ai.gateway.ClaudeGateway.complete") as complete:
                with self.captureOnCommitCallbacks(execute=True):
                    DoseCheckService(requesting_user=self.doctor).evaluate_prescription(
                        rx, gate="sign"
                    )
            complete.assert_not_called()

        self.assertFalse(
            AISafetyAlert.objects.filter(prescription_item=item, source="engine").exists()
        )
        self.assertFalse(
            AISafetyAlert.objects.filter(
                prescription_item=item, alert_type="dose_explicacao"
            ).exists()
        )

    def test_consent_gate_closed_produces_no_explanation_engine_untouched(self):
        """FEATURE_AI_PRESCRIPTION_SAFETY off (no DPA signed either) → the
        explanation task's own consent gate refuses → nothing written, and the
        engine's blocking verdict is completely unaffected."""
        rx, item = self._make_rx(dose=Decimal("40"))  # OUT_OF_RANGE
        with patch("apps.ai.gateway.ClaudeGateway.complete") as complete:
            with self.captureOnCommitCallbacks(execute=True):
                DoseCheckService(requesting_user=self.doctor).evaluate_prescription(rx, gate="sign")
        complete.assert_not_called()

        engine_alert = AISafetyAlert.objects.get(
            prescription_item=item, source=AISafetyAlert.Source.ENGINE, alert_type="dose"
        )
        self.assertEqual(engine_alert.severity, "contraindication")
        self.assertEqual(engine_alert.status, "flagged")
        self.assertFalse(
            AISafetyAlert.objects.filter(
                prescription_item=item, alert_type="dose_explicacao"
            ).exists()
        )


class DoseTypeLeavesVALIDAlertTypesTest(TenantTestCase):
    """`dose` no longer round-trips through the generic LLM safety checker —
    it is reserved for the engine (source=engine) and the explainer
    (dose_explicacao, source=llm)."""

    def test_dose_not_in_valid_alert_types(self):
        from apps.emr.services.prescription_safety import VALID_ALERT_TYPES

        self.assertNotIn("dose", VALID_ALERT_TYPES)


class NoCodeWritesLlmDoseAlertTest(TenantTestCase):
    """Guard (mirrors ordem 026's source= guard): nenhum código de produção
    grava AISafetyAlert com source='llm' e alert_type='dose' — o LLM só
    explica (dose_explicacao), nunca decide (dose)."""

    @staticmethod
    def _is_llm_source(node: ast.AST) -> bool:
        if isinstance(node, ast.Constant) and node.value == "llm":
            return True
        # AISafetyAlert.Source.LLM
        return isinstance(node, ast.Attribute) and node.attr == "LLM"

    @staticmethod
    def _is_literal_dose(node: ast.AST) -> bool:
        return isinstance(node, ast.Constant) and node.value == "dose"

    def test_no_upsert_writes_source_llm_alert_type_dose(self):
        apps_dir = pathlib.Path(__file__).resolve().parents[2]
        offenders = []
        for path in apps_dir.rglob("*.py"):
            if "tests" in path.parts or "migrations" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"create", "update_or_create", "get_or_create"}
                    and isinstance(node.func.value, ast.Attribute)
                    and node.func.value.attr == "objects"
                    and isinstance(node.func.value.value, ast.Name)
                    and node.func.value.value.id == "AISafetyAlert"
                ):
                    continue
                kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
                source_node = kwargs.get("source")
                alert_type_node = kwargs.get("alert_type")
                if source_node is None or alert_type_node is None:
                    continue
                if self._is_llm_source(source_node) and self._is_literal_dose(alert_type_node):
                    offenders.append(f"{path.relative_to(apps_dir.parent)}:{node.lineno}")
        self.assertGreaterEqual(
            len(list(apps_dir.rglob("*.py"))), 100, "varredura não enxergou o código"
        )
        self.assertEqual(offenders, [], "código grava AISafetyAlert(source=llm, alert_type=dose)")
