"""Deterministic stockout-prediction engine — stockout wedge PR S1.

SUPPLY-OPERATIONS logic. This module is PURE and DETERMINISTIC:

  * NO database queries / writes. The (future S2/S3) orchestrator pre-computes
    every DB-derived input — the trailing dispense history, the current balance —
    and passes them in. ``compute_daily_velocity`` takes a plain list of
    ``(timestamp, quantity)`` tuples; ``StockoutChecker.check`` takes the already
    -derived velocity + the establishment's config. This mirrors
    ``apps.pharmacy.services.dose_checker.DoseChecker`` and
    ``apps.billing.services.glosa_checker.GlosaChecker``.
  * NO LLM, NO network, NO clock. ``now`` is injected by the caller — the engine
    never reads the wall clock, so every check is reproducible.
  * Decimal-only for any numeric compare or division — NEVER float. A float
    mid-calculation could silently misrepresent a days-to-stockout figure.
  * Every reason string is a deterministic, human-readable pt-BR sentence that
    EMBEDS the numbers (balance, velocity/day, days-to-stockout, predicted date),
    so changing an input changes the message. It is NOT an LLM explanation.

POSTURE — ADVISE, NEVER BLOCK.
  Stockout prediction NEVER blocks anything. There is no gate, no 409, no
  rejected dispense. Blocking a clinical dispense over a supply forecast is
  dangerous (the locked design rejected a DispenseView gate outright). The only
  RISK verdict severity is ``advise``; there is deliberately no ``block`` path.

INERT BY DEFAULT.
  The config fields on Drug/Material (lead_time_days, safety_stock,
  reorder_point) are all nullable. With no config and/or no consumption history
  the engine returns ``not_applicable`` — it invents nothing. Specifically the
  engine is INERT (no risk, no division) when daily_velocity is None (zero or
  insufficient dispense history) OR lead_time_days is None. Division-by-zero is
  therefore impossible: velocity == 0 collapses to None upstream → inert.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

# Velocity is a units/day rate; 4 decimal places is plenty for a daily mean and
# matches the precision posture of the dose engine. days_to_stockout is a count
# of days — quantized to 1 place so the reason reads cleanly ("3.2 dias").
_VELOCITY_QUANT = Decimal("0.0001")
_DAYS_QUANT = Decimal("0.1")

# Locked velocity thresholds (see STOCKOUT-WEDGE.md "✅ LOCKED").
DEFAULT_WINDOW_DAYS = 30
DEFAULT_MIN_EVENTS = 3


def _qv(value: Decimal) -> Decimal:
    """Quantize a velocity (units/day) to the canonical scale (half-up)."""
    return value.quantize(_VELOCITY_QUANT, rounding=ROUND_HALF_UP)


def _qd(value: Decimal) -> Decimal:
    """Quantize a days figure to 1 decimal place (half-up) for display."""
    return value.quantize(_DAYS_QUANT, rounding=ROUND_HALF_UP)


def compute_daily_velocity(
    dispense_events: Sequence[tuple[datetime, Decimal]],
    *,
    now: datetime,
    window_days: int = DEFAULT_WINDOW_DAYS,
    min_events: int = DEFAULT_MIN_EVENTS,
) -> Decimal | None:
    """Simple moving-average daily consumption over a trailing window.

    PURE — no DB, no clock (``now`` injected). ``dispense_events`` is a list of
    ``(timestamp, quantity)`` tuples; the caller MUST pass only
    ``movement_type="dispense"`` events (quantities are the dispensed amounts,
    treated as positive magnitudes). Quantities are summed as Decimals.

    Rules (LOCKED):
      * Consider only events whose timestamp falls within the trailing
        ``window_days`` ending at ``now`` (``now - window_days <= ts <= now``).
      * If the in-window event count < ``min_events`` (default 3) → return None
        (INERT — sporadic consumption must not trigger a false "iminente").
      * If the in-window total dispensed == 0 → return None (INERT; also makes a
        zero-velocity division impossible downstream).
      * Else velocity = total_dispensed_in_window / window_days (Decimal,
        quantized).

    Returns the units/day rate as a Decimal, or None when inert.
    """
    if window_days <= 0:
        return None

    window_start = now - timedelta(days=window_days)
    in_window = [abs(Decimal(qty)) for (ts, qty) in dispense_events if window_start <= ts <= now]

    if len(in_window) < min_events:
        return None

    total = sum(in_window, Decimal("0"))
    if total == 0:
        return None

    return _qv(total / Decimal(window_days))


@dataclass(frozen=True)
class StockoutVerdict:
    """Immutable result of a single stockout check.

    ``kind`` is one of:
      * ``"not_applicable"`` — INERT: no velocity history and/or no lead time
        configured. No risk, no prediction.
      * ``"sufficient"`` — there IS enough runway: the item will not stock out
        before it can be replenished, and no configured threshold is breached.
      * ``"stockout_risk"`` — the item is projected to run out before (or near)
        the replenishment lead time, or a configured reorder/safety threshold is
        breached. ADVISE only.

    ``severity`` is ``"advise"`` for ``stockout_risk`` and ``None`` otherwise.
    There is deliberately NO "block" severity — stockout NEVER blocks.

    ``predicted_date`` / ``days_to_stockout`` are populated whenever they can be
    computed (i.e. not in the ``not_applicable`` path); ``reason`` is a
    deterministic pt-BR sentence embedding the numbers.
    """

    kind: str
    severity: str | None = None
    predicted_date: date | None = None
    days_to_stockout: Decimal | None = None
    reason: str = ""


KIND_NOT_APPLICABLE = "not_applicable"
KIND_SUFFICIENT = "sufficient"
KIND_STOCKOUT_RISK = "stockout_risk"
SEVERITY_ADVISE = "advise"


class StockoutChecker:
    """Pure, deterministic stockout predictor. No state, no I/O."""

    @staticmethod
    def check(
        *,
        current_balance: Decimal,
        daily_velocity: Decimal | None,
        lead_time_days: int | None,
        safety_stock: Decimal | None,
        reorder_point: Decimal | None,
        now: datetime,
    ) -> StockoutVerdict:
        """Predict whether ``current_balance`` runs out before replenishment.

        All numeric inputs that participate in arithmetic are Decimal (or None /
        int for lead_time_days). PURE — ``now`` is injected; the engine never
        reads the clock.

        INERT (``not_applicable``) when ``daily_velocity`` is None (zero or
        insufficient dispense history) OR ``lead_time_days`` is None. This is the
        ONLY path that divides nothing — and because velocity == 0 collapses to
        None upstream, division-by-zero can never happen.

        Otherwise:
          * days_to_stockout = current_balance / daily_velocity
          * predicted_stockout_date = now.date() + days_to_stockout (whole days)
          * RISK (advise) when ANY of:
              - days_to_stockout <= lead_time_days (can't replenish in time), OR
              - reorder_point is set and current_balance <= reorder_point, OR
              - safety_stock is set and the projected balance at lead_time
                (current_balance - velocity * lead_time_days) would fall below
                safety_stock.
          * else ``sufficient``.
        """
        # ── INERT GUARD ──────────────────────────────────────────────────────
        # No usable velocity (zero / insufficient history) OR no lead time → the
        # engine invents nothing and divides nothing.
        if daily_velocity is None or lead_time_days is None:
            return StockoutVerdict(
                kind=KIND_NOT_APPLICABLE,
                reason=(
                    "Inerte: sem velocidade de consumo "
                    f"({'sem histórico suficiente' if daily_velocity is None else 'ok'}) "
                    "ou lead time não configurado — sem predição de ruptura."
                ),
            )

        balance = Decimal(current_balance)
        velocity = Decimal(daily_velocity)
        lead = Decimal(lead_time_days)

        # daily_velocity is guaranteed non-zero here (zero collapses to None
        # upstream), so this division is always safe.
        days_to_stockout = _qd(balance / velocity)
        predicted_date = now.date() + timedelta(days=int(days_to_stockout))

        # Projected balance once the lead-time window has elapsed (i.e. the
        # earliest a replenishment could realistically land).
        projected_at_lead = balance - (velocity * lead)

        # Normalize the optional thresholds to Decimal once (None stays None).
        reorder = Decimal(reorder_point) if reorder_point is not None else None
        safety = Decimal(safety_stock) if safety_stock is not None else None

        reasons: list[str] = []

        runway_breach = days_to_stockout <= lead
        if runway_breach:
            reasons.append(
                f"dias até ruptura ({days_to_stockout}) ≤ lead time ({lead_time_days} dias)"
            )

        reorder_breach = reorder is not None and balance <= reorder
        if reorder_breach:
            reasons.append(f"saldo ({balance}) ≤ ponto de reposição ({reorder})")

        safety_breach = safety is not None and projected_at_lead < safety
        if safety_breach:
            reasons.append(
                f"saldo projetado em {lead_time_days} dias ({_qv(projected_at_lead)}) "
                f"< estoque de segurança ({safety})"
            )

        if runway_breach or reorder_breach or safety_breach:
            detail = "; ".join(reasons)
            reason = (
                f"Risco de ruptura (ADVISE): saldo {balance}, "
                f"consumo {velocity}/dia, ruptura em ~{days_to_stockout} dias "
                f"(prevista {predicted_date.isoformat()}). Motivo: {detail}."
            )
            return StockoutVerdict(
                kind=KIND_STOCKOUT_RISK,
                severity=SEVERITY_ADVISE,
                predicted_date=predicted_date,
                days_to_stockout=days_to_stockout,
                reason=reason,
            )

        return StockoutVerdict(
            kind=KIND_SUFFICIENT,
            predicted_date=predicted_date,
            days_to_stockout=days_to_stockout,
            reason=(
                f"Estoque suficiente: saldo {balance}, consumo {velocity}/dia, "
                f"ruptura em ~{days_to_stockout} dias (prevista {predicted_date.isoformat()}), "
                f"além do lead time ({lead_time_days} dias)."
            ),
        )


@dataclass(frozen=True)
class ExpiryWaste:
    """One lot projected to expire before the running consumption can reach it.

    ``stock_item_id`` is the lot that will be left partially unconsumed at its
    ``expiry_date``; ``waste_qty`` is the Decimal remainder that will be wasted;
    ``reason`` is a deterministic pt-BR sentence embedding the numbers.
    """

    stock_item_id: object
    waste_qty: Decimal
    expiry_date: date
    reason: str = ""


def predict_expiry_waste(
    lots: Sequence[tuple[object, Decimal, date | None]],
    daily_velocity: Decimal | None,
    now: datetime,
) -> list[ExpiryWaste]:
    """Pure FEFO expiry-waste predictor — no DB, no clock (``now`` injected).

    ``lots`` is a list of ``(stock_item_id, on_hand_qty, expiry_date)`` tuples for
    ONE product's on-hand StockItems. The orchestrator supplies them; this
    function only does the arithmetic.

    Algorithm (LOCKED — FEFO):
      * INERT (return ``[]``) when ``daily_velocity`` is None (no/insufficient
        dispense history — division would be meaningless) — mirrors the stockout
        engine's inert guard. Division-by-zero is impossible since velocity == 0
        collapses to None upstream.
      * Stack the lots by ``expiry_date`` ASC (FEFO — earliest-expiring consumed
        first). Lots with no ``expiry_date`` cannot expire-waste → skipped (and
        do NOT consume the runway, since an undated lot is consumed last in
        practice and never the binding waste constraint).
      * Walk the stack: each lot becomes available to consume only AFTER every
        earlier-expiring lot ahead of it is consumed. The cumulative quantity
        ahead of (and including) a lot takes ``cumulative / velocity`` days to
        burn down. If that day count lands AFTER the lot's ``expiry_date`` (i.e.
        ``now + days_to_finish_this_lot > expiry_date``), the portion that cannot
        be consumed in the remaining days is predicted waste.
      * waste = on_hand - max(0, units_consumable_before_expiry - units_ahead),
        clamped to [0, on_hand]. A lot fully consumed before its expiry → 0
        (omitted from the result).

    Returns a list of ``ExpiryWaste`` (only lots with waste_qty > 0), in FEFO
    order.
    """
    if daily_velocity is None:
        return []

    velocity = Decimal(daily_velocity)
    if velocity <= 0:
        return []

    # FEFO: earliest expiry first. Lots without an expiry date can never be a
    # waste prediction and don't bind the runway → drop them from the stack.
    dated = [(sid, abs(Decimal(qty)), exp) for (sid, qty, exp) in lots if exp is not None]
    dated.sort(key=lambda t: t[2])

    out: list[ExpiryWaste] = []
    units_ahead = Decimal("0")  # cumulative on-hand of all earlier-expiring lots
    today = now.date()

    for stock_item_id, on_hand, expiry in dated:
        if on_hand <= 0:
            units_ahead += on_hand
            continue

        days_left = Decimal((expiry - today).days)
        # Units we can physically consume by this lot's expiry across the whole
        # FEFO stack up to and including it.
        consumable_by_expiry = days_left * velocity if days_left > 0 else Decimal("0")
        # Of those, the lots ahead are burned first; what remains is available to
        # this lot. Clamp at 0 (a lot whose predecessors already outlast the date).
        available_to_this = consumable_by_expiry - units_ahead
        if available_to_this < 0:
            available_to_this = Decimal("0")

        consumed = available_to_this if available_to_this < on_hand else on_hand
        waste = on_hand - consumed

        if waste > 0:
            out.append(
                ExpiryWaste(
                    stock_item_id=stock_item_id,
                    waste_qty=waste,
                    expiry_date=expiry,
                    reason=(
                        f"Desperdício por validade (ADVISE): lote com {on_hand} un. vence "
                        f"em {expiry.isoformat()} ({int(days_left)} dias); ao consumo de "
                        f"{velocity}/dia (FEFO) só ~{_qv(consumed)} un. serão usadas — "
                        f"sobra prevista {_qv(waste)} un."
                    ),
                )
            )

        units_ahead += on_hand

    return out
