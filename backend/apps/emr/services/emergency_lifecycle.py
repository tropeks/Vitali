"""
E3 — Transições de ciclo do boletim de PS (chamar/atender → encerrar) + a ponte
de internação (internação → ADT).

Lifecycle transitions are driven ONLY through this module (never raw
serializer.save), mirroring :mod:`apps.emr.services.emergency_classify` /
:mod:`apps.emr.services.adt`: the boletim row is ``select_for_update``-locked so
concurrent transitions serialize, and every state move happens inside one
``transaction.atomic``. Illegal transitions raise
:class:`django.core.exceptions.ValidationError` — the viewset maps that to HTTP
409 (same shape as the ADT admit/discharge conflict handling).

Internação bridge
-----------------
When ``close`` is called with ``disposition == internacao`` AND a ``bed`` (+
admitting/attending professional), it calls :func:`apps.emr.services.adt.admit`
inside the SAME transaction to create the :class:`Admission` (linking the
boletim's ``encounter`` when present, source defaulting to ``emergencia``) and
stores the resulting admission FK on the boletim. An occupied-bed / ADT rejection
surfaces as ``ValidationError`` (→ 409) and rolls the whole close back. If NO bed
is supplied, the boletim still closes as ``internacao`` but ``admission`` stays
NULL (admite-se depois — bed assignment can happen later via the ADT surface).
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.emr.emergency_models import EmergencyEncounter
from apps.emr.services import adt as adt_service

_Status = EmergencyEncounter.Status
_Disposition = EmergencyEncounter.Disposition

# Statuses a boletim may be closed FROM. em_atendimento is the normal path; from
# classificado is allowed too so a quick disposition (ex.: evasão antes de ser
# chamado) does not force a spurious start-attendance first.
_CLOSABLE_STATUSES = frozenset({_Status.CLASSIFICADO, _Status.EM_ATENDIMENTO})


@transaction.atomic
def start_attendance(
    boletim: EmergencyEncounter,
    *,
    professional: Any | None = None,
    actor: Any | None = None,
) -> EmergencyEncounter:
    """Chamar/iniciar atendimento: classificado → em_atendimento.

    Rejects (``ValidationError`` → 409) any status other than ``classificado``: a
    boletim must be triaged before it can be attended, and one already in
    attendance / closed cannot be (re)started.

    ``professional`` is accepted (the profissional que assume o atendimento) but
    E3 has no attending-professional field on the boletim yet — it is reserved for
    a future encounter link; passing it is a no-op today.
    """
    locked = EmergencyEncounter.objects.select_for_update().get(pk=boletim.pk)
    if locked.status != _Status.CLASSIFICADO:
        raise ValidationError(
            f"Boletim não pode iniciar atendimento a partir de "
            f"'{locked.get_status_display()}' (requer 'Classificado')."
        )
    locked.status = _Status.EM_ATENDIMENTO
    locked.save(update_fields=["status", "updated_at"])
    return locked


@transaction.atomic
def close(
    boletim: EmergencyEncounter,
    *,
    disposition: str,
    actor: Any | None = None,
    bed: Any | None = None,
    admitting_professional: Any | None = None,
    attending_professional: Any | None = None,
    admission_source: str | None = None,
    admission_datetime: Any | None = None,
    reason: str = "",
) -> EmergencyEncounter:
    """Encerrar o boletim: → encerrado + grava ``disposition``.

    Allowed from ``em_atendimento`` (fluxo normal) and from ``classificado``
    (desfechos rápidos, ex.: evasão). Any other status → ``ValidationError`` (409).

    Internação bridge: quando ``disposition == internacao`` e um ``bed`` é
    informado, chama :func:`apps.emr.services.adt.admit` na MESMA transação
    (source default ``emergencia``, encounter do boletim quando houver) e grava a
    Admission em ``boletim.admission``. Sem leito, encerra como internação com
    ``admission`` NULL (admite depois). Leito ocupado / erro ADT → 409.
    """
    locked = EmergencyEncounter.objects.select_for_update().get(pk=boletim.pk)
    if locked.status not in _CLOSABLE_STATUSES:
        raise ValidationError(
            f"Boletim não pode ser encerrado a partir de '{locked.get_status_display()}'."
        )

    admission = None
    if disposition == _Disposition.INTERNACAO and bed is not None:
        # adt.admit raises ValidationError on occupied/indisponível bed — it
        # propagates out (rolling back this close) and the view maps it to 409.
        from apps.emr.models import Admission

        admission = adt_service.admit(
            patient=locked.patient,
            bed=bed,
            admitting_professional=admitting_professional,
            attending_professional=attending_professional,
            admission_source=admission_source or Admission.AdmissionSource.EMERGENCIA,
            admission_datetime=admission_datetime,
            encounter=locked.encounter,
            actor=actor,
            reason=reason,
        )

    locked.status = _Status.ENCERRADO
    locked.disposition = disposition
    locked.admission = admission
    locked.save(update_fields=["status", "disposition", "admission", "updated_at"])
    return locked
