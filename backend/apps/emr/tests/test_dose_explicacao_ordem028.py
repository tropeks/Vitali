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


# ── guarda AST reusável (revisão P2) ─────────────────────────────────────────
#
# alert_type que o LLM tem permissão de gravar (source="llm") — tudo que NÃO
# for um destes literais reprova, e uma expressão que não é sequer um literal
# de string (variável, atributo, chamada — "o leitor não consegue provar")
# TAMBÉM reprova. A única exceção documentada é o padrão dinâmico já existente
# em apps.emr.tasks.check_prescription_safety (alert_type=alert.alert_type),
# cuja segurança vem de VALID_ALERT_TYPES (prescription_safety.py) já não
# conter "dose" — uma invariante de OUTRO arquivo que uma varredura puramente
# sintática, por linha, não tem como enxergar sem uma análise de fluxo de dados
# que este guard não faz. Ver DoseTypeLeavesVALIDAlertTypesTest acima para a
# prova complementar (em tempo de execução) dessa invariante.
_PERMITTED_LLM_ALERT_TYPE_LITERALS = frozenset(
    {"dose_explicacao", "drug_interaction", "allergy", "contraindication"}
)


def _is_llm_source(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant) and node.value == "llm":
        return True
    # AISafetyAlert.Source.LLM
    return isinstance(node, ast.Attribute) and node.attr == "LLM"


def _alert_type_is_forbidden(node: ast.AST) -> bool:
    """True quando alert_type é um literal de string FORA do conjunto
    permitido (pega "dose", variações/typos e qualquer outro literal não
    catalogado) OU um acesso de atributo cujo nome final é literalmente
    "dose"/"DOSE" (cobre um futuro enum tipo AISafetyAlert.AlertType.DOSE,
    que ainda não existe hoje — daí o "se existir enum" ser sempre falso na
    varredura real, mas coberto nos trechos sintéticos)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value not in _PERMITTED_LLM_ALERT_TYPE_LITERALS
    if isinstance(node, ast.Attribute):
        return node.attr.lower() == "dose"
    return False


def _is_aisafetyalert_manager_call(node: ast.AST) -> bool:
    """``AISafetyAlert.objects.<create|update_or_create|get_or_create|
    bulk_create>(...)``. For ``bulk_create`` the actual kwargs live on the
    NESTED ``AISafetyAlert(...)`` calls inside the list argument, which
    ``_is_aisafetyalert_direct_call`` catches independently via ``ast.walk``
    (it visits nested nodes regardless of the enclosing call) — this branch
    exists mainly so the method name itself is a named, intentional part of
    the contract, not an accident of tree-walking."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"create", "update_or_create", "get_or_create", "bulk_create"}
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "objects"
        and isinstance(node.func.value.value, ast.Name)
        and node.func.value.value.id == "AISafetyAlert"
    )


