"""
L2 — ADT admissão/internação service: the bed-occupancy state machine.

Admit/discharge are driven ONLY through this module (never raw serializer.save)
so a Bed's operational ``status``, the :class:`Admission` row, and the
append-only :class:`AdmissionEvent` log always move together inside one
``transaction.atomic``. L3 (transfer/census) will add a ``transfer`` here that
moves ``current_bed`` and appends a ``transfer`` event (from+to bed).

Contract for L3:
- ``admit`` leaves the bed ``ocupado`` with an active (status=admitted) Admission
  whose ``current_bed`` is that bed; the ``uniq_active_admission_per_bed`` partial
  constraint guarantees single occupancy.
- ``discharge`` frees the bed to ``higienizacao`` and nulls ``current_bed``.
- Every transition appends exactly one AdmissionEvent.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.emr.models import Admission, AdmissionEvent, Bed

# Bed statuses from which a fresh admission may occupy the bed. ``reservado`` is
# accepted (bed held for this patient); everything else (ocupado, higienizacao,
# bloqueado, interditado) is rejected.
_ADMITTABLE_STATUSES = frozenset({Bed.Status.LIVRE, Bed.Status.RESERVADO})


@transaction.atomic
def admit(
    *,
    patient: Any,
    bed: Bed,
    admitting_professional: Any,
    attending_professional: Any,
    admission_source: str = Admission.AdmissionSource.OUTRO,
    admission_datetime: Any | None = None,
    expected_discharge_datetime: Any | None = None,
    encounter: Any | None = None,
    actor: Any | None = None,
    reason: str = "",
) -> Admission:
    """Admit ``patient`` to ``bed``: create an active Admission, occupy the bed,
    and append an ``admit`` event — atomically.

    Raises ``ValidationError`` if the bed is not ``livre``/``reservado``.
    """
    # Lock the bed row to serialize concurrent admits on the same bed.
    locked_bed = Bed.objects.select_for_update().get(pk=bed.pk)
    if locked_bed.status not in _ADMITTABLE_STATUSES:
        raise ValidationError(
            f"Leito {locked_bed.identifier} indisponível para internação "
            f"(situação: {locked_bed.get_status_display()})."
        )

    admission = Admission.objects.create(
        patient=patient,
        admitting_professional=admitting_professional,
        attending_professional=attending_professional,
        current_bed=locked_bed,
        encounter=encounter,
        admission_source=admission_source,
        admission_datetime=admission_datetime or timezone.now(),
        expected_discharge_datetime=expected_discharge_datetime,
        status=Admission.Status.ADMITTED,
    )

    locked_bed.status = Bed.Status.OCUPADO
    locked_bed.save(update_fields=["status", "updated_at"])

    AdmissionEvent.objects.create(
        admission=admission,
        event_type=AdmissionEvent.EventType.ADMIT,
        from_bed=None,
        to_bed=locked_bed,
        actor=actor,
        reason=reason,
    )
    return admission


@transaction.atomic
def discharge(
    *,
    admission: Admission,
    disposition: str,
    actual_discharge_datetime: Any | None = None,
    actor: Any | None = None,
    reason: str = "",
) -> Admission:
    """Discharge an active ``admission``: mark it discharged with a disposition,
    free its bed (→ ``higienizacao``), null ``current_bed``, and append a
    ``discharge`` event — atomically.

    Raises ``ValidationError`` if the admission is not active (status=admitted).
    """
    locked = Admission.objects.select_for_update().get(pk=admission.pk)
    if locked.status != Admission.Status.ADMITTED:
        raise ValidationError("Internação não está ativa; não pode receber alta.")

    freed_bed = None
    if locked.current_bed_id:
        freed_bed = Bed.objects.select_for_update().get(pk=locked.current_bed_id)
        freed_bed.status = Bed.Status.HIGIENIZACAO
        freed_bed.save(update_fields=["status", "updated_at"])

    locked.status = Admission.Status.DISCHARGED
    locked.disposition = disposition
    locked.actual_discharge_datetime = actual_discharge_datetime or timezone.now()
    locked.current_bed = None
    locked.save(
        update_fields=[
            "status",
            "disposition",
            "actual_discharge_datetime",
            "current_bed",
            "updated_at",
        ]
    )

    AdmissionEvent.objects.create(
        admission=locked,
        event_type=AdmissionEvent.EventType.DISCHARGE,
        from_bed=freed_bed,
        to_bed=None,
        actor=actor,
        reason=reason,
    )
    return locked
