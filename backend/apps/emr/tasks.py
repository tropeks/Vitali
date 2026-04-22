"""
S-063: Celery tasks for AI prescription safety checking.

The post_save signal is wired in EmrConfig.ready() via apps/emr/signals.py.
The signal uses transaction.on_commit() so the task fires only after the DB
transaction commits — prevents race conditions where the task reads data
before the write is visible.
"""

import logging

from celery import shared_task
from django.core.cache import cache
from django.db import transaction

logger = logging.getLogger(__name__)

SAFETY_STATUS_CACHE_TTL = 3600  # 1 hour
SAFETY_STATUS_KEY_TEMPLATE = "ai:safety_status:{item_id}"


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def check_prescription_safety(self, item_id: str):
    """
    Run PrescriptionSafetyChecker for a PrescriptionItem.

    Creates or updates AISafetyAlert records for each flagged alert.
    Updates the item's safety status badge in cache.
    Uses select_for_update() to prevent race conditions on retry.

    Idempotent: unique_together on (prescription_item, alert_type) prevents
    duplicate alerts if the task retries.
    """
    from apps.emr.models import AISafetyAlert, PrescriptionItem
    from apps.emr.services.prescription_safety import PrescriptionSafetyChecker

    status_key = SAFETY_STATUS_KEY_TEMPLATE.format(item_id=item_id)

    try:
        # select_for_update prevents concurrent task instances from racing
        with transaction.atomic():
            try:
                item = (
                    PrescriptionItem.objects.select_for_update()
                    .select_related("prescription__patient", "drug")
                    .get(id=item_id)
                )
            except PrescriptionItem.DoesNotExist:
                logger.warning("PrescriptionItem %s not found, skipping safety check", item_id)
                return

            prescription = item.prescription
            checker = PrescriptionSafetyChecker()
            result = checker.check(item, prescription)

            if result.degraded:
                # Don't create alerts for degraded (LLM error) results
                cache.set(
                    status_key,
                    {"status": "error", "alerts": [], "degraded": True},
                    SAFETY_STATUS_CACHE_TTL,
                )
                return

            # Create or update AISafetyAlert records for each flagged alert
            created_alerts = []
            for alert in result.alerts:
                safety_alert, _ = AISafetyAlert.objects.update_or_create(
                    prescription_item=item,
                    alert_type=alert.alert_type,
                    defaults={
                        "severity": alert.severity,
                        "message": alert.message,
                        "recommendation": alert.recommendation,
                        "status": "flagged",
                    },
                )
                created_alerts.append(
                    {
                        "id": str(safety_alert.id),
                        "alert_type": safety_alert.alert_type,
                        "severity": safety_alert.severity,
                        "message": safety_alert.message,
                        "recommendation": safety_alert.recommendation,
                    }
                )

            # Update cache with final status
            final_status = "safe" if result.is_safe else "flagged"
            cache.set(
                status_key,
                {"status": final_status, "alerts": created_alerts, "degraded": False},
                SAFETY_STATUS_CACHE_TTL,
            )

            logger.info(
                "Safety check complete for item %s: %s (%d alerts)",
                item_id,
                final_status,
                len(created_alerts),
            )

    except Exception as exc:
        logger.exception("Safety check task failed for item %s: %s", item_id, exc)
        # Set error status in cache before retry
        cache.set(
            status_key,
            {"status": "error", "alerts": [], "degraded": True},
            SAFETY_STATUS_CACHE_TTL,
        )
        raise self.retry(exc=exc) from exc
