"""
S-063: Django signals for EMR app.

Prescription safety signal:
  Fires after a PrescriptionItem is created.
  Uses transaction.on_commit() to defer the Celery task dispatch until
  after the DB transaction commits. This prevents a race condition where
  the Celery worker tries to read the PrescriptionItem before it is
  visible in the database.

  Why on_commit() and NOT direct .delay() in post_save:
    post_save fires during the transaction. If we call .delay() directly,
    the Celery worker may start before the COMMIT reaches the DB replica
    (or even the primary in autocommit=False scenarios), causing a
    DoesNotExist error on the first attempt and wasting retry budget.
    on_commit() guarantees the task fires only after the write is durable.
"""
import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(post_save, sender="emr.PrescriptionItem")
def trigger_safety_check(sender, instance, created, **kwargs):
    """
    Dispatch the check_prescription_safety Celery task after a new
    PrescriptionItem is committed to the database.

    Only fires on creation (not updates) to avoid re-checking on every edit.
    Uses transaction.on_commit() so the task has the committed row available.
    """
    if not created:
        return

    # Import here to avoid circular import at module load time
    from apps.emr.tasks import check_prescription_safety

    # transaction.on_commit() defers .delay() until after the outer
    # transaction commits. Safe to call even outside a transaction block —
    # Django treats the operation as already committed in that case.
    transaction.on_commit(
        lambda: check_prescription_safety.delay(str(instance.id))
    )

    logger.debug(
        "Scheduled safety check for PrescriptionItem %s (on_commit)",
        instance.id,
    )
