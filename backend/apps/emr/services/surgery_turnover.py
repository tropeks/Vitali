"""
CS3 — Centro Cirúrgico: turnover de sala (higienização/preparo entre cirurgias).

The operational lifecycle of a :class:`~apps.emr.models.RoomTurnover` record — the
cleaning/preparation window a room goes through between two surgical cases. Kept
separate from :mod:`apps.emr.services.surgery_scheduling` (which owns the *slot*
state machine and the ``turnover_minutes`` ENFORCEMENT during scheduling): this
module only opens and closes the turnover LOG.

Lifecycle::

    open_turnover(room, case_out=?, at=?, by=?)  →  RoomTurnover(status=AGUARDANDO)
    complete_turnover(turnover, at=?)            →  status=PRONTA, ready_at set

Both operations run under ``transaction.atomic``. Simple by design: no guard
against multiple open turnovers on the same room (a site may model that
operationally); the scheduling gap invariant lives in the scheduling service.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.emr.models import OperatingRoom, RoomTurnover, SurgicalCase


@transaction.atomic
def open_turnover(
    operating_room: OperatingRoom,
    *,
    case_out: SurgicalCase | None = None,
    at: Any | None = None,
    by: Any | None = None,
) -> RoomTurnover:
    """Open a new ``AGUARDANDO`` turnover for ``operating_room``.

    ``case_out`` is the surgery that just left (optional); ``at`` defaults to now
    (the moment the room was freed); ``by`` is the ``core.User`` that opened it.
    """
    return RoomTurnover.objects.create(
        operating_room=operating_room,
        case_out=case_out,
        started_at=at or timezone.now(),
        status=RoomTurnover.Status.AGUARDANDO,
        created_by=by,
    )


@transaction.atomic
def complete_turnover(turnover: RoomTurnover, *, at: Any | None = None) -> RoomTurnover:
    """Mark ``turnover`` ready: set ``ready_at`` and ``status = PRONTA``.

    ``at`` defaults to now. Idempotent-friendly: re-completing simply refreshes
    ``ready_at`` and keeps the status ``PRONTA``.
    """
    locked = RoomTurnover.objects.select_for_update().get(pk=turnover.pk)
    locked.ready_at = at or timezone.now()
    locked.status = RoomTurnover.Status.PRONTA
    locked.save(update_fields=["ready_at", "status", "updated_at"])
    return locked
