"""
M2-S3-T3 — Laboratory delta check.
=================================
On a new numeric lab result, compare it to the patient's most recent PRIOR
numeric result for the *same test*. If the percentage variation exceeds the
test's configured ``delta_threshold_pct``, raise a :class:`LabDeltaAlert`.

Design (honest, no fabrication):
  * The threshold is per-test config (``LabTest.delta_threshold_pct``). NULL →
    the check is INERT for that test (returns None, no alert).
  * "Most recent prior result" = the newest LabOrderItem for the same patient +
    test with a ``resulted_at`` strictly before this result's, whose
    ``result_value`` parses as a number. No prior → no alert.
  * Variation is ``|current - prior| / |prior| * 100`` (percent). A zero prior
    baseline can't yield a percentage, so it never fires (returns None).
  * Idempotent: keyed on the triggering ``order_item`` (OneToOne) — re-running
    updates the same alert row, never duplicates.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from apps.emr.models import LabDeltaAlert, LabOrderItem


def _parse_numeric(raw) -> Decimal | None:
    """Parse a lab result value to Decimal, or None if it is not numeric.

    Accepts a leading comparator/sign and comma decimals ("1,23", ">5"). Returns
    None for qualitative/blank values so the delta check silently skips them.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    # Strip a leading comparator often present in lab values (<, >, ≤, ≥, =).
    for prefix in ("<=", ">=", "≤", "≥", "<", ">", "="):
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
            break
    text = text.replace(",", ".")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _most_recent_prior(order_item: LabOrderItem) -> tuple[LabOrderItem | None, Decimal | None]:
    """Return the newest prior numeric result for the same patient + test."""
    if order_item.resulted_at is None:
        return None, None
    candidates = (
        LabOrderItem.objects.filter(
            order__patient_id=order_item.order.patient_id,
            test_id=order_item.test_id,
            resulted_at__isnull=False,
            resulted_at__lt=order_item.resulted_at,
        )
        .exclude(pk=order_item.pk)
        .order_by("-resulted_at")
    )
    for prior in candidates.iterator():
        value = _parse_numeric(prior.result_value)
        if value is not None:
            return prior, value
    return None, None


def run_delta_check(order_item: LabOrderItem) -> LabDeltaAlert | None:
    """Evaluate the delta check for a freshly resulted ``order_item``.

    Returns the created/updated :class:`LabDeltaAlert` when the variation exceeds
    the test threshold, else ``None`` (no prior, inert test, non-numeric value,
    or within threshold).
    """
    test = order_item.test
    threshold = test.delta_threshold_pct
    if threshold is None:  # test not configured → inert
        return None

    current = _parse_numeric(order_item.result_value)
    if current is None:
        return None

    prior_item, prior_value = _most_recent_prior(order_item)
    if prior_item is None or prior_value is None:
        return None  # no prior result → no alert
    if prior_value == 0:
        return None  # cannot compute a percentage from a zero baseline

    delta_absolute = current - prior_value
    delta_pct = (abs(delta_absolute) / abs(prior_value)) * Decimal("100")

    if delta_pct <= Decimal(threshold):
        return None  # within the configured threshold → no alert

    alert, _created = LabDeltaAlert.objects.update_or_create(
        order_item=order_item,
        defaults={
            "previous_item": prior_item,
            "test": test,
            "previous_value": prior_value,
            "current_value": current,
            "delta_absolute": delta_absolute,
            "delta_pct": delta_pct,
            "threshold_pct": threshold,
        },
    )
    return alert
