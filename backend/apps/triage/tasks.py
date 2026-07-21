"""
Triage Celery tasks.

`send_triage_emergency_notification` delivers an emergency-classified WhatsApp
triage to the staff configured in the tenant's `EscalationConfig`. It mirrors
`apps.emr.tasks.send_escalation_notification`: a fail-open delivery stub that
logs the alert today and is the swap-in point for real email / WhatsApp
delivery later. The durable trail (AuditLog) is written synchronously by
`apps.triage.services.notifications` BEFORE this task is enqueued, so a delivery
failure never loses the escalation record.
"""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def send_triage_emergency_notification(self, triage_session_id: str, notify_emails: list) -> None:
    """Notify configured staff that a WhatsApp triage classified as emergency.

    Fail-open: a persistent delivery failure is logged but never affects the
    TriageSession or its AuditLog (both committed before this runs).
    """
    logger.warning(
        "send_triage_emergency_notification: triage=%s recipients=%s",
        triage_session_id,
        notify_emails,
    )
