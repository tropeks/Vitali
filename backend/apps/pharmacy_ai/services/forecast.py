"""
Phase 3 AI Farmácia — demand forecast primitive.

This service computes a **rolling-window** stock-demand forecast per Drug
from the existing `apps.pharmacy.StockMovement` ledger. There is NO ML model
here yet — clinics build up dispensation history first, then a Phase 3+
iteration can train a seasonality-aware model on top. The arithmetic here
is the same baseline most pharmacy operators reach for first:

```
avg_daily_consumption = sum(dispenses_in_window) / window_days
projected_days_of_supply = current_stock / avg_daily_consumption
recommended_reorder_qty = max(0, target_days * avg_daily - current_stock)
```

The primitive is useful on day one (transparent baseline) and the same REST
shape can be served by a smarter implementation later without breaking
callers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from apps.pharmacy.models import Drug, StockItem, StockMovement


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

    def to_dict(self) -> dict:
        return asdict(self)


def forecast_for_drug(
    drug: Drug, *, window_days: int = 30, target_days: int = 60
) -> DemandForecast:
    """
    Compute a baseline rolling-window forecast for one Drug.

    `window_days`: lookback to measure demand (default 30).
    `target_days`: how many days of supply we want after reordering (default 60).
    """
    if window_days <= 0:
        raise ValueError("window_days must be positive.")
    if target_days <= 0:
        raise ValueError("target_days must be positive.")

    since = timezone.now() - timedelta(days=window_days)

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
        # A clinic with positive net dispense rows would imply data
        # corruption; clamp to zero rather than emit nonsense forecasts.
        total_dispensed = 0.0
    avg_daily = total_dispensed / window_days

    current_stock = float(
        StockItem.objects.filter(drug=drug).aggregate(total=Sum("quantity"))["total"]
        or Decimal("0")
    )

    if avg_daily > 0:
        projected_days: float | None = current_stock / avg_daily
    else:
        projected_days = None  # demand=0 → infinite runway; surface as null

    target_supply = target_days * avg_daily
    recommended_reorder = max(0.0, target_supply - current_stock)

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
    )
