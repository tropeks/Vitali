# mypy: ignore-errors
"""
Pharmacy Celery tasks — expiry and low-stock alerts per tenant.
Tasks run for every tenant via schema_context (django-tenants).
Results are stored in Redis for the stock dashboard.
"""

import json
import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone
from django_tenants.utils import get_tenant_model, schema_context

logger = logging.getLogger(__name__)


def _get_redis():
    import redis

    return redis.from_url(getattr(settings, "CELERY_BROKER_URL", "redis://localhost:6379/0"))


@shared_task(name="pharmacy.check_expiry_alerts")
def check_expiry_alerts():
    """
    For each tenant: find stock items expiring in ≤ 30 days.
    Stores item list (not just count) in Redis key pharmacy:{schema}:expiry_alerts.
    """
    Tenant = get_tenant_model()
    for tenant in Tenant.objects.exclude(schema_name="public"):
        try:
            with schema_context(tenant.schema_name):
                _check_expiry_alerts_for_tenant(tenant.schema_name)
        except Exception:
            logger.exception("check_expiry_alerts failed for tenant %s", tenant.schema_name)


def _check_expiry_alerts_for_tenant(schema_name: str):
    from .models import StockItem

    today = timezone.now().date()
    threshold = today + timedelta(days=30)
    expiring = (
        StockItem.objects.filter(
            quantity__gt=0,
            expiry_date__isnull=False,
            expiry_date__lte=threshold,
            expiry_date__gte=today,
        )
        .select_related("drug", "material")
        .values(
            "id",
            "lot_number",
            "expiry_date",
            "quantity",
            "drug__name",
            "material__name",
        )
    )
    items = []
    for item in expiring:
        items.append(
            {
                "id": str(item["id"]),
                "lot_number": item["lot_number"],
                "expiry_date": str(item["expiry_date"]),
                "quantity": str(item["quantity"]),
                "name": item["drug__name"] or item["material__name"] or "—",
            }
        )
    r = _get_redis()
    key = f"pharmacy:{schema_name}:expiry_alerts"
    r.set(key, json.dumps(items), ex=86400)  # 24 h TTL
    logger.info("check_expiry_alerts: %d items written to %s", len(items), key)


@shared_task(name="pharmacy.check_min_stock_alerts")
def check_min_stock_alerts():
    """
    For each tenant: find stock items below min_stock threshold.
    Stores item list in Redis key pharmacy:{schema}:min_stock_alerts.
    """
    Tenant = get_tenant_model()
    for tenant in Tenant.objects.exclude(schema_name="public"):
        try:
            with schema_context(tenant.schema_name):
                _check_min_stock_alerts_for_tenant(tenant.schema_name)
        except Exception:
            logger.exception("check_min_stock_alerts failed for tenant %s", tenant.schema_name)


def _check_min_stock_alerts_for_tenant(schema_name: str):
    from django.db.models import F

    from .models import StockItem

    low = (
        StockItem.objects.filter(
            quantity__lt=F("min_stock"),
            min_stock__gt=0,
        )
        .select_related("drug", "material")
        .values(
            "id",
            "lot_number",
            "quantity",
            "min_stock",
            "drug__name",
            "material__name",
        )
    )
    items = []
    for item in low:
        items.append(
            {
                "id": str(item["id"]),
                "lot_number": item["lot_number"],
                "quantity": str(item["quantity"]),
                "min_stock": str(item["min_stock"]),
                "name": item["drug__name"] or item["material__name"] or "—",
            }
        )
    r = _get_redis()
    key = f"pharmacy:{schema_name}:min_stock_alerts"
    r.set(key, json.dumps(items), ex=86400)
    logger.info("check_min_stock_alerts: %d items written to %s", len(items), key)


@shared_task(name="pharmacy.evaluate_stockout")
def evaluate_stockout():
    """Stockout-prediction wedge S2 — nightly proactive evaluation across every tenant.

    Thin wrapper around the ``evaluate_stockout`` management command, fanned out
    over all tenants via ``tenant_context`` (Celery beat fires in the public
    schema). No-op per tenant when the ``stockout_safety`` flag is OFF (the
    service guards this internally). Registered nightly at 02:30 UTC via the
    PeriodicTask in pharmacy migration 0020; also runnable by hand as
    ``manage.py evaluate_stockout``.
    """
    from django.core.management import call_command
    from django_tenants.utils import tenant_context

    Tenant = get_tenant_model()
    for tenant in Tenant.objects.exclude(schema_name="public"):
        try:
            with tenant_context(tenant):
                call_command("evaluate_stockout")
        except Exception:
            logger.exception("evaluate_stockout failed for tenant %s", tenant.schema_name)


@shared_task(name="pharmacy.grade_stockout_predictions")
def grade_stockout_predictions():
    """Stockout-prediction wedge S4 — nightly flywheel.

    Thin wrapper around the ``grade_stockout_predictions`` management command:
    runs it for EVERY tenant via ``tenant_context`` (Celery beat fires in the
    public schema). Grades each past-due ``stockout_risk`` prediction by what
    actually happened (true_positive / intercepted / false_positive). Idempotent,
    flag-independent (only grades already-created alerts). Registered to run
    nightly via the django_celery_beat PeriodicTask created in pharmacy migration
    0012; can also be run by hand as ``manage.py grade_stockout_predictions``.
    """
    from django.core.management import call_command
    from django_tenants.utils import tenant_context

    Tenant = get_tenant_model()
    for tenant in Tenant.objects.exclude(schema_name="public"):
        try:
            with tenant_context(tenant):
                call_command("grade_stockout_predictions")
        except Exception:
            logger.exception("grade_stockout_predictions failed for tenant %s", tenant.schema_name)
