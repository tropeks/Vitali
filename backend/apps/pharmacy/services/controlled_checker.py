"""Controlled-substance diversion engine (pure, deterministic) — wedge PR C1.

Given a patient's PRIOR controlled-dispensation history and the dispensation just
made, returns deterministic diversion signals (refill-too-soon, doctor-shopping,
quantity-escalation). ADVISE/compliance only — the orchestrator records these for
review; nothing here ever blocks a dispensation (the existing perm + notes gate
governs the act; a false-positive block would deny a legitimate controlled med).

Design (mirrors stockout_checker / no_show_checker):
- **PURE**: no DB, no clock, no LLM/ML. Deterministic over the records the
  orchestrator resolves (the current dispensation's own time is the anchor).
- **All signals are DERIVED from real dispensation rows** — nothing invented.
  Cross-class patterns are never mixed: doctor-shopping groups by controlled
  CLASS; refill / escalation group by the exact DRUG.
- **INERT when data is absent**: refill needs a configured
  ``min_refill_interval_days`` (None → that signal off); the others need enough
  history.

LOCKED in eng-review:
- refill_too_soon: same drug, a DIFFERENT prescription re-dispensed within the
  drug's ``min_refill_interval_days`` (a partial fill of the SAME script is not a
  refill). The fragile ``qty/(freq×dose)`` days-supply formula is deliberately
  NOT used — ``dose_unit`` is mass-only while dispense quantity is countable.
- multiple_prescribers: ≥ K distinct prescribers for the same controlled CLASS
  within a rolling window.
- quantity_escalation: the last N fills of the same DRUG strictly increasing.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from decimal import Decimal

ENGINE_VERSION = "controlled-c1"

# Signal kinds.
SIGNAL_REFILL_TOO_SOON = "refill_too_soon"
SIGNAL_MULTIPLE_PRESCRIBERS = "multiple_prescribers"
SIGNAL_QUANTITY_ESCALATION = "quantity_escalation"

# Operational defaults — tunable per establishment, NOT ANVISA/Portaria-344 rules.
DEFAULT_PRESCRIBER_THRESHOLD = 3
DEFAULT_WINDOW_DAYS = 90
DEFAULT_ESCALATION_MIN_FILLS = 3


@dataclass(frozen=True)
class DispensationRecord:
    """One controlled dispensation as seen by the engine (resolved by the service)."""

    dispensation_id: str
    drug_id: str
    controlled_class: str
    prescription_id: str
    prescriber_id: str | None
    quantity: Decimal
    dispensed_at: datetime.datetime


@dataclass(frozen=True)
class ControlledSignal:
    kind: str
    detail: dict = field(default_factory=dict)
    engine_version: str = ENGINE_VERSION


def check(
    *,
    current: DispensationRecord,
    history: list[DispensationRecord],
    min_refill_interval_days: int | None,
    prescriber_threshold: int = DEFAULT_PRESCRIBER_THRESHOLD,
    window_days: int = DEFAULT_WINDOW_DAYS,
    escalation_min_fills: int = DEFAULT_ESCALATION_MIN_FILLS,
) -> list[ControlledSignal]:
    """Return the diversion signals raised by ``current`` given prior ``history``."""
    # Defensive prior-only guard (the trigger has already committed).
    prior = [h for h in history if h.dispensed_at < current.dispensed_at]
    signals: list[ControlledSignal] = []

    _refill = _check_refill_too_soon(current, prior, min_refill_interval_days)
    if _refill is not None:
        signals.append(_refill)

    _shopping = _check_multiple_prescribers(current, prior, prescriber_threshold, window_days)
    if _shopping is not None:
        signals.append(_shopping)

    _escalation = _check_quantity_escalation(current, prior, escalation_min_fills)
    if _escalation is not None:
        signals.append(_escalation)

    return signals


def _check_refill_too_soon(
    current: DispensationRecord,
    prior: list[DispensationRecord],
    min_refill_interval_days: int | None,
) -> ControlledSignal | None:
    if min_refill_interval_days is None:
        return None  # inert until the drug's interval is configured
    # Same drug, a DIFFERENT prescription (a split of the same script is not a refill).
    same_drug = [
        h
        for h in prior
        if h.drug_id == current.drug_id and h.prescription_id != current.prescription_id
    ]
    if not same_drug:
        return None
    most_recent = max(same_drug, key=lambda h: h.dispensed_at)
    gap_days = (current.dispensed_at - most_recent.dispensed_at).days
    if gap_days < min_refill_interval_days:
        return ControlledSignal(
            kind=SIGNAL_REFILL_TOO_SOON,
            detail={
                "gap_days": gap_days,
                "min_refill_interval_days": min_refill_interval_days,
                "prior_dispensation_id": most_recent.dispensation_id,
                "prior_dispensed_at": most_recent.dispensed_at.isoformat(),
            },
        )
    return None


def _check_multiple_prescribers(
    current: DispensationRecord,
    prior: list[DispensationRecord],
    threshold: int,
    window_days: int,
) -> ControlledSignal | None:
    window_start = current.dispensed_at - datetime.timedelta(days=window_days)
    prescribers = {
        h.prescriber_id
        for h in prior
        if h.controlled_class == current.controlled_class
        and h.dispensed_at >= window_start
        and h.prescriber_id
    }
    if current.prescriber_id:
        prescribers.add(current.prescriber_id)
    if len(prescribers) >= threshold:
        return ControlledSignal(
            kind=SIGNAL_MULTIPLE_PRESCRIBERS,
            detail={
                "controlled_class": current.controlled_class,
                "distinct_prescribers": len(prescribers),
                "threshold": threshold,
                "window_days": window_days,
            },
        )
    return None


def _check_quantity_escalation(
    current: DispensationRecord,
    prior: list[DispensationRecord],
    min_fills: int,
) -> ControlledSignal | None:
    same_drug = sorted(
        [h for h in prior if h.drug_id == current.drug_id] + [current],
        key=lambda h: h.dispensed_at,
    )
    if len(same_drug) < min_fills:
        return None
    tail = same_drug[-min_fills:]
    strictly_increasing = all(tail[i].quantity < tail[i + 1].quantity for i in range(len(tail) - 1))
    if strictly_increasing:
        return ControlledSignal(
            kind=SIGNAL_QUANTITY_ESCALATION,
            detail={
                "fills": min_fills,
                "quantities": [str(h.quantity) for h in tail],
            },
        )
    return None
