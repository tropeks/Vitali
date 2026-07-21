"""
Daily wedge business-value snapshot task — issue #123.

``snapshot_wedge_value`` iterates every active tenant, computes its wedge ROI
metrics via ``apps.core.services.wedge_value`` (which schema-switches per tenant),
and ``update_or_create``s one ``WedgeValueSnapshot`` row per tenant for today in
the PUBLIC schema. The platform dashboard then reads these pre-computed rows
without fanning out across schemas on every request.

Registered to run once a day in ``vitali/celery.py`` (beat_schedule). The task is
idempotent: re-running on the same day refreshes the day's rows rather than
duplicating them. One tenant failing does not abort the others.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name="core.snapshot_wedge_value")
def snapshot_wedge_value(window_days: int = 30) -> dict:
    """Compute and persist today's wedge-value snapshot for every active tenant.

    Returns a small summary dict (counts) for observability / task result.
    """
    from apps.core.models import Tenant, WedgeValueSnapshot
    from apps.core.services.wedge_value import compute_wedge_value_for_tenant

    now = timezone.now()
    today = now.date()

    tenants = list(Tenant.objects.exclude(schema_name="public"))
    succeeded = 0
    failed = 0

    for tenant in tenants:
        try:
            metrics = compute_wedge_value_for_tenant(tenant, window_days=window_days, now=now)
            WedgeValueSnapshot.objects.update_or_create(
                schema_name=tenant.schema_name,
                snapshot_date=today,
                defaults={
                    "tenant_name": tenant.name,
                    "window_days": window_days,
                    "metrics": metrics,
                },
            )
            succeeded += 1
        except Exception as exc:  # pragma: no cover - defensive per-tenant guard
            failed += 1
            logger.error(
                "snapshot_wedge_value.tenant_failed tenant=%s err=%s",
                tenant.schema_name,
                exc,
            )

    summary = {
        "snapshot_date": today.isoformat(),
        "tenants_total": len(tenants),
        "succeeded": succeeded,
        "failed": failed,
    }
    logger.info("snapshot_wedge_value.done %s", summary)
    return summary
