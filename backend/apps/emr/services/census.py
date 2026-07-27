"""
L3 — Censo / ocupação de leitos (read-only aggregation over the L1/L2 state).

These are pure read helpers over the physical bed structure (:class:`Bed` /
:class:`InpatientUnit`) and the active-admission set (:class:`Admission` with
``status=admitted``). No state is mutated here — occupancy is derived from the
bed ``status`` enum that :mod:`apps.emr.services.adt` keeps authoritative.

Denominator choice (occupancy_rate)
-----------------------------------
``occupancy_rate = occupied / operational_beds`` where **operational_beds** is the
count of beds whose status is NOT ``interditado`` and NOT ``bloqueado`` — i.e. beds
that could physically receive a patient (livre/ocupado/higienizacao/reservado).
Interditado (out of service) and bloqueado (administratively held) beds are removed
from the denominator so a ward that fences off beds is not penalised as "less
occupied". Rate is ``0.0`` when there are no operational beds.

LOS unit
--------
Length of stay is reported in **whole hours** (floor of
``timezone.now() - admission_datetime``). Whole hours (not days) because inpatient
turnover and NIR bed-management decisions are hour-grained; the frontend can format
to days when it wants a coarser view.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Count
from django.utils import timezone

from apps.emr.models import Admission, Bed, InpatientUnit

# Bed statuses removed from the occupancy denominator (not physically available).
_NON_OPERATIONAL_STATUSES = frozenset({Bed.Status.INTERDITADO, Bed.Status.BLOQUEADO})


def _los_hours(admission: Admission, *, now: Any | None = None) -> int:
    """Whole hours between the admission datetime and ``now`` (floored, min 0)."""
    now = now or timezone.now()
    delta = now - admission.admission_datetime
    return max(0, int(delta.total_seconds() // 3600))


def unit_occupancy(unit: InpatientUnit) -> dict[str, Any]:
    """Occupancy snapshot for a single inpatient ``unit``.

    Returns total beds, per-status counts, operational-bed count, occupied count
    and the occupancy_rate (see module docstring for the denominator definition).
    """
    counts: dict[str, int] = {value: 0 for value, _ in Bed.Status.choices}
    total = 0
    for entry in Bed.objects.filter(unit=unit).values("status").annotate(n=Count("id")):
        counts[entry["status"]] = entry["n"]
        total += entry["n"]

    non_operational = sum(counts[s] for s in _NON_OPERATIONAL_STATUSES)
    operational = total - non_operational
    occupied = counts[Bed.Status.OCUPADO]
    rate = (occupied / operational) if operational else 0.0

    return {
        "unit": {"id": unit.id, "code": unit.code, "name": unit.name},
        "total_beds": total,
        "status_counts": counts,
        "operational_beds": operational,
        "occupied": occupied,
        "occupancy_rate": rate,
    }


def all_unit_occupancy(*, facility: Any | None = None) -> list[dict[str, Any]]:
    """Occupancy snapshot for every unit (optionally scoped to ``facility``)."""
    qs = InpatientUnit.objects.all()
    if facility is not None:
        qs = qs.filter(facility_id=facility)
    return [unit_occupancy(u) for u in qs]


def census(*, unit: Any | None = None, now: Any | None = None) -> list[dict[str, Any]]:
    """Active-census list: one row per active (status=admitted) admission.

    Each row carries patient (id/name), current bed (id/identifier), its unit
    (id/code/name), the admission datetime, and LOS in whole hours. Optionally
    scoped to a single ``unit`` (matched via ``current_bed__unit``).
    """
    now = now or timezone.now()
    qs = (
        Admission.objects.filter(status=Admission.Status.ADMITTED, current_bed__isnull=False)
        .select_related("patient", "current_bed", "current_bed__unit")
        .order_by("current_bed__unit__code", "current_bed__identifier")
    )
    if unit is not None:
        qs = qs.filter(current_bed__unit=unit)

    rows: list[dict[str, Any]] = []
    for adm in qs:
        bed = adm.current_bed
        rows.append(
            {
                # Stringify ids so the client-facing contract matches every other
                # (serializer-based) endpoint — UUIDs render as strings over the
                # wire, and callers (incl. DRF ``resp.data`` in tests) get strings.
                "admission_id": str(adm.id),
                "patient": {"id": str(adm.patient_id), "name": adm.patient.full_name},
                "bed": {"id": str(bed.id), "identifier": bed.identifier},
                "unit": {
                    "id": str(bed.unit_id),
                    "code": bed.unit.code,
                    "name": bed.unit.name,
                },
                "admission_datetime": adm.admission_datetime,
                "los_hours": _los_hours(adm, now=now),
            }
        )
    return rows
