"""Read-side bridge: the duty roster constrains emr appointment availability.

Registered at ``HRConfig.ready()`` into the emr availability hook registry
(``emr.services.scheduling.register_availability_hook``). The dependency arrow is
one-way — hr imports emr, never the reverse (see the import-linter baseline).

Semantics (backward compatible with pre-roster scheduling):
  * A professional with NO roster slot on the interval's day is unconstrained by
    the roster — availability falls through to the weekly grid / exceptions.
  * A professional WITH at least one slot that day is available only inside a slot
    whose ``[start_time, end_time]`` window covers the requested interval.
"""

from __future__ import annotations

from django.utils import timezone


def roster_availability_hook(professional, start, end) -> bool:
    """Availability predicate driven by the professional's duty roster."""
    from apps.hr.models import RosterSlot

    start_local = timezone.localtime(start) if timezone.is_aware(start) else start
    end_local = timezone.localtime(end) if timezone.is_aware(end) else end
    day = start_local.date()

    slots = list(
        RosterSlot.objects.filter(professional=professional, date=day, roster__active=True)
    )
    if not slots:
        return True  # roster does not constrain this professional/day

    start_t = start_local.time()
    end_t = end_local.time()
    return any(slot.start_time <= start_t and slot.end_time >= end_t for slot in slots)
