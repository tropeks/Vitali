"""
Triage staff-notification service.

When a WhatsApp triage classifies as ``emergency``, configured clinical staff
must be paged (CFM Res. 2.314/2022 §6 — a non-presential triage that fires a red
flag must escalate to a licensed professional). This module is the escalation
bridge between the triage FSM and the tenant's notification config.

POSTURE — ALWAYS FAIL-SAFE. The TriageSession (with its urgency classification)
is already committed before notification runs; any error here is logged and
swallowed so a notification failure never breaks the patient's WhatsApp flow.

Recipients are read from the per-tenant ``EscalationConfig.notify_emails`` —
the same "configured staff" list used by the clinical-deterioration escalation
router (`apps.emr.services.escalation`), so operators configure escalation once.
"""

from __future__ import annotations

import logging

from django.db import transaction

logger = logging.getLogger(__name__)


def notify_staff_emergency(session) -> None:
    """Page configured staff about an emergency triage. Never raises.

    Writes an AuditLog row synchronously (durable trail) then best-effort
    enqueues delivery via ``send_triage_emergency_notification``.
    """
    try:
        _notify(session)
    except Exception:
        logger.exception(
            "notify_staff_emergency failed for TriageSession %s; failing safe.",
            getattr(session, "id", None),
        )


def _notify(session) -> None:
    from apps.core.models import AuditLog

    recipients = _recipients()

    AuditLog.objects.create(
        action="triage_emergency_escalated",
        resource_type="triage_session",
        resource_id=str(session.id),
        new_data={
            "triage_session_id": str(session.id),
            "urgency": session.urgency,
            "contact_phone": session.contact_phone,
            "chief_complaint": session.chief_complaint,
            "matched_keywords": list(session.matched_keywords or []),
            "red_flags_positive": session.red_flags_positive,
            "notify_emails": recipients,
        },
    )

    if not recipients:
        logger.warning(
            "Emergency TriageSession %s has no EscalationConfig recipients; "
            "audit trail written, no delivery enqueued.",
            session.id,
        )
        return

    session_id = str(session.id)

    def _enqueue() -> None:
        try:
            from apps.triage.tasks import send_triage_emergency_notification

            send_triage_emergency_notification.delay(session_id, recipients)
        except Exception:
            logger.warning(
                "Could not enqueue send_triage_emergency_notification for %s; "
                "audit trail is already written.",
                session_id,
            )

    # Defer delivery until the surrounding DB transaction commits so we never
    # page staff about a session that ends up rolled back. on_commit runs the
    # callback immediately when not in an atomic block.
    transaction.on_commit(_enqueue)


def _recipients() -> list[str]:
    """Configured staff emails for this tenant, or [] when unconfigured."""
    try:
        from apps.emr.models import EscalationConfig

        config = EscalationConfig.objects.filter(is_active=True).order_by("-created_at").first()
        if config and config.notify_emails:
            return list(config.notify_emails)
    except Exception:
        logger.exception("Could not load EscalationConfig for triage emergency.")
    return []
