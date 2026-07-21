# mypy: ignore-errors
"""
Slot generation service — get_available_slots(professional, date_range).

Reads ScheduleConfig to understand working hours, generates all possible slots
for the given date range, then subtracts already-booked appointments.

Returns: dict[date_str, list[TimeSlot]]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TimeSlot:
    start: datetime
    end: datetime

    @property
    def label(self) -> str:
        return self.start.strftime("%H:%M")

    @property
    def start_iso(self) -> str:
        return self.start.isoformat()

    @property
    def end_iso(self) -> str:
        return self.end.isoformat()


def get_available_slots(
    professional,
    start_date: date | None = None,
    days_ahead: int = 7,
) -> dict[str, list[TimeSlot]]:
    """
    Return available booking slots for `professional` over the next `days_ahead` working days.

    Args:
        professional: emr.Professional instance
        start_date: Start date (defaults to today)
        days_ahead: How many calendar days to look ahead (default 7)

    Returns:
        dict mapping "YYYY-MM-DD" to list of available TimeSlot objects
    """
    from apps.emr.models import Appointment, ScheduleConfig

    try:
        config: ScheduleConfig = professional.schedule_config
    except ScheduleConfig.DoesNotExist:
        logger.warning(
            "Professional %s has no ScheduleConfig — returning no slots", professional.pk
        )
        return {}

    if not config.is_active:
        return {}

    if start_date is None:
        start_date = timezone.now().date()

    end_date = start_date + timedelta(days=days_ahead)

    # Load booked appointments for the entire range in one query
    booked = list(
        Appointment.objects.filter(
            professional=professional,
            status__in=["scheduled", "confirmed", "waiting", "in_progress"],
            start_time__date__gte=start_date,
            start_time__date__lt=end_date,
        ).values("start_time", "end_time")
    )

    working_days: list[int] = config.working_days  # e.g. [0,1,2,3,4] (Mon=0)
    duration = timedelta(minutes=config.slot_duration_minutes)
    result: dict[str, list[TimeSlot]] = {}

    current = start_date
    while current < end_date:
        if current.weekday() in working_days:
            slots = _generate_day_slots(
                day=current,
                work_start=config.working_hours_start,
                work_end=config.working_hours_end,
                lunch_start=config.lunch_start,
                lunch_end=config.lunch_end,
                duration=duration,
            )
            # Filter out booked slots
            available = [slot for slot in slots if not _overlaps_any(slot, booked)]
            if available:
                result[current.isoformat()] = available

        current += timedelta(days=1)

    return result


def count_slots_for_config(config, start_date: date, end_date: date) -> int:
    """
    Gross bookable-slot capacity a ScheduleConfig generates in [start_date, end_date] inclusive.

    Unlike ``get_available_slots`` this ignores existing bookings — it returns the total
    number of slots the agenda *offers*, which is the denominator for fill-rate / occupancy
    metrics. Returns 0 for an inactive config or one with no working days.

    Args:
        config: emr.ScheduleConfig instance
        start_date: first day to count (inclusive)
        end_date: last day to count (inclusive)
    """
    if not config.is_active:
        return 0

    working_days: list[int] = config.working_days or []
    if not working_days or end_date < start_date:
        return 0

    duration = timedelta(minutes=config.slot_duration_minutes)
    total = 0
    current = start_date
    while current <= end_date:
        if current.weekday() in working_days:
            total += len(
                _generate_day_slots(
                    day=current,
                    work_start=config.working_hours_start,
                    work_end=config.working_hours_end,
                    lunch_start=config.lunch_start,
                    lunch_end=config.lunch_end,
                    duration=duration,
                )
            )
        current += timedelta(days=1)

    return total


def _to_time(t) -> time:
    """Coerce str '08:00' or datetime.time to datetime.time."""
    if isinstance(t, str):
        parts = t.split(":")
        return time(int(parts[0]), int(parts[1]))
    return t


def _generate_day_slots(
    day: date,
    work_start,
    work_end,
    lunch_start,
    lunch_end,
    duration: timedelta,
) -> list[TimeSlot]:
    """Generate all possible slots within working hours, excluding lunch."""
    work_start = _to_time(work_start)
    work_end = _to_time(work_end)
    if lunch_start:
        lunch_start = _to_time(lunch_start)
    if lunch_end:
        lunch_end = _to_time(lunch_end)

    slots = []
    cursor = datetime.combine(day, work_start)
    day_end = datetime.combine(day, work_end)

    # Make timezone-aware if needed
    try:
        from django.utils.timezone import is_naive, make_aware

        if is_naive(cursor):
            cursor = make_aware(cursor)
            day_end = make_aware(day_end)
    except Exception:
        pass

    while cursor + duration <= day_end:
        slot_end = cursor + duration
        if lunch_start and lunch_end:
            lunch_s = datetime.combine(day, lunch_start)
            lunch_e = datetime.combine(day, lunch_end)
            try:
                from django.utils.timezone import is_naive, make_aware

                if is_naive(lunch_s):
                    lunch_s = make_aware(lunch_s)
                    lunch_e = make_aware(lunch_e)
            except Exception:
                pass
            # Skip slots that overlap with lunch
            if not (slot_end <= lunch_s or cursor >= lunch_e):
                cursor += duration
                continue
        slots.append(TimeSlot(start=cursor, end=slot_end))
        cursor += duration

    return slots


def _overlaps_any(slot: TimeSlot, booked: list[dict]) -> bool:
    for appt in booked:
        if slot.start < appt["end_time"] and slot.end > appt["start_time"]:
            return True
    return False
