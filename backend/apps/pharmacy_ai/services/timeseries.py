"""
Daily-demand time series construction for the AI Farmácia forecast (issue #131).

The learned seasonality model needs a *regular* daily series — one bucket per
calendar day, zeros included — whereas the arithmetic baseline only needs a
single windowed sum. This module turns the irregular `StockMovement` dispense
ledger into that regular series so the forecaster can see weekly patterns.

Pure-ish: a single bounded query + in-Python bucketing. No N+1, no model
training here (that lives in `learned.py`).
"""

from __future__ import annotations

import datetime

from django.db.models import QuerySet

from apps.pharmacy.models import Drug, StockMovement


def build_daily_demand(
    drug: Drug,
    *,
    end: datetime.datetime,
    days: int,
) -> list[float]:
    """
    Build a zero-filled daily demand series for ``drug`` over the ``days`` days
    ending at ``end`` (exclusive), oldest day first.

    Demand = absolute quantity of ``dispense`` movements. Dispense entries store
    a *negative* quantity (stock leaves), so we negate to get a positive demand;
    any non-negative dispense row (data corruption) contributes 0 rather than a
    nonsense negative spike. Adjustments / returns / write-offs are deliberately
    excluded — they are not consumption signals (mirrors the baseline service).

    Returns a list of length ``days``: index 0 is the oldest day, index
    ``days - 1`` is the most recent.
    """
    if days <= 0:
        raise ValueError("days must be positive.")

    start = end - datetime.timedelta(days=days)
    rows: QuerySet = StockMovement.objects.filter(
        stock_item__drug=drug,
        movement_type="dispense",
        created_at__gte=start,
        created_at__lt=end,
    ).values_list("created_at", "quantity")

    buckets = [0.0] * days
    for created_at, quantity in rows.iterator():
        # Bucket by whole-day offset from ``start``. Using the datetime delta
        # (not .date()) keeps bucketing timezone-agnostic and matches how the
        # ledger records timestamps; ``created_at >= start`` is guaranteed by
        # the filter so the offset is always >= 0.
        idx = (created_at - start).days
        if 0 <= idx < days:
            demand = float(-quantity)
            if demand > 0:
                buckets[idx] += demand

    return buckets
