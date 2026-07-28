"""
C3 — Centro Cirúrgico intra-op service: surgical times + safe-surgery checklist.

Intra-op writes on a :class:`SurgicalCase` go ONLY through this module (never raw
``serializer.save``) so a :class:`SurgicalTime` append and the case-status
advance move together inside one ``transaction.atomic`` under a row lock — exactly
like :mod:`apps.emr.services.surgery_scheduling` and :mod:`apps.emr.services.adt`
(atomic + ``select_for_update`` + raise ``ValidationError``; the viewset surfaces
that as HTTP 409).

Time → status transitions (the core C3 state machine)
-----------------------------------------------------
Each time event may only be recorded when the case is in the right status, and
three of the six events advance the status:

    event             required current status        → resulting status
    ─────────────────────────────────────────────────────────────────────
    sala_entrada      confirmada                      → em_sala
    anestesia_inicio  em_sala                         → (unchanged)
    anestesia_fim     em_sala / em_andamento          → (unchanged)
    incisao           em_sala                         → em_andamento
    fechamento        em_andamento                    → (unchanged)
    sala_saida        em_andamento                    → finalizada

Consequences of these gates (no extra bookkeeping needed):
  * A case in ``agendada`` / ``cancelada`` / ``finalizada`` can never accept a
    time (none of those is a required current status) — times are only recorded
    on a confirmed / in-room / in-progress case.
  * Events are implicitly ordered: ``incisao`` before the case is ``em_sala`` is
    rejected; ``sala_saida`` before ``incisao`` (still ``em_sala``) is rejected.
  * Recording the same status-advancing event twice is rejected — after the
    first ``sala_entrada`` the case is ``em_sala``, so a second ``sala_entrada``
    (which requires ``confirmada``) fails.

Safe-surgery checklist (OMS)
----------------------------
``confirm_checklist`` records the WHO checklist for one phase (sign_in / time_out
/ sign_out) exactly once — a ``(case, phase)`` is append-only (unique). We do NOT
hard-gate the time transitions on the checklist (e.g. we do not *require* sign_in
before ``anestesia_inicio``): the checklist is recorded as an independent safety
artifact, keeping the state machine simple and the two concerns decoupled. The
DB unique constraint + the explicit pre-check here reject a re-confirm as a
``ValidationError`` (→ 409) rather than a raw IntegrityError.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.emr.models import SurgicalCase, SurgicalChecklist, SurgicalTime

Status = SurgicalCase.Status
Event = SurgicalTime.Event

# event → (required current statuses, resulting status or None to keep current).
_TIME_RULES: dict[str, tuple[frozenset[str], str | None]] = {
    Event.SALA_ENTRADA: (frozenset({Status.CONFIRMADA}), Status.EM_SALA),
    Event.ANESTESIA_INICIO: (frozenset({Status.EM_SALA}), None),
    Event.ANESTESIA_FIM: (frozenset({Status.EM_SALA, Status.EM_ANDAMENTO}), None),
    Event.INCISAO: (frozenset({Status.EM_SALA}), Status.EM_ANDAMENTO),
    Event.FECHAMENTO: (frozenset({Status.EM_ANDAMENTO}), None),
    Event.SALA_SAIDA: (frozenset({Status.EM_ANDAMENTO}), Status.FINALIZADA),
}


@transaction.atomic
def record_time(
    case: SurgicalCase,
    event: str,
    *,
    at: Any | None = None,
    by: Any | None = None,
    notes: str = "",
) -> SurgicalCase:
    """Append a :class:`SurgicalTime` for ``event`` and advance the case status
    per :data:`_TIME_RULES` — atomically, under a lock on the case row.

    Raises ``ValidationError`` if ``event`` is unknown or the case's current
    status does not permit the event (out-of-order / illegal). Returns the
    (locked, possibly advanced) case.
    """
    rule = _TIME_RULES.get(event)
    if rule is None:
        raise ValidationError(f"Evento de tempo cirúrgico inválido: '{event}'.")
    required_statuses, next_status = rule

    locked = SurgicalCase.objects.select_for_update().get(pk=case.pk)
    if locked.status not in required_statuses:
        raise ValidationError(
            f"Não é possível registrar '{SurgicalTime.Event(event).label}' com o caso em "
            f"situação '{locked.get_status_display()}'."
        )

    SurgicalTime.objects.create(
        case=locked,
        event=event,
        recorded_at=at or timezone.now(),
        recorded_by=by,
        notes=notes,
    )

    if next_status is not None and locked.status != next_status:
        locked.status = next_status
        locked.save(update_fields=["status", "updated_at"])
    return locked


@transaction.atomic
def confirm_checklist(
    case: SurgicalCase,
    phase: str,
    items: dict | None,
    *,
    by: Any | None = None,
) -> SurgicalChecklist:
    """Confirm the safe-surgery checklist for ``phase`` (once). Raises
    ``ValidationError`` if the phase is already confirmed for this case.

    Locks the case row so concurrent confirms of the same phase serialize; the
    ``(case, phase)`` unique constraint is the DB-level backstop.
    """
    if phase not in SurgicalChecklist.Phase.values:
        raise ValidationError(f"Fase de checklist inválida: '{phase}'.")

    locked = SurgicalCase.objects.select_for_update().get(pk=case.pk)
    if SurgicalChecklist.objects.filter(case=locked, phase=phase).exists():
        raise ValidationError(
            f"Checklist da fase '{SurgicalChecklist.Phase(phase).label}' já confirmado."
        )
    return SurgicalChecklist.objects.create(
        case=locked,
        phase=phase,
        items=items or {},
        confirmed_at=timezone.now(),
        confirmed_by=by,
    )
