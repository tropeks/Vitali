"""
C2 — Centro Cirúrgico scheduling service: the surgical-case slot state machine.

Scheduling of a :class:`SurgicalCase` onto an :class:`OperatingRoom` is driven
ONLY through this module (never raw ``serializer.save``) so the room + times +
status always move together inside one ``transaction.atomic`` and the room-slot
overlap-guard runs under a row lock. This mirrors :mod:`apps.emr.services.adt`
(atomic + ``select_for_update`` + raise ``ValidationError``; the viewset surfaces
that as HTTP 409).

Overlap-guard (the core C2 invariant)
-------------------------------------
Two surgical cases may not occupy the SAME room at overlapping times. A case
BLOCKS a slot while its status is one of ``agendada / confirmada / em_sala /
em_andamento`` — a ``finalizada`` or ``cancelada`` case never blocks (the slot is
free). The overlap predicate is the standard half-open-interval test::

    existing.scheduled_start < new_end  AND  existing.scheduled_end > new_start

i.e. ``[start, end)`` intervals overlap. We serialize concurrent scheduling on a
room by taking a ``select_for_update`` lock on the ``OperatingRoom`` row before
running the guard.

Allowed status transitions
--------------------------
    agendada    → confirmada          (confirm)
    agendada    → cancelada           (cancel)
    confirmada  → cancelada           (cancel)
    em_sala     → cancelada           (cancel)  [em_sala/em_andamento are set in a later sprint]
    em_andamento→ cancelada           (cancel)

    schedule / reschedule are allowed only FROM ``agendada`` or ``confirmada``
    (a case already in the room, finished, or cancelled cannot be (re)timed). A
    ``schedule`` on an ``agendada`` case keeps it ``agendada``; on a ``confirmada``
    case it keeps ``confirmada`` (re-timing a confirmed case does not un-confirm
    it). ``confirm`` requires the case to be ``agendada``. ``cancel`` is allowed
    from any status EXCEPT ``finalizada`` (a finished case cannot be cancelled).

Nothing here touches checklist / times / team (C3) or OPME (C6).
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.emr.models import OperatingRoom, SurgicalCase

# Statuses in which a case still occupies its room slot (blocks overlapping
# scheduling on the same room). finalizada / cancelada free the slot.
_BLOCKING_STATUSES = frozenset(
    {
        SurgicalCase.Status.AGENDADA,
        SurgicalCase.Status.CONFIRMADA,
        SurgicalCase.Status.EM_SALA,
        SurgicalCase.Status.EM_ANDAMENTO,
    }
)

# Statuses from which a case may be (re)scheduled onto a room+time slot.
_SCHEDULABLE_FROM = frozenset(
    {
        SurgicalCase.Status.AGENDADA,
        SurgicalCase.Status.CONFIRMADA,
    }
)


def _require_time_order(start: Any, end: Any) -> None:
    if start is None or end is None:
        raise ValidationError("Início e fim do agendamento são obrigatórios.")
    if end <= start:
        raise ValidationError("O fim do agendamento deve ser posterior ao início.")


def _assert_no_overlap(*, room: OperatingRoom, start: Any, end: Any, exclude_pk: Any) -> None:
    """Raise ``ValidationError`` if any OTHER blocking case on ``room`` overlaps
    the half-open interval ``[start, end)``. Assumes the room row is locked."""
    conflict = (
        SurgicalCase.objects.filter(
            operating_room=room,
            status__in=_BLOCKING_STATUSES,
            scheduled_start__lt=end,
            scheduled_end__gt=start,
        )
        .exclude(pk=exclude_pk)
        .exists()
    )
    if conflict:
        raise ValidationError(
            f"Conflito de agenda: a sala {room.code} já está ocupada nesse horário."
        )


@transaction.atomic
def schedule(
    case: SurgicalCase,
    operating_room: OperatingRoom,
    start: Any,
    end: Any,
    *,
    actor: Any | None = None,
) -> SurgicalCase:
    """Assign ``operating_room`` + ``[start, end)`` to ``case`` after the room-slot
    overlap-guard — atomically, under a lock on the room row.

    The case status is preserved (``agendada`` stays ``agendada``; a ``confirmada``
    case being re-timed stays ``confirmada``). Raises ``ValidationError`` if
    ``end <= start``, the case is not schedulable (finalizada/cancelada/in-room),
    or the slot overlaps another blocking case on the same room.
    """
    _require_time_order(start, end)
    # Lock the room row to serialize concurrent scheduling on the same room, then
    # lock the case row.
    OperatingRoom.objects.select_for_update().get(pk=operating_room.pk)
    locked = SurgicalCase.objects.select_for_update().get(pk=case.pk)
    if locked.status not in _SCHEDULABLE_FROM:
        raise ValidationError(
            f"Caso cirúrgico em situação '{locked.get_status_display()}' não pode ser agendado."
        )

    _assert_no_overlap(room=operating_room, start=start, end=end, exclude_pk=locked.pk)

    locked.operating_room = operating_room
    locked.scheduled_start = start
    locked.scheduled_end = end
    locked.save(update_fields=["operating_room", "scheduled_start", "scheduled_end", "updated_at"])
    return locked


@transaction.atomic
def reschedule(
    case: SurgicalCase,
    start: Any,
    end: Any,
    operating_room: OperatingRoom | None = None,
    *,
    actor: Any | None = None,
) -> SurgicalCase:
    """Move ``case`` to a new ``[start, end)`` (optionally a new ``operating_room``)
    after the overlap-guard EXCLUDING the case itself — atomically, under a lock
    on the target room row.

    ``operating_room=None`` keeps the case's current room (error if it has none).
    Status is preserved. Same rejection rules as :func:`schedule`.
    """
    _require_time_order(start, end)
    locked = SurgicalCase.objects.select_for_update().get(pk=case.pk)
    if locked.status not in _SCHEDULABLE_FROM:
        raise ValidationError(
            f"Caso cirúrgico em situação '{locked.get_status_display()}' não pode ser reagendado."
        )

    target_room = operating_room or locked.operating_room
    if target_room is None:
        raise ValidationError("Caso cirúrgico sem sala; informe a sala para reagendar.")

    OperatingRoom.objects.select_for_update().get(pk=target_room.pk)
    _assert_no_overlap(room=target_room, start=start, end=end, exclude_pk=locked.pk)

    locked.operating_room = target_room
    locked.scheduled_start = start
    locked.scheduled_end = end
    locked.save(update_fields=["operating_room", "scheduled_start", "scheduled_end", "updated_at"])
    return locked


@transaction.atomic
def confirm(case: SurgicalCase, *, actor: Any | None = None) -> SurgicalCase:
    """Confirm an ``agendada`` case → ``confirmada``. Raises ``ValidationError``
    if the case is not currently ``agendada``."""
    locked = SurgicalCase.objects.select_for_update().get(pk=case.pk)
    if locked.status != SurgicalCase.Status.AGENDADA:
        raise ValidationError(
            f"Só é possível confirmar um caso agendado (situação atual: "
            f"'{locked.get_status_display()}')."
        )
    locked.status = SurgicalCase.Status.CONFIRMADA
    locked.save(update_fields=["status", "updated_at"])
    return locked


@transaction.atomic
def cancel(case: SurgicalCase, *, reason: str = "", actor: Any | None = None) -> SurgicalCase:
    """Cancel a case → ``cancelada`` (frees its room slot). Raises
    ``ValidationError`` if the case is already ``finalizada`` (a finished case
    cannot be cancelled) or already ``cancelada``."""
    locked = SurgicalCase.objects.select_for_update().get(pk=case.pk)
    if locked.status == SurgicalCase.Status.FINALIZADA:
        raise ValidationError("Caso cirúrgico finalizado não pode ser cancelado.")
    if locked.status == SurgicalCase.Status.CANCELADA:
        raise ValidationError("Caso cirúrgico já está cancelado.")
    locked.status = SurgicalCase.Status.CANCELADA
    if reason:
        note = f"[cancelamento] {reason}"
        locked.notes = f"{locked.notes}\n{note}".strip() if locked.notes else note
        locked.save(update_fields=["status", "notes", "updated_at"])
    else:
        locked.save(update_fields=["status", "updated_at"])
    return locked
