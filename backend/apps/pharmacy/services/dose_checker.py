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

# Units grouped by physical dimension. A mismatch WITHIN one family is a
# same-dimension off-by-1000 confusion (mg↔mcg↔g, mL↔L) and MUST hard-block.
# A cross-family mismatch (e.g. mL vs mg) is incomparable, cannot be a 1000x
# typo, and degrades to an advisory rather than flooding the gate.
_UNIT_FAMILIES = (
    frozenset({"mg", "mcg", "g"}),  # mass
    frozenset({"mL", "L"}),  # volume (not in DOSE_UNIT_CHOICES today; defensive)
)


def _q(value: Decimal) -> Decimal:
    """Quantize a Decimal to the canonical 4-place dose scale (half-up)."""
    return value.quantize(_QUANT, rounding=ROUND_HALF_UP)


class Verdict(str, Enum):
    """Engine verdict. Maps to the locked fail decision table (plan §2.6)."""

    SAFE = "SAFE"
    OUT_OF_RANGE = "OUT_OF_RANGE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    DATA_MISSING = "DATA_MISSING"
    UNIT_MISMATCH = "UNIT_MISMATCH"
    NO_RULE_MATCH = "NO_RULE_MATCH"
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
    # Dose-engine v2 (AXIS 3): the matched rule's enforcement mode. Drives whether
    # an OUT_OF_RANGE verdict blocks (default) or is a non-blocking caution. Only
    # meaningful for OUT_OF_RANGE/SAFE returns; "block" elsewhere (the orchestrator
    # routes WEIGHT_GATE/UNIT_MISMATCH as blocking regardless).
    enforcement: str = "block"


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
        dose_role: str | None = None,
    ) -> DoseVerdict:
        """Evaluate a single prescribed dose against the formulary band.

        All numeric inputs that participate in arithmetic MUST be Decimal (or
        None). The whole body is wrapped so any unexpected exception degrades to
        ENGINE_ERROR (advisory) rather than crashing the gate — the caller also
        catches, defence in depth.

        ``dose_role`` (AXIS 2) is the prescriber-declared regimen role; None or
        blank normalizes to "maintenance" — the safe clinical default.
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
                dose_role=dose_role,
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
        dose_role: str | None = None,
    ) -> DoseVerdict:
        # AXIS 2: normalize the prescribed role. None/blank → "maintenance" (the
        # safe clinical default), so an unmarked order is screened against the
        # lower maintenance band rather than ever matching a higher loading rule.
        prescribed_role = dose_role or "maintenance"

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
        #    Materialize the active rules ONCE: _select_rule iterates this list and
        #    the unmatched-path logic below reuses it — a single query total.
        active_rules = list(formulary.dose_rules.filter(active=True))
        candidates = DoseChecker._matching_candidates(
            active_rules=active_rules,
            patient_age_days=patient_age_days,
            weight_kg=weight_kg,
            route=route,
            frequency_per_day=frequency_per_day,
            prescribed_role=prescribed_role,
        )
        if len(candidates) > 1:
            logger.info(
                "DoseChecker: %d DoseRules matched for formulary=%s — most specific band, "
                "strictest absolute ceiling.",
                len(candidates),
                getattr(formulary, "id", None),
            )
        rule = DoseChecker._most_specific(candidates)
        if rule is None:
            logger.info(
                "DoseChecker: no matching DoseRule for formulary=%s age_days=%s weight=%s "
                "route=%s — NOT_APPLICABLE.",
                getattr(formulary, "id", None),
                patient_age_days,
                weight_kg,
                route,
            )
            # Distinguish a GAP (rules exist, none cover this patient) from a
            # not-yet-authored formulary (no active rules at all). A gap is a
            # checkable drug we couldn't check → advisory, NEVER a silent pass.
            if not active_rules:
                return DoseVerdict(
                    verdict=Verdict.NOT_APPLICABLE,
                    reason="Nenhuma regra de dose aplicável à faixa etária/peso deste paciente.",
                )
            # FAIL-SAFE: if the weight is unknown and there is an active rule that
            # matches age + route but was EXCLUDED only because it needs the weight
            # (per_kg basis, or a weight band), we can't even pick the right band —
            # asking for the weight is the fail-safe, NOT a silent advisory gap.
            # NOTE: deliberately do NOT filter by frequency here. A missing weight
            # must raise WEIGHT_GATE even when the frequency is also unknown — for a
            # drug whose only rules are frequency-banded (e.g. an aminoglycoside),
            # otherwise a per-kg order with no weight AND no frequency would slip
            # past the hard weight gate as a mere NO_RULE_MATCH advisory. The weight
            # gate is the higher-priority block; the missing frequency surfaces on
            # re-evaluation once the weight is recorded.
            if weight_kg is None and any(
                DoseChecker._age_matches(r, patient_age_days)
                and DoseChecker._route_matches(r, route)
                and DoseChecker._role_matches(r, prescribed_role)
                and (
                    r.basis == "per_kg"
                    or r.weight_min_kg is not None
                    or r.weight_max_kg is not None
                )
                for r in active_rules
            ):
                dose_label = DoseChecker._dose_label(dose_amount, dose_unit)
                return DoseVerdict(
                    verdict=Verdict.WEIGHT_GATE,
                    reason=(
                        f"A dose {dose_label} depende do peso do paciente "
                        "(regra por peso/por kg), que não está registrado. Registre o peso "
                        "para liberar a verificação."
                    ),
                    rule_id=None,
                )
            dose_label = DoseChecker._dose_label(dose_amount, dose_unit)
            return DoseVerdict(
                verdict=Verdict.NO_RULE_MATCH,
                reason=(
                    f"A dose {dose_label} não é coberta por nenhuma regra deste medicamento "
                    "para a faixa etária/peso/via deste paciente; verificação de dose "
                    "indisponível."
                ),
            )

        # 3. Unit coherence — NEVER coerce mg↔mL↔mcg. Mismatch or missing dose →
        #    DATA_MISSING (advisory), never a silent wrong comparison.
        if dose_amount is None:
            return DoseVerdict(
                verdict=Verdict.DATA_MISSING,
                reason="Dose não informada de forma estruturada; verificação de dose indisponível.",
                rule_id=rule.id,
            )
        if not dose_unit:
            return DoseVerdict(
                verdict=Verdict.DATA_MISSING,
                reason=(
                    f"Dose {dose_amount} informada sem unidade; não é possível comparar com a "
                    f"regra ({rule.dose_unit}). Verificação indisponível."
                ),
                rule_id=rule.id,
            )
        elif dose_unit != rule.dose_unit:
            # A same-dimension mismatch is the dangerous off-by-1000 confusion
            # (mg↔mcg↔g, mL↔L) → BLOCK. A cross-dimension mismatch (e.g. mL vs
            # mg) is incomparable, cannot be a 1000x typo, and can't be safely
            # converted → advisory, NOT a hard block that floods legitimate orders.
            if DoseChecker._same_dimension(dose_unit, rule.dose_unit):
                return DoseVerdict(
                    verdict=Verdict.UNIT_MISMATCH,
                    reason=(
                        f"Dose {dose_amount} {dose_unit} tem unidade diferente "
                        f"da regra ({rule.dose_unit}); não é seguro converter automaticamente. "
                        "Confirme a unidade da dose."
                    ),
                    rule_id=rule.id,
                )
            return DoseVerdict(
                verdict=Verdict.DATA_MISSING,
                reason=(
                    f"Dose {dose_amount} {dose_unit} não é comparável à unidade da regra "
                    f"({rule.dose_unit}); não é seguro converter automaticamente. "
                    "Verificação de dose indisponível."
                ),
                rule_id=rule.id,
            )

        dose = Decimal(dose_amount)
        # The universal hard ceiling is the STRICTEST (lowest) absolute_max_dose
        # among ALL rules that match this patient — never just the most-specific
        # rule's. This decouples "which therapeutic band applies" (most specific)
        # from "what single-dose ceiling can never be exceeded" (strictest), so a
        # narrower-but-looser overlapping rule can't raise the hard cap.
        absolute_max = min(Decimal(c.absolute_max_dose) for c in candidates)

        # 4. Compute the expected band per basis.
        if rule.basis == "per_kg":
            # Per-kg REQUIRES a fresh weight.
            if weight_kg is None:
                return DoseVerdict(
                    verdict=Verdict.WEIGHT_GATE,
                    reason=(
                        f"Dose de {dose_amount} {dose_unit} é por kg e exige o peso do "
                        "paciente, que não está registrado. Registre o peso para liberar a "
                        "verificação."
                    ),
                    rule_id=rule.id,
                )
            if DoseChecker._weight_is_stale(weight_recorded_at, now, weight_staleness_days):
                return DoseVerdict(
                    verdict=Verdict.WEIGHT_GATE,
                    reason=(
                        f"Dose de {dose_amount} {dose_unit} é por kg, mas o peso do paciente "
                        f"está desatualizado (> {weight_staleness_days} dias). Atualize o peso "
                        "para reavaliar."
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

        # 5. ALWAYS enforce the universal absolute ceiling FIRST, and ALWAYS as a
        #    hard BLOCK regardless of rule.enforcement. This is the weight-typo /
        #    per-kg-math floor: a bad weight (70 kg typed 700 kg) can push the
        #    per-kg band itself above a lethal absolute dose. A soft ("advise")
        #    rule — e.g. an opioid with no therapeutic ceiling — may legitimately
        #    titrate ABOVE the expected range, but it must NEVER be allowed to
        #    breach the absolute catastrophe ceiling on a caution only; that would
        #    let a lethal typo pass. So this verdict is enforcement="block", fixed.
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
                enforcement="block",
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
                enforcement=rule.enforcement,
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
                    enforcement=rule.enforcement,
                )

        # 7b. Daily cap exists but frequency is missing → we CANNOT verify the
        #     daily dimension, so we must not overclaim a clean SAFE. Per-dose and
        #     the absolute ceiling were already enforced above (a single-dose
        #     overdose is still caught); this flags only the unverifiable daily cap.
        if rule.max_per_day is not None and not frequency_per_day:
            return DoseVerdict(
                verdict=Verdict.DATA_MISSING,
                reason=(
                    f"Dose {dose} {rule.dose_unit} por administração dentro do intervalo, mas a "
                    f"frequência diária não foi informada; não foi possível verificar o teto "
                    f"diário de {rule.max_per_day} {rule.dose_unit}."
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
            enforcement=rule.enforcement,
        )

    # ── helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _dose_label(dose_amount, dose_unit):
        """Human label for a prescribed dose, used in WEIGHT_GATE / NO_RULE_MATCH
        reasons. It MUST reflect the amount whenever one is present — even without a
        unit — so that editing the dose changes the reason string. Collapsing a
        unit-less dose to a static label would let an acknowledged blocking alert be
        bypassed by editing only the amount (the override-preservation predicate keys
        on the message), so the unit-less case still embeds the number.
        """
        if dose_amount is None:
            return "prescrita"
        return f"{dose_amount} {dose_unit}" if dose_unit else f"{dose_amount} (sem unidade)"

    @staticmethod
    def _same_dimension(unit_a, unit_b):
        """True if both units belong to the same known physical-dimension family."""
        for fam in _UNIT_FAMILIES:
            if unit_a in fam and unit_b in fam:
                return True
        return False

    @staticmethod
    def _select_rule(
        *,
        active_rules,
        formulary,
        patient_age_days,
        weight_kg,
        route,
        frequency_per_day,
        prescribed_role,
    ):
        """Pick the matching DoseRule deterministically.

        Filters the already-materialized ``active_rules`` by age band, weight band,
        route, frequency band (AXIS 1), and dose role (AXIS 2) — no re-query. Null
        bound = unbounded. If several match, the most specific (narrowest age band,
        then weight band, then frequency band, then a concrete route over a blank
        one) wins; ties break on the rule's stable ordering (stricter ceiling, then
        id) so the choice is deterministic across runs.

        AXIS 1 fail-safe: a rule with ANY freq bound set does NOT match when the
        prescribed frequency is unknown (we cannot confirm the regimen) — it falls
        through to NO_RULE_MATCH (or to a sibling rule with no freq bound).

        AXIS 2 exact-match: the rule's dose_role must equal ``prescribed_role``
        (blank already normalized to "maintenance" by the caller), so a loading
        rule is selected only for an explicitly-loading item.
        """
        return DoseChecker._most_specific(
            DoseChecker._matching_candidates(
                active_rules=active_rules,
                patient_age_days=patient_age_days,
                weight_kg=weight_kg,
                route=route,
                frequency_per_day=frequency_per_day,
                prescribed_role=prescribed_role,
            )
        )

    @staticmethod
    def _matching_candidates(
        *,
        active_rules,
        patient_age_days,
        weight_kg,
        route,
        frequency_per_day,
        prescribed_role,
    ):
        """All active rules that match this patient on every axis (age, weight,
        route, frequency band [AXIS 1], dose role [AXIS 2]). The caller picks the
        most-specific band via ``_most_specific`` and enforces the STRICTEST
        absolute ceiling across the whole list."""
        candidates = []
        for rule in active_rules:
            if not DoseChecker._age_matches(rule, patient_age_days):
                continue
            if not DoseChecker._weight_matches(rule, weight_kg):
                continue
            if not DoseChecker._route_matches(rule, route):
                continue
            if not DoseChecker._freq_matches(rule, frequency_per_day):
                continue
            if not DoseChecker._role_matches(rule, prescribed_role):
                continue
            candidates.append(rule)
        return candidates

    @staticmethod
    def _most_specific(candidates):
        """The most-specific rule (narrowest bands; stricter ceiling on a tie), or
        None when nothing matched."""
        if not candidates:
            return None
        return min(candidates, key=DoseChecker._specificity_key)

    @staticmethod
    def _specificity_key(rule):
        """Sort key: smaller = more specific, picked first.

        Narrower age band first, then narrower weight band, then narrower frequency
        band (AXIS 1), then a concrete route before a blank (any-route) rule, then —
        on a genuine tie — the STRICTER (lowest absolute_max_dose) rule, and only
        finally a stable id tie-break. Never let an arbitrary UUID pick a looser
        (higher-ceiling) rule. dose_role is NOT part of the key: it is an exact-match
        filter (AXIS 2), so all surviving candidates already share the same role.
        """
        age_span = DoseChecker._span(rule.age_min_days, rule.age_max_days)
        weight_span = DoseChecker._span(rule.weight_min_kg, rule.weight_max_kg)
        freq_span = DoseChecker._span(rule.freq_min_per_day, rule.freq_max_per_day)
        route_rank = 0 if rule.route else 1
        return (
            age_span,
            weight_span,
            freq_span,
            route_rank,
            Decimal(rule.absolute_max_dose),
            str(rule.id),
        )

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
    def _freq_matches(rule, frequency_per_day):
        # AXIS 1. A rule with NO freq bounds matches any frequency (today's
        # behavior — backward-compatible). A rule with ANY freq bound set is
        # frequency-scoped: it matches only when the prescribed frequency falls in
        # [freq_min, freq_max] (null bound = open on that side). FAIL-SAFE: if the
        # rule is freq-scoped but the prescription's frequency is unknown, we cannot
        # confirm the regimen → the rule does NOT match (falls through to
        # NO_RULE_MATCH, or to a sibling rule with no freq bound).
        if rule.freq_min_per_day is None and rule.freq_max_per_day is None:
            return True
        if frequency_per_day is None:
            return False
        if rule.freq_min_per_day is not None and frequency_per_day < rule.freq_min_per_day:
            return False
        if rule.freq_max_per_day is not None and frequency_per_day > rule.freq_max_per_day:
            return False
        return True

    @staticmethod
    def _role_matches(rule, prescribed_role):
        # AXIS 2. Exact match against the (already-normalized) prescribed role.
        # A loading rule is selected ONLY for an explicitly-loading item; an
        # unmarked (maintenance) order never matches a loading rule.
        return rule.dose_role == prescribed_role

    @staticmethod
    def _weight_is_stale(weight_recorded_at, now, weight_staleness_days):
        if weight_recorded_at is None:
            # No timestamp = can't prove freshness → treat as stale (fail-safe).
            return True
        try:
            return (now - weight_recorded_at) > timedelta(days=weight_staleness_days)
        except (TypeError, InvalidOperation):
            return True
