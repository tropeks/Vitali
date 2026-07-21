"""HR signals — F-15 employee termination cascade (issue #128).

Why a signal here (and not for onboarding)
-------------------------------------------
Onboarding (Employee *creation*) is deliberately orchestrated by
``EmployeeOnboardingService`` and NOT by a signal: FK ordering (User must exist
before Professional) makes an explicit service the right tool (locked decision
1A).

*Termination* is the opposite case. Every row already exists, so there is no FK
ordering problem, and a termination can be triggered from many entry points:
the ``DELETE /api/v1/hr/employees/{id}/`` endpoint, a ``PATCH`` that flips
``employment_status`` to ``terminated``, the Django admin, a data migration, or
a management command. A ``post_save`` signal is therefore the correct place to
guarantee the revocation cascade fires *however* an Employee is terminated —
satisfying the F-15 acceptance criterion: "terminating an employee immediately
invalidates sessions and removes the professional from the scheduling agenda."

Re-entrancy
-----------
``EmployeeDeactivationService.deactivate`` saves the Employee as part of its own
work. To stop the signal from recursively re-invoking the service (which would
write duplicate AuditLog entries), the service marks the instance with
``_f15_cascade_active`` while it runs; this handler treats that as "already
being handled" and returns.

Atomicity per entry point
-------------------------
The status flip and the cascade must commit as ONE unit, otherwise a mid-cascade
failure leaves a "terminated" employee with live sessions — and the idempotency
guard turns any retry into a silent no-op (orphaned access). Coverage:

- ``PATCH``/``PUT``/``DELETE`` via ``EmployeeViewSet``: the view wraps the whole
  request in ``transaction.atomic`` and takes ``select_for_update()`` on the
  Employee row, so save + signal + cascade commit (or roll back) together.
- Django admin: ``ModelAdmin`` runs its changeform inside ``transaction.atomic``,
  so the same single-commit guarantee holds.
- Data migrations: run inside the migration's transaction (atomic by default).
- Raw ``Model.save()`` in a shell/management command *outside* ``atomic()``:
  NOT covered — the flip autocommits before ``post_save`` runs, so a cascade
  failure can strand the flip. Scripted terminations must either wrap the save
  in ``transaction.atomic()`` or call ``EmployeeDeactivationService`` directly.

Known limitation: ``QuerySet.update()`` bypasses ``Model.save()`` and therefore
signals (a documented Django behaviour). Every supported termination entry point
goes through ``save()``, so this is acceptable; bulk terminations should call the
service explicitly.
"""

import logging

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .models import Employee

logger = logging.getLogger(__name__)

TERMINATED = "terminated"
# Private instance attributes (set on the in-memory Employee, never persisted).
_PREV_STATUS_ATTR = "_f15_previous_employment_status"
_CASCADE_ACTIVE_ATTR = "_f15_cascade_active"


@receiver(
    pre_save,
    sender=Employee,
    dispatch_uid="hr.f15_capture_previous_employment_status",
)
def capture_previous_employment_status(sender, instance, **kwargs):
    """Stash the persisted employment_status so post_save can detect a transition.

    We read the *old* value straight from the DB (a single indexed lookup) rather
    than trusting any in-memory state, so the transition check is correct even
    when the instance was mutated before saving.
    """
    if instance._state.adding or instance.pk is None:
        setattr(instance, _PREV_STATUS_ATTR, None)
        return
    previous = (
        sender.objects.filter(pk=instance.pk).values_list("employment_status", flat=True).first()
    )
    setattr(instance, _PREV_STATUS_ATTR, previous)


@receiver(
    post_save,
    sender=Employee,
    dispatch_uid="hr.f15_cascade_employee_termination",
)
def cascade_employee_termination(sender, instance, created, **kwargs):
    """Run the F-15 revocation cascade when an Employee transitions to terminated."""
    if created:
        # Onboarding always creates an *active* employee; a row created already
        # terminated is treated as imported data, not a live termination event.
        return
    if instance.employment_status != TERMINATED:
        return

    previous = getattr(instance, _PREV_STATUS_ATTR, None)
    if previous == TERMINATED:
        return  # Already terminated — idempotent no-op.

    if getattr(instance, _CASCADE_ACTIVE_ATTR, False):
        # The service is already running the cascade and just saved the row.
        return

    # Imported lazily to avoid a circular import at app-load time.
    from .services import EmployeeDeactivationService

    logger.info(
        "F-15: employee %s transitioned %s->terminated; running revocation cascade",
        instance.pk,
        previous,
    )
    # Actor attribution: the view path (PATCH/PUT) stashes request.user on the
    # instance as _f15_acting_user (EmployeeViewSet.perform_update) so the audit
    # chain records who terminated the employee. Non-HTTP entry points
    # (admin/ORM/migration) have no request context; AuditLog.user is nullable
    # for exactly that case.
    acting_user = getattr(instance, "_f15_acting_user", None)
    EmployeeDeactivationService().deactivate(instance, requesting_user=acting_user)
