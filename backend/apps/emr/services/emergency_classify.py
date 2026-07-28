"""
E2 — Classificação de risco (triagem Manchester): the append-only classify op.

Classification is driven ONLY through this module (never raw serializer.save) so
the copied acuity snapshot, the append-only :class:`RiskClassification` row, and
the boletim's ``status`` advance together inside one ``transaction.atomic``.

Contract for E3 (queue/SLA + disposition):
- ``classify`` appends a NEW RiskClassification (re-triagem never mutates prior
  rows) and advances the boletim aguardando_classificacao → classificado. Re-
  classifying an already-classificado boletim keeps ``classificado`` (idempotent)
  and just appends another record — the ``current_classification`` becomes the
  latest. ``acuity_level`` + ``target_minutes`` are copied from the chosen
  discriminator's catalog row so history is stable across catalog changes.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction

from apps.core.manchester_catalog_models import acuity_target_minutes
from apps.emr.emergency_models import EmergencyEncounter, RiskClassification


@transaction.atomic
def classify(
    boletim: EmergencyEncounter,
    discriminator: Any,
    *,
    vitals: Any | None = None,
    by: Any | None = None,
    notes: str = "",
) -> RiskClassification:
    """Classify ``boletim`` with ``discriminator``: append a RiskClassification
    (acuity + target copied from the discriminator's catalog row) and advance the
    boletim status to ``classificado`` — atomically.

    Re-classifying is a first-class re-triagem: a new row is appended and the
    status stays ``classificado`` (never mutating prior classifications).
    """
    # Lock the boletim row to serialize concurrent classifications.
    locked = EmergencyEncounter.objects.select_for_update().get(pk=boletim.pk)

    flowchart = discriminator.flowchart
    acuity_level = discriminator.acuity_level
    target = acuity_target_minutes(acuity_level)

    classification = RiskClassification.objects.create(
        boletim=locked,
        flowchart=flowchart,
        discriminator=discriminator,
        acuity_level=acuity_level,
        target_minutes=target,
        vitals=vitals,
        classified_by=by,
        notes=notes,
    )

    # Advance aguardando_classificacao → classificado (idempotent for re-triagem;
    # em_atendimento/encerrado are E3-driven and must not be regressed here).
    if locked.status == EmergencyEncounter.Status.AGUARDANDO_CLASSIFICACAO:
        locked.status = EmergencyEncounter.Status.CLASSIFICADO
        locked.save(update_fields=["status", "updated_at"])

    return classification
