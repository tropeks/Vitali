"""
S2 — Bridge de produção ambulatorial SUS (EncounterProcedure → BPA-I).
====================================================================
When a SUS competência is generated, sweep the establishment's ambulatorial
clinical capture for the competência month and materialise one
:class:`~apps.billing.sus_models.BpaIndividualizado` per SUS-coded procedure that
has a billable CNS. This is the SUS analogue of the TISS SP/SADT lab bridge
(:mod:`apps.billing.services.lab_order_billing`): the clinical domain
(``apps.emr``) never imports billing, so the bridge lives here and reads
``EncounterProcedure`` directly.

Contract (documented — the bridge fills gaps honestly, never fabricating data):

  * **Scope**: ``EncounterProcedure``s whose ``encounter.encounter_type ==
    "ambulatorial"``, whose ``encounter.encounter_date`` falls in the competência
    month (derived from ``SusCompetencia.competencia`` "AAAA-MM"), and that are
    **SUS-coded** (``sigtap`` set). Uncoded or non-ambulatorial captures are
    skipped (never fabricate a SIGTAP).
  * **CNS**: BPA-I is individualizado, so it needs the patient's CNS. A procedure
    whose patient has no CNS is skipped (it belongs in a BPA-C, entered manually).
  * **Valor**: ``(sigtap.valor_sa + sigtap.valor_sp) × quantity`` — pure Decimal
    arithmetic (SUS valoração never floats), the ambulatorial componentes.
  * **Idempotent**: each generated line links its origin ``encounter_procedure``;
    a re-run skips procedures already linked to a BPA-I in that competência (and a
    unique constraint backstops a concurrent double-run).
  * **Only aberta**: generation is rejected (``ValidationError`` → 409 at the
    view) on a fechada/exportada competência.

``apps.billing → apps.emr`` coupling here is the same grandfathered edge the lab
bridge uses.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.billing.sus_models import BpaIndividualizado, SusCompetencia
from apps.emr.models import EncounterProcedure


def _ambulatorial_valor(sigtap, quantidade: int) -> Decimal:
    """Valor SUS ambulatorial: ``(valor_sa + valor_sp) × quantidade`` (Decimal)."""
    sa = sigtap.valor_sa if sigtap.valor_sa is not None else Decimal("0")
    sp = sigtap.valor_sp if sigtap.valor_sp is not None else Decimal("0")
    return (sa + sp) * quantidade


def gerar_producao_ambulatorial(competencia: SusCompetencia, *, actor=None) -> dict:
    """Materialise BPA-I lines for a competência's ambulatorial SUS-coded capture.

    Atomic + idempotent. Raises ``django.core.exceptions.ValidationError`` (→ 409
    at the view) when the competência is not ``aberta``. Returns a summary
    ``{"bpa_i_count": int, "total_valor": Decimal}`` counting only lines created
    by THIS run (a re-run returns ``bpa_i_count == 0``).
    """
    with transaction.atomic():
        comp = SusCompetencia.objects.select_for_update().get(pk=competencia.pk)
        if comp.status != SusCompetencia.Status.ABERTA:
            raise ValidationError(
                f"Competência {comp.competencia} não está aberta "
                f"(status={comp.status}); geração de produção bloqueada."
            )

        # Procedures already turned into a BPA-I in this competência are skipped —
        # this is the idempotency mechanism (the unique constraint backstops it).
        already = set(
            BpaIndividualizado.objects.filter(
                competencia=comp, encounter_procedure__isnull=False
            ).values_list("encounter_procedure_id", flat=True)
        )

        qs = (
            EncounterProcedure.objects.select_related("encounter", "encounter__patient")
            .filter(
                encounter__encounter_type="ambulatorial",
                encounter__encounter_date__year=int(comp.competencia[:4]),
                encounter__encounter_date__month=int(comp.competencia[5:7]),
                sigtap__isnull=False,
            )
            .order_by("created_at")
        )

        created = 0
        total = Decimal("0")
        for ep in qs:
            if ep.id in already:
                continue
            patient = ep.encounter.patient
            cns = (patient.cns or "").strip()
            if not cns:
                # BPA-I needs a CNS; a patient-less/no-CNS capture belongs to BPA-C.
                continue

            sigtap = ep.sigtap
            if sigtap is None:  # guarded by the sigtap__isnull=False filter above
                continue
            quantidade = int(ep.quantity)
            valor = _ambulatorial_valor(sigtap, quantidade)
            executor = ep.performed_by
            BpaIndividualizado.objects.create(
                competencia=comp,
                sigtap=sigtap,
                cbo=executor.cbo if executor else None,
                patient=patient,
                cns=cns,
                professional=executor,
                quantidade=quantidade,
                valor=valor,
                encounter_procedure=ep,
            )
            created += 1
            total += valor

        return {"bpa_i_count": created, "total_valor": total}
