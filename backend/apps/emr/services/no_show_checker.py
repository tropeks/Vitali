"""No-show risk engine (pure, deterministic) — no-show prediction wedge PR N1.

Given a patient's PAST appointment history (counts only) and an upcoming
appointment's features, returns a transparent no-show risk score. This is the
authoritative core of the 6th AI-native wedge — operational/advise only, it never
blocks booking or check-in.

Design (mirrors stockout_checker / dose_checker):
- **PURE**: no DB, no clock, no LLM/ML. Deterministic function of inputs. The
  orchestrator (PR N2) resolves the history counts (strictly from terminal
  appointments BEFORE this appointment's start_time) and feeds them in.
- **Transparent multiplicative-odds model** (NOT additive points — additive caps
  saturate and break the per-component explanation). Locked in eng-review:
    base_rate = (no_shows + α) / (terminal + α + β),   α=2, β=8  → Beta(2,8) prior
    odds      = base_rate / (1 − base_rate) × Π(modifiers)
    score     = odds / (1 + odds)                      ∈ (0, 1) by construction
  The Beta(2,8) prior encodes a 20% establishment baseline with weight 10
  pseudo-observations, so a patient's own data only dominates after ~10 visits.
- **Inert below min-sample**: with fewer than ``min_sample`` terminal
  (completed + no_show) appointments, returns ``None`` — we never brand a
  low-history patient on the prior alone. Absence of a verdict = "no opinion".
- **Decimal-only** numeric, like the dose/stockout engines.

Modifiers are odds multipliers ≥ 1.0 (risk-increasing only, keeps it monotonic
and trivially explainable); each one that fires is recorded in ``breakdown``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

ENGINE_VERSION = "noshow-n1"

# Beta(α, β) smoothing prior → mean α/(α+β) = 0.20 establishment baseline.
PRIOR_ALPHA = Decimal("2")
PRIOR_BETA = Decimal("8")

# Minimum terminal (completed + no_show) history before a patient is scored.
DEFAULT_MIN_SAMPLE = 5

# Locked odds multipliers (each ≥ 1.0).
MULT_NO_CONFIRM = Decimal("1.6")  # reminder sent but not confirmed
MULT_LONG_LEAD = Decimal("1.4")  # booked >= 30 days ahead
MULT_CONSECUTIVE = Decimal("2.0")  # >= 2 consecutive prior no-shows
MULT_SELF_SERVE = Decimal("1.2")  # self-booked via web / whatsapp
MULT_RETURN = Decimal("1.15")  # return visit

LONG_LEAD_DAYS = 30
CONSECUTIVE_THRESHOLD = 2
SELF_SERVE_SOURCES = frozenset({"web", "whatsapp"})

# Bands (score cutoffs).
BAND_LOW = "low"
BAND_MEDIUM = "medium"
BAND_HIGH = "high"
MEDIUM_CUTOFF = Decimal("0.25")
HIGH_CUTOFF = Decimal("0.50")

# Suggested actions (surface only — v1 never auto-acts).
ACTION_NONE = "none"
ACTION_CONFIRM_ACTIVE = "confirm_active"

_QUANT = Decimal("0.0001")


@dataclass(frozen=True)
class NoShowVerdict:
    score: Decimal
    band: str
    breakdown: list[dict] = field(default_factory=list)
    suggested_action: str = ACTION_NONE
    engine_version: str = ENGINE_VERSION


def _band(score: Decimal) -> str:
    if score >= HIGH_CUTOFF:
        return BAND_HIGH
    if score >= MEDIUM_CUTOFF:
        return BAND_MEDIUM
    return BAND_LOW


def score_no_show(
    *,
    no_shows: int,
    terminal: int,
    consecutive_no_shows: int = 0,
    whatsapp_reminder_sent: bool = False,
    whatsapp_confirmed: bool = False,
    lead_time_days: int = 0,
    source: str = "",
    appointment_type: str = "",
    min_sample: int = DEFAULT_MIN_SAMPLE,
) -> NoShowVerdict | None:
    """Score one upcoming appointment's no-show risk.

    ``terminal`` = the patient's count of past completed + no_show appointments
    (cancelled excluded). ``no_shows`` ⊆ terminal. Returns ``None`` (inert) when
    ``terminal < min_sample``. ``lead_time_days`` is clamped to ≥ 0.
    """
    if terminal < min_sample:
        return None

    # Guard: no_shows can never exceed terminal (caller bug / dirty data).
    no_shows = max(0, min(no_shows, terminal))
    lead_time_days = max(0, lead_time_days)

    base_rate = (Decimal(no_shows) + PRIOR_ALPHA) / (Decimal(terminal) + PRIOR_ALPHA + PRIOR_BETA)
    odds = base_rate / (Decimal(1) - base_rate)

    breakdown: list[dict] = [
        {
            "feature": "base_rate",
            "value": str(base_rate.quantize(_QUANT, rounding=ROUND_HALF_UP)),
            "no_shows": no_shows,
            "terminal": terminal,
            "reason": (
                f"Histórico: {no_shows} falta(s) em {terminal} agendamentos "
                f"(taxa suavizada {base_rate.quantize(_QUANT, rounding=ROUND_HALF_UP)})."
            ),
        }
    ]

    def _apply(active: bool, multiplier: Decimal, feature: str, reason: str) -> None:
        nonlocal odds
        if active:
            odds *= multiplier
            breakdown.append({"feature": feature, "multiplier": str(multiplier), "reason": reason})

    # The no-confirm modifier fires ONLY when a reminder was actually sent and is
    # still unconfirmed — otherwise an early job run would unfairly flag everyone.
    _apply(
        whatsapp_reminder_sent and not whatsapp_confirmed,
        MULT_NO_CONFIRM,
        "no_confirmation",
        "Lembrete enviado mas ainda não confirmado.",
    )
    _apply(
        lead_time_days >= LONG_LEAD_DAYS,
        MULT_LONG_LEAD,
        "long_lead_time",
        f"Agendado com {lead_time_days} dias de antecedência (≥ {LONG_LEAD_DAYS}).",
    )
    _apply(
        consecutive_no_shows >= CONSECUTIVE_THRESHOLD,
        MULT_CONSECUTIVE,
        "consecutive_no_shows",
        f"{consecutive_no_shows} faltas consecutivas recentes.",
    )
    _apply(
        source in SELF_SERVE_SOURCES,
        MULT_SELF_SERVE,
        "self_serve_channel",
        f"Agendamento self-service ({source}).",
    )
    _apply(
        appointment_type == "return",
        MULT_RETURN,
        "return_visit",
        "Consulta de retorno.",
    )

    score = (odds / (Decimal(1) + odds)).quantize(_QUANT, rounding=ROUND_HALF_UP)
    band = _band(score)
    action = ACTION_CONFIRM_ACTIVE if band in (BAND_MEDIUM, BAND_HIGH) else ACTION_NONE

    return NoShowVerdict(
        score=score,
        band=band,
        breakdown=breakdown,
        suggested_action=action,
    )
