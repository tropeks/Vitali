"""
E3 — Fila por gravidade + painel do PS (board) da Emergência.

The acuity-ordered PS queue of ACTIVE boletins and the PS panel summary (board).
Read-only projections over :class:`~apps.emr.emergency_models.EmergencyEncounter`
+ its latest :class:`~apps.emr.emergency_models.RiskClassification`
(``current_classification``). No state is mutated here — lifecycle transitions
(start_attendance / close + the internação bridge) live in
:mod:`apps.emr.services.emergency_lifecycle`.

Ordering (the triage priority contract E4's board renders):

1. **Unclassified first** — ``aguardando_classificacao`` boletins precisam triar,
   so they head the queue regardless of arrival.
2. then by **acuity rank** (vermelho → azul, via ``ACUITY_RANK``);
3. then by **arrival_at** (mais antigo primeiro) — the fair tiebreak.

``waited_minutes`` = now − arrival_at; ``target_minutes`` copied from the current
classification (None while unclassified); ``overdue`` = classified AND
waited_minutes > target_minutes (an unclassified boletim is never "overdue" — it
has no SLA yet).

``facility`` is accepted for forward-compatibility (E4) but is currently a no-op:
the E3 ``EmergencyEncounter`` model carries no facility FK (nor does its optional
``Encounter``), and data is already isolated per tenant schema. When E4 adds a
facility link, wire the filter here — the signature is stable.
"""

from __future__ import annotations

from typing import Any

from django.utils import timezone

from apps.core.manchester_catalog_models import ACUITY_RANK, AcuityLevel
from apps.emr.emergency_models import EmergencyEncounter

# The boletim statuses that belong on the live PS queue (encerrado excluded).
ACTIVE_STATUSES = (
    EmergencyEncounter.Status.AGUARDANDO_CLASSIFICACAO,
    EmergencyEncounter.Status.CLASSIFICADO,
    EmergencyEncounter.Status.EM_ATENDIMENTO,
)


def _row(boletim: EmergencyEncounter, *, now: Any) -> dict[str, Any]:
    """Project one boletim into a queue row (computed SLA fields included)."""
    unclassified = boletim.status == EmergencyEncounter.Status.AGUARDANDO_CLASSIFICACAO
    current = boletim.current_classification

    waited_minutes = int((now - boletim.arrival_at).total_seconds() // 60)
    acuity_level = current.acuity_level if current else None
    target_minutes = current.target_minutes if current else None
    overdue = target_minutes is not None and not unclassified and waited_minutes > target_minutes

    return {
        "boletim_id": boletim.id,
        "patient_id": boletim.patient_id,
        "patient_name": boletim.patient.full_name,
        "status": boletim.status,
        "mode_of_arrival": boletim.mode_of_arrival,
        "chief_complaint": boletim.chief_complaint,
        "arrival_at": boletim.arrival_at,
        "waited_minutes": waited_minutes,
        "acuity_level": acuity_level,
        "target_minutes": target_minutes,
        "overdue": overdue,
    }


def _sort_key(row: dict[str, Any]) -> tuple:
    """Unclassified first, then acuity rank (vermelho→azul), then arrival_at asc."""
    unclassified = row["status"] == EmergencyEncounter.Status.AGUARDANDO_CLASSIFICACAO
    # Group 0 = unclassified (must triage → head of queue); group 1 = classified.
    group = 0 if unclassified else 1
    rank = ACUITY_RANK.get(row["acuity_level"], 0) if not unclassified else 0
    return (group, rank, row["arrival_at"])


def queue(*, facility: Any | None = None, now: Any | None = None) -> list[dict[str, Any]]:
    """The acuity-ordered PS queue of ACTIVE boletins.

    Returns queue rows (see :func:`_row`) ordered unclassified-first, then by
    acuity rank (vermelho→azul), then by arrival_at (oldest first). ``now``
    defaults to :func:`django.utils.timezone.now` (runtime now). ``facility`` is
    accepted but currently a no-op (see module docstring).
    """
    now = now or timezone.now()

    qs = (
        EmergencyEncounter.objects.filter(status__in=ACTIVE_STATUSES)
        .select_related("patient")
        .prefetch_related("classifications")
    )
    rows = [_row(b, now=now) for b in qs]
    rows.sort(key=_sort_key)
    return rows


def board(*, facility: Any | None = None) -> dict[str, Any]:
    """The PS panel summary: the queue + counts by acuity level + overdue count.

    ``counts`` always carries all five Manchester levels (0-filled); it counts the
    classified boletins on the queue by their current acuity. ``unclassified`` and
    ``total`` round out the panel header. Uses runtime now.
    """
    rows = queue(facility=facility)

    counts = {level.value: 0 for level in AcuityLevel}
    overdue = 0
    unclassified = 0
    for row in rows:
        if row["acuity_level"] is not None:
            counts[row["acuity_level"]] += 1
        if row["status"] == EmergencyEncounter.Status.AGUARDANDO_CLASSIFICACAO:
            unclassified += 1
        if row["overdue"]:
            overdue += 1

    return {
        "queue": rows,
        "counts": counts,
        "overdue": overdue,
        "unclassified": unclassified,
        "total": len(rows),
    }


def next_patient(*, facility: Any | None = None) -> dict[str, Any] | None:
    """The first callable boletim for attendance (highest-priority classificado).

    Triage ≠ attendance: ``aguardando_classificacao`` boletins are skipped (they
    must be triaged first, not called to attendance), and ``em_atendimento`` ones
    are already being seen. So the next callable row is the first ``classificado``
    boletim in queue order (already acuity-then-arrival sorted). Returns ``None``
    when nothing is callable.
    """
    for row in queue(facility=facility):
        if row["status"] == EmergencyEncounter.Status.CLASSIFICADO:
            return row
    return None
