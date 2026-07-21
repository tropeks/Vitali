"""
AI Farmácia — demand forecast service.

Two forecasters live behind one REST shape:

1. **Arithmetic baseline** (the original Phase-3 primitive): a rolling-window
   average of dispensation, transparent and useful from day one::

       avg_daily_consumption   = sum(dispenses_in_window) / window_days
       projected_days_of_supply = current_stock / avg_daily_consumption
       recommended_reorder_qty  = max(0, target_days·avg_daily - current_stock)

2. **Learned seasonal model** (issue #131): once a drug has accrued enough
   dispensation history, an additive Holt-Winters model (weekly seasonality +
   trend, see `learned.py`) is back-tested against the baseline on a hold-out
   slice. When it wins the MAPE comparison it becomes the *recommended*
   forecast; otherwise the service degrades to the baseline. Either way the
   endpoint returns a usable answer.

The baseline fields are preserved verbatim for backward compatibility and for
the side-by-side accuracy comparison the issue asks for; the learned model adds
parallel ``*_model`` fields plus a ``model`` selector and an ``accuracy`` block.
Consumers wanting "the best forecast" should read the ``model`` / ``*_model``
fields; the flat baseline fields stay stable for existing callers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from apps.pharmacy.models import Drug, StockItem, StockMovement

from . import learned
from .timeseries import build_daily_demand

# Lookback used to *train* the learned model (issue #131 assumes 3+ months of
# pilot history). Independent of the baseline's `window_days`, which only sizes
# the rolling average. Missing days are zero-filled by `build_daily_demand`.
TRAIN_LOOKBACK_DAYS = 120

# Days reserved at the tail of the training series for the hold-out MAPE
# back-test that decides whether the learned model is adopted.
HOLDOUT_DAYS = 14


@dataclass(frozen=True)
class DemandForecast:
    drug_id: str
    drug_name: str
    window_days: int
    target_days: int
    total_dispensed_in_window: float
    avg_daily_consumption: float
    current_stock: float
    projected_days_of_supply: float | None
    recommended_reorder_quantity: float
    # ── learned seasonal model (issue #131) ──────────────────────────────────
    # `model` names the recommended forecaster: MODEL_HOLT_WINTERS when the
    # learned model won the hold-out, else MODEL_BASELINE. The `*_model` fields
    # carry that recommended forecaster's numbers (they mirror the baseline when
    # it falls back). `accuracy` is the MAPE comparison, or None when there was
    # too little history to back-test.
    model: str
    seasonality_period_days: int | None
    predicted_avg_daily_consumption: float
    projected_days_of_supply_model: float | None
    recommended_reorder_quantity_model: float
    accuracy: dict | None

    def to_dict(self) -> dict:
        return asdict(self)


def forecast_for_drug(
    drug: Drug, *, window_days: int = 30, target_days: int = 60
) -> DemandForecast:
    """
    Compute the demand forecast for one Drug.

    `window_days`: lookback to measure baseline demand (default 30).
    `target_days`: how many days of supply we want after reordering (default 60).

    Runs the arithmetic baseline and, when enough history exists, the learned
    seasonal model — adopting the latter only when it beats the baseline on a
    hold-out MAPE back-test.
    """
    if window_days <= 0:
        raise ValueError("window_days must be positive.")
    if target_days <= 0:
        raise ValueError("target_days must be positive.")

    now = timezone.now()
    since = now - timedelta(days=window_days)

    # Sum of `dispense` movement quantities for stock items of this drug
    # within the window. Dispense entries store quantity as a *negative*
    # number (it leaves stock), so we negate the sum to get the absolute
    # demand. Adjustments / returns / write-offs are deliberately excluded
    # — they are not consumption signals.
    dispensed = StockMovement.objects.filter(
        stock_item__drug=drug,
        movement_type="dispense",
        created_at__gte=since,
    ).aggregate(total=Sum("quantity"))["total"] or Decimal("0")
    total_dispensed = float(-dispensed)
    if total_dispensed < 0:
        # A net-positive "dispense" total means the ledger is corrupt; clamp to
        # zero rather than emit nonsense forecasts.
        total_dispensed = 0.0
    avg_daily = total_dispensed / window_days

    current_stock = float(
        StockItem.objects.filter(drug=drug).aggregate(total=Sum("quantity"))["total"]
        or Decimal("0")
    )

    if avg_daily > 0:
        projected_days: float | None = current_stock / avg_daily
    else:
        projected_days = None  # demand=0 → infinite runway; surface null

    target_supply = target_days * avg_daily
    recommended_reorder = max(0.0, target_supply - current_stock)

    # ── learned seasonal model ────────────────────────────────────────────────
    # Train on the daily series and forecast the next `target_days`; the model's
    # recommendation mirrors the baseline math but uses the (seasonally-aware)
    # predicted demand over the horizon instead of a flat windowed average.
    history = build_daily_demand(drug, end=now, days=TRAIN_LOOKBACK_DAYS)
    result = learned.forecast_demand(
        history,
        horizon=target_days,
        holdout_days=HOLDOUT_DAYS,
        season_length=learned.DEFAULT_SEASON_LENGTH,
    )
    predicted_total = sum(result.predictions)
    predicted_avg_daily = predicted_total / target_days if target_days else 0.0
    recommended_reorder_model = max(0.0, predicted_total - current_stock)
    if predicted_avg_daily > 0:
        projected_days_model: float | None = current_stock / predicted_avg_daily
    else:
        projected_days_model = None

    return DemandForecast(
        drug_id=str(drug.pk),
        drug_name=getattr(drug, "generic_name", "") or getattr(drug, "name", ""),
        window_days=window_days,
        target_days=target_days,
        total_dispensed_in_window=total_dispensed,
        avg_daily_consumption=avg_daily,
        current_stock=current_stock,
        projected_days_of_supply=projected_days,
        recommended_reorder_quantity=recommended_reorder,
        model=result.model,
        seasonality_period_days=result.season_length,
        predicted_avg_daily_consumption=predicted_avg_daily,
        projected_days_of_supply_model=projected_days_model,
        recommended_reorder_quantity_model=recommended_reorder_model,
        accuracy=result.accuracy.to_dict() if result.accuracy is not None else None,
    )
