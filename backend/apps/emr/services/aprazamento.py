"""
N2-T2 — aprazamento (nursing prescription scheduling) service.

*Aprazamento* is the nursing act of laying out WHEN each prescribed intervention
is due. A :class:`~apps.emr.sae_models.NursingPrescriptionItem` carries the
canonical interval ``frequency_hours`` (a "6/6h" order = 6) anchored at
``start_at``; this module expands that into the concrete grid of due execution
times over a window.

There is no pre-existing dose-scheduling service in the codebase (medication
``scheduled_at`` is always supplied by the caller), so this is a clean, pure,
dependency-free function: same inputs → same output (idempotent), no DB writes,
no ``timezone.now()``. Callers persist / reconcile the returned datetimes as they
see fit (e.g. against an execution log), exactly as the eMAR layer treats a
``scheduled_at`` slot.

Public API
----------
* :func:`generate_due_times` — the pure kernel: ``(start, interval_hours,
  window_hours) -> list[datetime]``.
* :func:`build_schedule` — convenience adapter reading ``frequency_hours`` /
  ``start_at`` off a ``NursingPrescriptionItem``.
"""

from __future__ import annotations

from datetime import datetime, timedelta

__all__ = ["generate_due_times", "build_schedule"]


def generate_due_times(
    start: datetime, interval_hours: int, window_hours: int = 24
) -> list[datetime]:
    """Expand a repeating interval into the grid of due times over a window.

    Starting at ``start`` and stepping every ``interval_hours`` hours, emit every
    due time strictly **before** ``start + window_hours`` (the window end is
    exclusive, so a 6/6h order over 24h yields exactly 4 times: the anchor plus
    +6h/+12h/+18h; the +24h tick belongs to the next window).

    Pure and idempotent: no clock reads, no I/O — identical arguments always
    return an identical list.

    Args:
        start: anchor datetime of the first due execution.
        interval_hours: hours between consecutive executions (must be > 0).
        window_hours: length of the scheduling window in hours (default 24).

    Returns:
        Chronologically ordered list of due datetimes (may be empty if
        ``window_hours <= 0``).

    Raises:
        ValueError: if ``interval_hours`` is not a positive integer.
    """
    if interval_hours is None or interval_hours <= 0:
        raise ValueError("interval_hours must be a positive number of hours")

    window_end = start + timedelta(hours=window_hours)
    due: list[datetime] = []
    current = start
    step = timedelta(hours=interval_hours)
    while current < window_end:
        due.append(current)
        current = current + step
    return due


def build_schedule(
    item, *, window_start: datetime | None = None, window_hours: int = 24
) -> list[datetime]:
    """Aprazamento grid for a ``NursingPrescriptionItem`` over a window.

    Reads ``frequency_hours`` and ``start_at`` off ``item`` and delegates to
    :func:`generate_due_times`. ``window_start`` overrides the anchor when the
    grid should begin somewhere other than the item's own ``start_at`` (e.g.
    re-aprazar from the start of the current shift); it defaults to ``start_at``.

    Args:
        item: a NursingPrescriptionItem (or any object exposing
            ``frequency_hours`` and ``start_at``).
        window_start: optional anchor override; defaults to ``item.start_at``.
        window_hours: length of the window in hours (default 24).

    Returns:
        The list of due datetimes (see :func:`generate_due_times`).
    """
    anchor = window_start if window_start is not None else item.start_at
    return generate_due_times(anchor, item.frequency_hours, window_hours=window_hours)
