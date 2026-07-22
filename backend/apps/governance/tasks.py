"""Tenant-aware workers for the durable integration boundary."""

import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone
from django_tenants.utils import schema_context

from .integrations import handle_inbox, publish_outbox
from .services import InboxService, OutboxService

logger = logging.getLogger(__name__)


def _backoff(attempts: int):
    return timezone.now() + timedelta(seconds=min(3600, 15 * (2 ** min(attempts, 8))))


@shared_task(name="governance.dispatch_outbox")
def dispatch_outbox(schema_name: str, limit: int = 100) -> dict:
    metrics = {"claimed": 0, "published": 0, "failed": 0, "dead": 0}
    with schema_context(schema_name):
        rows = OutboxService.claim_batch(limit=limit)
        metrics["claimed"] = len(rows)
        for event in rows:
            try:
                publish_outbox(event)
                OutboxService.mark_published(event)
                metrics["published"] += 1
            except Exception as exc:  # handlers are an external failure boundary
                logger.exception(
                    "integration.outbox.failed",
                    extra={
                        "schema": schema_name,
                        "event_id": str(event.pk),
                        "event_type": event.event_type,
                        "attempt": event.attempts,
                    },
                )
                OutboxService.mark_failed(event, error=str(exc), retry_at=_backoff(event.attempts))
                event.refresh_from_db(fields=("status",))
                metrics["dead" if event.status == event.Status.DEAD else "failed"] += 1
    logger.info("integration.outbox.batch", extra={"schema": schema_name, **metrics})
    return metrics


@shared_task(name="governance.process_inbox")
def process_inbox(schema_name: str, limit: int = 100) -> dict:
    metrics = {"claimed": 0, "completed": 0, "failed": 0, "dead": 0}
    with schema_context(schema_name):
        rows = InboxService.claim_batch(limit=limit)
        metrics["claimed"] = len(rows)
        for message in rows:
            try:
                handle_inbox(message.message_type, message.payload, message.headers)
                InboxService.mark_completed(message)
                metrics["completed"] += 1
            except Exception as exc:  # handlers are an external failure boundary
                logger.exception(
                    "integration.inbox.failed",
                    extra={
                        "schema": schema_name,
                        "message_id": str(message.pk),
                        "message_type": message.message_type,
                        "attempt": message.attempts,
                    },
                )
                InboxService.mark_failed(
                    message, error=str(exc), retry_at=_backoff(message.attempts)
                )
                message.refresh_from_db(fields=("status",))
                metrics["dead" if message.status == message.Status.DEAD else "failed"] += 1
    logger.info("integration.inbox.batch", extra={"schema": schema_name, **metrics})
    return metrics
