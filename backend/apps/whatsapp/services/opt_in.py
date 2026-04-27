import logging
from uuid import uuid4

from django.db import transaction

from apps.core.models import AuditLog

logger = logging.getLogger(__name__)


def notify_opt_in_completed(contact) -> None:
    """
    Called by WhatsAppContact.do_opt_in() inside the FSM hot path. Enqueues
    the post-opt-in welcome message via transaction.on_commit (fail-open).
    AuditLog with correlation_id (decision 2A).

    No-op if contact has no linked patient (e.g. inbound from unknown number
    that hasn't been linked yet — the FSM creates a contact lazily).
    """
    from apps.whatsapp.tasks import send_post_opt_in_welcome  # local import — avoid circular

    if not contact.patient_id:
        logger.info(
            "notify_opt_in_completed: contact %s has no patient — skipping welcome",
            contact.id,
        )
        return

    correlation_id = str(uuid4())
    AuditLog.objects.create(
        user=None,
        action="opt_in_completed",
        resource_type="whatsapp_contact",
        resource_id=str(contact.id),
        new_data={
            "phone": contact.phone,
            "patient_id": str(contact.patient_id),
            "correlation_id": correlation_id,
        },
    )
    contact_id = str(contact.id)
    transaction.on_commit(lambda: send_post_opt_in_welcome.delay(contact_id, correlation_id))