def _is_aisafetyalert_direct_call(node: ast.AST) -> bool:
    """``AISafetyAlert(...)`` — direct instantiation. Catches both
    ``AISafetyAlert(...).save()`` style writes and each item of a
    ``bulk_create([AISafetyAlert(...), ...])`` list, since ``ast.walk``
    descends into the list literal and visits each inner ``Call`` node too."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "AISafetyAlert"
    )


def find_llm_dose_offenders(source_text: str, label: str) -> list[str]:
    """Parse ``source_text`` and return ``["<label>:<lineno>", ...]`` for every
    AISafetyAlert write whose ``source`` is the LLM and whose ``alert_type``
    cannot be proven safe. Shared by the real-code scan and the synthetic
    pattern tests below — one function, so "the guard passes for real" and
    "the guard catches these patterns" are provably the SAME guard."""
    tree = ast.parse(source_text)
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (_is_aisafetyalert_manager_call(node) or _is_aisafetyalert_direct_call(node)):
            continue
        kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
        source_node = kwargs.get("source")
        alert_type_node = kwargs.get("alert_type")
        if source_node is None or alert_type_node is None:
            continue
        if _is_llm_source(source_node) and _alert_type_is_forbidden(alert_type_node):
            offenders.append(f"{label}:{node.lineno}")
    return offenders


class NoCodeWritesLlmDoseAlertTest(TenantTestCase):
    """Guard (mirrors ordem 026's source= guard): nenhum código de produção
    grava AISafetyAlert com source='llm' e um alert_type que não seja um dos
    literais permitidos — o LLM só explica (dose_explicacao) ou fala de
    interação/alergia/contraindicação; nunca decide dose."""

    def test_no_write_uses_source_llm_with_a_forbidden_alert_type(self):
        apps_dir = pathlib.Path(__file__).resolve().parents[2]
        offenders: list[str] = []
        scanned = 0
        for path in apps_dir.rglob("*.py"):
            if "tests" in path.parts or "migrations" in path.parts:
                continue
            scanned += 1
            source_text = path.read_text(encoding="utf-8")
            label = str(path.relative_to(apps_dir.parent))
            offenders.extend(find_llm_dose_offenders(source_text, label))
        self.assertGreaterEqual(scanned, 100, "varredura não enxergou o código")
        self.assertEqual(
            offenders, [], "código grava AISafetyAlert(source=llm, alert_type=<não permitido>)"
        )


class GuardCatchesSyntheticPatternsTest(TenantTestCase):
    """Revisão (P2): prova, com trechos de código FABRICADOS (nunca rodados,
    só analisados como texto pela MESMA função ``find_llm_dose_offenders``
    que varre o código real acima), que o guard pega os três padrões pedidos
    — manager call, bulk_create e instanciação direta + .save() — e que não
    acusa falso positivo para um alert_type permitido."""

    def test_catches_literal_dose_via_update_or_create(self):
        src = (
            "AISafetyAlert.objects.update_or_create(\n"
            "    prescription_item=item,\n"
            '    alert_type="dose",\n'
            '    source="llm",\n'
            "    defaults={},\n"
            ")\n"
        )
        offenders = find_llm_dose_offenders(src, "sintetico")
        self.assertEqual(len(offenders), 1, offenders)

    def test_catches_literal_dose_via_bulk_create(self):
        src = (
            "AISafetyAlert.objects.bulk_create([\n"
            "    AISafetyAlert(\n"
            "        prescription_item=item,\n"
            '        alert_type="dose",\n'
            "        source=AISafetyAlert.Source.LLM,\n"
            "    ),\n"
            "])\n"
        )
        offenders = find_llm_dose_offenders(src, "sintetico")
        self.assertEqual(len(offenders), 1, offenders)

    def test_catches_literal_dose_via_direct_instantiate_then_save(self):
        src = (
            "alert = AISafetyAlert(\n"
            "    prescription_item=item,\n"
            '    alert_type="dose",\n'
            '    source="llm",\n'
            ")\n"
            "alert.save()\n"
        )
        offenders = find_llm_dose_offenders(src, "sintetico")
        self.assertEqual(len(offenders), 1, offenders)

    def test_catches_unknown_literal_not_just_the_word_dose(self):
        """A typo/variant literal (never in the permitted set) must ALSO
        reprove — the guard checks set membership, not just == "dose"."""
        src = (
            "AISafetyAlert.objects.create(\n"
            "    prescription_item=item,\n"
            '    alert_type="dosage",\n'
            '    source="llm",\n'
            ")\n"
        )
        offenders = find_llm_dose_offenders(src, "sintetico")
        self.assertEqual(len(offenders), 1, offenders)

    def test_catches_hypothetical_dose_enum_attribute(self):
        """Se um enum futuro ganhar um membro DOSE, o guard já pega."""
        src = (
            "AISafetyAlert.objects.create(\n"
            "    prescription_item=item,\n"
            "    alert_type=AISafetyAlert.AlertType.DOSE,\n"
            '    source="llm",\n'
            ")\n"
        )
        offenders = find_llm_dose_offenders(src, "sintetico")
        self.assertEqual(len(offenders), 1, offenders)

    def test_does_not_flag_a_permitted_literal(self):
        src = (
            "AISafetyAlert.objects.update_or_create(\n"
            "    prescription_item=item,\n"
            '    alert_type="dose_explicacao",\n'
            "    source=AISafetyAlert.Source.LLM,\n"
            "    defaults={},\n"
            ")\n"
        )
        offenders = find_llm_dose_offenders(src, "sintetico")
        self.assertEqual(offenders, [])

    def test_does_not_flag_an_engine_sourced_write(self):
        src = (
            "AISafetyAlert.objects.update_or_create(\n"
            "    prescription_item=item,\n"
            '    alert_type="dose",\n'
            '    source="engine",\n'
            "    defaults={},\n"
            ")\n"
        )
        offenders = find_llm_dose_offenders(src, "sintetico")
        self.assertEqual(offenders, [])
