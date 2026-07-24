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
from django.db.models.deletion import ProtectedError
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver

logger = logging.getLogger(__name__)


# ─── CID10Code cross-schema PROTECT for ProblemListItem (E2-T1) ───────────────
# Sibling of apps/core/signals.py::protect_cid10_code_deletion (which covers
# MedicalHistory + SOAPNote). Same rationale: PostgreSQL cannot enforce FK
# integrity across schemas (public core.CID10Code → tenant emr), so deleting a
# CID-10 code referenced by a ProblemListItem in ANY tenant is blocked here at
# the application layer. Lives in emr (not core) so E2 stays self-contained.


@receiver(pre_delete, sender="core.CID10Code")
def protect_cid10_code_deletion_problems(sender, instance, **kwargs):
    """Block deletion of a CID10Code referenced by ProblemListItem in any tenant."""
    from django_tenants.utils import get_tenant_model, schema_context

    TenantModel = get_tenant_model()
    for tenant in TenantModel.objects.exclude(schema_name="public"):
        with schema_context(tenant.schema_name):
            from apps.emr.models import ProblemListItem

            if ProblemListItem.objects.filter(cid10=instance).exists():
                raise ProtectedError(
                    f"CID10Code {instance.code} is referenced by ProblemListItem in "
                    f"schema '{tenant.schema_name}' and cannot be deleted.",
                    {instance},
                )


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
    transaction.on_commit(lambda: check_prescription_safety.delay(str(instance.id)))

    logger.debug(
        "Scheduled safety check for PrescriptionItem %s (on_commit)",
        instance.id,
    )


@receiver(post_save, sender="emr.VitalSigns")
def trigger_deterioration_check(sender, instance, created, **kwargs):
    """Run the NEWS2 deterioration check after a VitalSigns row is committed.

    Clinical-deterioration wedge (PR D2). Fires on BOTH create and update — vitals
    are recorded by PATCHing the blank check-in row, so the meaningful evaluation
    happens on update; the blank create scores as incomplete (engine inert → no-op).

    Deferred via ``transaction.on_commit`` so the service reads the committed row
    and — critically — so the synchronous evaluation runs only AFTER the vitals
    save is durable. The save is therefore never blocked or rolled back by the
    check (it is advise/escalation-only). The service itself no-ops when the
    ``deterioration_safety`` flag is OFF and fails safe on any error.
    """
    vital_signs_pk = instance.pk

    def _run():
        # Import here to avoid a circular import at module load time.
        from apps.emr.models import VitalSigns
        from apps.emr.services.deterioration import DeteriorationService

        vs = (
            VitalSigns.objects.select_related("encounter__patient")
            .filter(pk=vital_signs_pk)
            .first()
        )
        if vs is None:  # row deleted between commit and callback
            return
        DeteriorationService().evaluate(vs)

    transaction.on_commit(_run)
