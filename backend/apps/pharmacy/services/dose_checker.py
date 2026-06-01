"""Deterministic dose-check engine — dose-safety wedge PR B.

LIFE-SAFETY logic. This module is PURE and DETERMINISTIC:

  * NO database writes (it only *reads* the formulary/rules passed to it, and
    only via the ``drug`` ORM object the caller already loaded).
  * NO LLM, NO network, NO clock except the ``now`` the caller injects.
  * Decimal-only arithmetic — NEVER float. A float mid-calculation can silently
    misrepresent a dose; for a medication ceiling that is unacceptable.
  * Every reason string is a deterministic, human-readable pt-BR sentence built
    from the numbers — it is NOT an LLM explanation. The LLM (source="llm")
    explains; this engine (source="engine") DECIDES.

Why this lives in ``apps.pharmacy`` (not ``apps.emr``):
  The engine must read ``pharmacy.MedicationFormulary`` / ``pharmacy.DoseRule``.
  The import boundary in this codebase is ``pharmacy -> emr`` is allowed but
  ``emr -> pharmacy`` is only done lazily (string FKs, local imports) to avoid a
  circular import at module load. Putting the engine in pharmacy lets it import
  pharmacy models at module level with zero risk. The emr-side orchestrator
  (apps.emr.services.dose_safety) imports this engine lazily.

PR A shipped the schema (MedicationFormulary, DoseRule, structured dose fields on
PrescriptionItem, the AISafetyAlert.source split). This engine consumes those
invariants. NO clinical numbers live here — the formulary is pharmacist-supplied
external truth (decision D-T1) and the production tables stay empty.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import Enum
from uuid import UUID

logger = logging.getLogger(__name__)

# Quantization for every comparison. The schema stores per-dose figures at 4
# decimal places (Decimal(12,4)); we quantize derived bounds to the same scale
# so a per-kg multiplication can't introduce phantom precision that flips a
# boundary comparison. Boundary (== max / == min) is ALLOWED (see check()).
_QUANT = Decimal("0.0001")


def _q(value: Decimal) -> Decimal:
    """Quantize a Decimal to the canonical 4-place dose scale (half-up)."""
    return value.quantize(_QUANT, rounding=ROUND_HALF_UP)


class Verdict(str, Enum):
    """Engine verdict. Maps to the locked fail decision table (plan §2.6)."""

    SAFE = "SAFE"
    OUT_OF_RANGE = "OUT_OF_RANGE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    DATA_MISSING = "DATA_MISSING"
    WEIGHT_GATE = "WEIGHT_GATE"
    ENGINE_ERROR = "ENGINE_ERROR"


@dataclass(frozen=True)
class DoseVerdict:
    """Immutable result of a single dose check.

    ``expected_low`` / ``expected_high`` are the patient-specific computed band
    (per-kg multiplied by weight, or the fixed band). ``max_per_dose`` echoes the
    universal absolute ceiling that was enforced. ``reason`` is a deterministic
    pt-BR sentence (NOT an LLM explanation). ``rule_id`` is the DoseRule that
    drove the verdict, for the flywheel / audit trail.
    """

    verdict: Verdict
    reason: str
    expected_low: Decimal | None = None
    expected_high: Decimal | None = None
    max_per_dose: Decimal | None = None
    rule_id: UUID | None = None


class DoseChecker:
    """Pure, deterministic dose checker. No state, no I/O."""

    @staticmethod
    def check(
        *,
        drug,
        dose_amount: Decimal | None,
        dose_unit: str | None,
        route: str | None,
        frequency_per_day: int | None,
        patient_age_days: int,
        weight_kg: Decimal | None,
        weight_recorded_at: datetime | None,
        now: datetime,
        weight_staleness_days: int,
    ) -> DoseVerdict:
        """Evaluate a single prescribed dose against the formulary band.

        All numeric inputs that participate in arithmetic MUST be Decimal (or
        None). The whole body is wrapped so any unexpected exception degrades to
        ENGINE_ERROR (advisory) rather than crashing the gate — the caller also
        catches, defence in depth.
        """
        try:
            return DoseChecker._check(
                drug=drug,
                dose_amount=dose_amount,
                dose_unit=dose_unit,
                route=route,
                frequency_per_day=frequency_per_day,
                patient_age_days=patient_age_days,
                weight_kg=weight_kg,
                weight_recorded_at=weight_recorded_at,
                now=now,
                weight_staleness_days=weight_staleness_days,
            )
        except Exception:  # pragma: no cover - exercised via the ENGINE_ERROR test
            logger.exception("DoseChecker raised — degrading to ENGINE_ERROR (advisory).")
            return DoseVerdict(
                verdict=Verdict.ENGINE_ERROR,
                reason=(
                    "Falha interna ao verificar a dose; verificação indisponível. "
                    "Confira a dose manualmente."
                ),
            )

    # ── internal (may raise; check() wraps it) ────────────────────────────────

    @staticmethod
    def _check(
        *,
        drug,
        dose_amount: Decimal | None,
        dose_unit: str | None,
        route: str | None,
        frequency_per_day: int | None,
        patient_age_days: int,
        weight_kg: Decimal | None,
        weight_recorded_at: datetime | None,
        now: datetime,
        weight_staleness_days: int,
    ) -> DoseVerdict:
        # 1. Formulary gate: no row, or inactive → NOT_APPLICABLE (no badge, no
        #    false green). Existence of an active row is the dose-checkable predicate.
        formulary = getattr(drug, "formulary", None)
        if formulary is None or not formulary.active:
            return DoseVerdict(
                verdict=Verdict.NOT_APPLICABLE,
                reason="Medicamento não está no formulário verificável de doses.",
            )

        # 2. Band selection: active rules matching age + weight band. Null bound =
        #    unbounded. Rule absent ≠ unsafe → NOT_APPLICABLE (but logged).
        rule = DoseChecker._select_rule(
            formulary=formulary,
            patient_age_days=patient_age_days,
            weight_kg=weight_kg,
            route=route,
        )
        if rule is None:
            logger.info(
                "DoseChecker: no matching DoseRule for formulary=%s age_days=%s weight=%s "
                "route=%s — NOT_APPLICABLE.",
                getattr(formulary, "id", None),
                patient_age_days,
                weight_kg,
                route,
            )
            return DoseVerdict(
                verdict=Verdict.NOT_APPLICABLE,
                reason="Nenhuma regra de dose aplicável à faixa etária/peso deste paciente.",
            )

        # 3. Unit coherence — NEVER coerce mg↔mL↔mcg. Mismatch or missing dose →
        #    DATA_MISSING (advisory), never a silent wrong comparison.
        if dose_amount is None:
            return DoseVerdict(
                verdict=Verdict.DATA_MISSING,
                reason="Dose não informada de forma estruturada; verificação de dose indisponível.",
                rule_id=rule.id,
            )
        if not dose_unit or dose_unit != rule.dose_unit:
            return DoseVerdict(
                verdict=Verdict.DATA_MISSING,
                reason=(
                    f"Unidade da dose ({dose_unit or 'não informada'}) não confere com a "
                    f"unidade da regra ({rule.dose_unit}); não é seguro converter "
                    "automaticamente. Verificação de dose indisponível."
                ),
                rule_id=rule.id,
            )

        dose = Decimal(dose_amount)
        absolute_max = Decimal(rule.absolute_max_dose)

        # 4. Compute the expected band per basis.
        if rule.basis == "per_kg":
            # Per-kg REQUIRES a fresh weight.
            if weight_kg is None:
                return DoseVerdict(
                    verdict=Verdict.WEIGHT_GATE,
                    reason=(
                        "Dose por kg exige o peso do paciente, que não está registrado. "
                        "Registre o peso para liberar a verificação de dose."
                    ),
                    rule_id=rule.id,
                )
            if DoseChecker._weight_is_stale(weight_recorded_at, now, weight_staleness_days):
                return DoseVerdict(
                    verdict=Verdict.WEIGHT_GATE,
                    reason=(
                        f"Peso do paciente está desatualizado (> {weight_staleness_days} dias). "
                        "Atualize o peso para liberar a verificação de dose por kg."
                    ),
                    rule_id=rule.id,
                )
            weight = Decimal(weight_kg)
            expected_low = _q(Decimal(rule.min_per_kg) * weight)
            expected_high = _q(Decimal(rule.max_per_kg) * weight)
        else:  # basis == "fixed"
            expected_low = _q(Decimal(rule.min_per_dose))
            expected_high = _q(Decimal(rule.max_per_dose))

        dose = _q(dose)
        absolute_max = _q(absolute_max)

        # 5. ALWAYS enforce the universal absolute ceiling FIRST. This is the
        #    weight-typo / per-kg-math floor: a bad weight (70 kg typed 700 kg)
        #    can push the per-kg band itself above a lethal absolute dose, so the
        #    absolute cap must fire even when the dose sits *inside* the per-kg band.
        if dose > absolute_max:
            return DoseVerdict(
                verdict=Verdict.OUT_OF_RANGE,
                reason=(
                    f"Dose {dose} {rule.dose_unit} excede o teto absoluto de "
                    f"{absolute_max} {rule.dose_unit} por administração."
                ),
                expected_low=expected_low,
                expected_high=expected_high,
                max_per_dose=absolute_max,
                rule_id=rule.id,
            )

        # 6. Range check (boundary == low/high is allowed).
        if dose < expected_low or dose > expected_high:
            return DoseVerdict(
                verdict=Verdict.OUT_OF_RANGE,
                reason=(
                    f"Dose {dose} {rule.dose_unit} fora do intervalo esperado "
                    f"{expected_low}–{expected_high} {rule.dose_unit}."
                ),
                expected_low=expected_low,
                expected_high=expected_high,
                max_per_dose=absolute_max,
                rule_id=rule.id,
            )

        # 7. Max-per-day: frequency × per-dose vs the daily cap.
        if frequency_per_day and rule.max_per_day is not None:
            daily = _q(dose * Decimal(int(frequency_per_day)))
            max_per_day = _q(Decimal(rule.max_per_day))
            if daily > max_per_day:
                return DoseVerdict(
                    verdict=Verdict.OUT_OF_RANGE,
                    reason=(
                        f"Dose diária {daily} {rule.dose_unit} "
                        f"({dose} × {int(frequency_per_day)}/dia) excede o máximo diário de "
                        f"{max_per_day} {rule.dose_unit}."
                    ),
                    expected_low=expected_low,
                    expected_high=expected_high,
                    max_per_dose=absolute_max,
                    rule_id=rule.id,
                )

        # 8. Within band, under both ceilings → SAFE.
        return DoseVerdict(
            verdict=Verdict.SAFE,
            reason=(
                f"Dose {dose} {rule.dose_unit} dentro do intervalo "
                f"{expected_low}–{expected_high} {rule.dose_unit}."
            ),
            expected_low=expected_low,
            expected_high=expected_high,
            max_per_dose=absolute_max,
            rule_id=rule.id,
        )

    # ── helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _select_rule(*, formulary, patient_age_days, weight_kg, route):
        """Pick the matching DoseRule deterministically.

        Filters active rules by age band, weight band, and route. Null bound =
        unbounded. If several match, the most specific (narrowest age band, then
        narrowest weight band, then a concrete route over a blank one) wins; ties
        break on the rule's stable ordering (age_min_days, then id) so the choice
        is deterministic across runs.
        """
        candidates = []
        for rule in formulary.dose_rules.filter(active=True):
            if not DoseChecker._age_matches(rule, patient_age_days):
                continue
            if not DoseChecker._weight_matches(rule, weight_kg):
                continue
            if not DoseChecker._route_matches(rule, route):
                continue
            candidates.append(rule)

        if not candidates:
            return None
        if len(candidates) > 1:
            logger.info(
                "DoseChecker: %d DoseRules matched for formulary=%s — choosing most specific.",
                len(candidates),
                getattr(formulary, "id", None),
            )
        candidates.sort(key=DoseChecker._specificity_key)
        return candidates[0]

    @staticmethod
    def _specificity_key(rule):
        """Sort key: smaller = more specific, picked first.

        Narrower age band first, then narrower weight band, then a concrete route
        before a blank (any-route) rule, then stable tie-break on id string.
        """
        age_span = DoseChecker._span(rule.age_min_days, rule.age_max_days)
        weight_span = DoseChecker._span(rule.weight_min_kg, rule.weight_max_kg)
        route_rank = 0 if rule.route else 1
        return (age_span, weight_span, route_rank, str(rule.id))

    @staticmethod
    def _span(low, high):
        """A finite span for a band; unbounded sides count as 'infinite' (sorts last)."""
        if low is None or high is None:
            return Decimal("Infinity")
        return abs(Decimal(high) - Decimal(low))

    @staticmethod
    def _age_matches(rule, patient_age_days):
        if rule.age_min_days is not None and patient_age_days < rule.age_min_days:
            return False
        if rule.age_max_days is not None and patient_age_days > rule.age_max_days:
            return False
        return True

    @staticmethod
    def _weight_matches(rule, weight_kg):
        # A weight band on the rule constrains by weight. If the rule has a weight
        # band but the patient weight is unknown, the band can't be confirmed →
        # treat as non-matching (a per_kg rule then falls through to WEIGHT_GATE
        # only if it was the rule that *would* match on age; a weight-banded rule
        # simply isn't selectable without a weight).
        if rule.weight_min_kg is None and rule.weight_max_kg is None:
            return True
        if weight_kg is None:
            return False
        w = Decimal(weight_kg)
        if rule.weight_min_kg is not None and w < Decimal(rule.weight_min_kg):
            return False
        if rule.weight_max_kg is not None and w > Decimal(rule.weight_max_kg):
            return False
        return True

    @staticmethod
    def _route_matches(rule, route):
        # Blank rule.route = any route. A concrete rule route must match the
        # prescribed route (when the prescription specifies one).
        if not rule.route:
            return True
        return route == rule.route

    @staticmethod
    def _weight_is_stale(weight_recorded_at, now, weight_staleness_days):
        if weight_recorded_at is None:
            # No timestamp = can't prove freshness → treat as stale (fail-safe).
            return True
        try:
            return (now - weight_recorded_at) > timedelta(days=weight_staleness_days)
        except (TypeError, InvalidOperation):
            return True
