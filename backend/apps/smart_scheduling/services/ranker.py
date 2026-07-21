"""
Phase 3 Smart Scheduling — rule-based slot ranker.

The ranker enumerates the candidate slots a professional has open in a
date window, then scores each one against a small bag of explicit signals:

- **Clinical-time score** — mid-morning (9-11) and mid-afternoon (14-16)
  are the most-attended bands across Brazilian primary-care research;
  early morning + end-of-day score lower. Pure heuristic, no ML.
- **Professional gap-fill score** — slots that fill an existing gap in
  the schedule (adjacent to an existing appointment on the same day)
  score higher; isolated mid-day openings score lowest. Encourages tight
  schedules rather than scattered ones.
- **Patient attendance score** — if the patient has historical
  appointments at this same hour-of-day, they are more likely to attend
  again. Computed from completed/in_progress appointments.

Each signal is normalised to [0, 1] and combined via a weighted sum; the
weights are tunable. The intentional invariant is that **the same
(patient, professional, slot) tuple always produces the same score** —
no randomness, no time-of-day drift. That makes the ranker easy to
unit-test and audit, and gives a clean swap-in point for a smarter
model later (replace `score_slot` keeping the input/output shape).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from django.utils import timezone

from apps.emr.models import Appointment, ScheduleConfig

# Same signal weighting as a "balanced" baseline. A future tuning pass
# (with real piloto data) can recalibrate these without touching callers.
DEFAULT_WEIGHTS = {
    "clinical_time": 0.4,
    "gap_fill": 0.35,
    "patient_history": 0.25,
}

# Hour-of-day → clinical preference score (0..1). Anchored on common
# Brazilian primary-care attendance curves; not ML, not a fit to any
# specific clinic.
_HOUR_SCORE = {
    7: 0.55,
    8: 0.65,
    9: 0.90,
    10: 1.00,
    11: 0.95,
    12: 0.30,  # lunch window
    13: 0.45,
    14: 0.85,
    15: 0.95,
    16: 0.90,
    17: 0.70,
    18: 0.40,
}


@dataclass(frozen=True)
class SuggestedSlot:
    start: datetime
    end: datetime
    professional_id: str
    score: float
    components: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "professional_id": self.professional_id,
            "score": round(self.score, 4),
            "components": {k: round(v, 4) for k, v in self.components.items()},
        }


def suggest_slots(
    *,
    professional,
    patient=None,
    from_date: date,
    to_date: date,
    limit: int = 5,
    weights: dict[str, float] | None = None,
) -> list[SuggestedSlot]:
    """
    Return up to `limit` ranked candidate slots for the professional in the
    [from_date, to_date] window. Slots already taken by an Appointment are
    excluded.
    """
    if from_date > to_date:
        raise ValueError("from_date must be <= to_date.")
    if limit <= 0:
        raise ValueError("limit must be positive.")
    weights = {**DEFAULT_WEIGHTS, **(weights or {})}

    try:
        config: ScheduleConfig = professional.schedule_config
    except ScheduleConfig.DoesNotExist:
        return []

    # A deactivated schedule (e.g. a terminated employee — F-15) yields no slots,
    # mirroring apps.whatsapp.slot_service so the professional is fully removed
    # from the booking agenda regardless of entry point.
    if not config.is_active:
        return []

    candidate_slots = list(_enumerate_slots(config, from_date, to_date))
    if not candidate_slots:
        return []

    appts_by_day = _appointments_in_window(professional, from_date, to_date)
    patient_hour_counts = _patient_hour_counts(patient) if patient else {}

    scored: list[SuggestedSlot] = []
    for start, end in candidate_slots:
        if _slot_taken(start, end, appts_by_day):
            continue
        components = {
            "clinical_time": _clinical_time_score(start),
            "gap_fill": _gap_fill_score(start, appts_by_day),
            "patient_history": _patient_history_score(start, patient_hour_counts),
        }
        score = sum(weights[k] * components[k] for k in components)
        scored.append(
            SuggestedSlot(
                start=start,
                end=end,
                professional_id=str(professional.pk),
                score=score,
                components=components,
            )
        )

    scored.sort(key=lambda s: (-s.score, s.start))
    return scored[:limit]


# ─── Internals ────────────────────────────────────────────────────────────────


def _enumerate_slots(config: ScheduleConfig, from_date: date, to_date: date):
    working_days = set(config.working_days or [])
    duration = timedelta(minutes=int(config.slot_duration_minutes or 30))
    day = from_date
    while day <= to_date:
        weekday = day.strftime("%A").lower()
        if weekday in working_days:
            start_dt = _combine(day, config.working_hours_start)
            end_of_day = _combine(day, config.working_hours_end)
            lunch_start = _combine(day, config.lunch_start) if config.lunch_start else None
            lunch_end = _combine(day, config.lunch_end) if config.lunch_end else None
            current = start_dt
            while current + duration <= end_of_day:
                slot_end = current + duration
                # Skip slots overlapping lunch window
                if not (
                    lunch_start and lunch_end and current < lunch_end and slot_end > lunch_start
                ):
                    yield (current, slot_end)
                current = slot_end
        day += timedelta(days=1)


def _combine(d: date, t: time) -> datetime:
    naive = datetime.combine(d, t)
    return timezone.make_aware(naive, timezone.get_current_timezone())


def _appointments_in_window(professional, from_date: date, to_date: date) -> dict:
    qs = Appointment.objects.filter(
        professional=professional,
        start_time__date__gte=from_date,
        start_time__date__lte=to_date,
    ).exclude(status="cancelled")
    by_day: dict[date, list[tuple[datetime, datetime]]] = {}
    for appt in qs:
        by_day.setdefault(appt.start_time.date(), []).append((appt.start_time, appt.end_time))
    return by_day


def _slot_taken(start: datetime, end: datetime, appts_by_day: dict) -> bool:
    for a_start, a_end in appts_by_day.get(start.date(), []):
        if start < a_end and end > a_start:
            return True
    return False


def _clinical_time_score(slot_start: datetime) -> float:
    return _HOUR_SCORE.get(slot_start.hour, 0.30)


def _gap_fill_score(slot_start: datetime, appts_by_day: dict) -> float:
    """Slots adjacent to an existing appointment on the same day score higher."""
    same_day = appts_by_day.get(slot_start.date(), [])
    if not same_day:
        return 0.4  # Empty day — neutral
    slot_end = slot_start + timedelta(minutes=30)
    for a_start, a_end in same_day:
        # adjacent (touching) or 1-slot-away gap
        if abs((a_end - slot_start).total_seconds()) <= 900:
            return 1.0
        if abs((slot_end - a_start).total_seconds()) <= 900:
            return 1.0
        if a_end <= slot_start <= a_end + timedelta(minutes=60):
            return 0.75
        if slot_end <= a_start <= slot_end + timedelta(minutes=60):
            return 0.75
    return 0.5


def _patient_hour_counts(patient) -> dict[int, int]:
    """
    Count the patient's previously-attended appointments by hour-of-day in
    the platform's *local* timezone. Slot ranking matches against the
    local-time slot, and Django returns UTC datetimes from the DB when
    `USE_TZ=True`, so we must convert before reading `.hour` — otherwise
    a 15:00 (local, UTC-3) appointment lands in the bucket for 18:00.
    """
    counts: dict[int, int] = {}
    local_tz = timezone.get_current_timezone()
    qs = Appointment.objects.filter(
        patient=patient, status__in=["completed", "in_progress"]
    ).values_list("start_time", flat=True)
    for ts in qs:
        local_hour = ts.astimezone(local_tz).hour
        counts[local_hour] = counts.get(local_hour, 0) + 1
    return counts


def _patient_history_score(slot_start: datetime, hour_counts: dict[int, int]) -> float:
    if not hour_counts:
        return 0.5  # No history — neutral
    total = sum(hour_counts.values())
    matched = hour_counts.get(slot_start.hour, 0)
    # Normalise: a hour with all the patient's history scores 1; one with
    # none scores 0; in between, proportional.
    return matched / total if total else 0.5
