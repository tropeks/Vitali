"""
B1 — SurgicalCase → SP/SADT billing bridge.
===========================================
When a surgical case is FINALIZED (executada), generate one TISS **SP/SADT** guide
billing its planned procedures, pricing them from the provider's active
``PriceTable`` (per TUSS code). This closes the clínico→financeiro loop for the
Centro Cirúrgico, mirroring the LabOrder bridge (``lab_order_billing``).

Bridge assumptions (documented — the OR domain does not model everything TISS
needs, so the bridge fills the gaps honestly, never fabricating clinical data):

  * **Finalized** = ``SurgicalCase.status == FINALIZADA`` (the terminal, executed
    state — the surgery actually happened). Any other status is not billable.
  * **Encounter**: the guide requires one (``TISSGuide.encounter`` is PROTECT);
    ``SurgicalCase.encounter`` must be set. A surgery with no encounter is not
    billable — never fabricate an encounter.
  * **Provider + card**: taken from the patient's active ``PatientInsurance``
    (``provider_ans_code`` → ``InsuranceProvider.ans_code``; ``card_number`` →
    ``insured_card_number``). No active convênio matching a registered provider →
    not billable (a private/particular surgery is out of TISS scope).
  * **TUSS per item**: each ``SurgicalProcedure`` already carries a
    ``core.TUSSCode`` FK — its ``quantity`` becomes the guide line quantity.
  * **Price**: the negotiated ``PriceTableItem.negotiated_value`` for that TUSS in
    the provider's active ``PriceTable``; ``0`` when no negotiated price exists
    (never invented).
  * **Idempotent**: at most one guide per surgical case (DB-enforced by the
    ``uniq_tiss_guide_per_surgical_case`` constraint). Re-running returns the
    existing guide.

The insurance / price-table / unit-value resolution helpers are shared verbatim
with the LabOrder bridge (``_active_insurance`` / ``_active_price_table`` /
``_unit_value``) — imported rather than duplicated so the two bridges price
identically and can never drift.

``apps.billing → apps.emr`` coupling here is covered by the grandfathered
import-linter baseline edge (already used by the LabOrder bridge).
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.billing.models import InsuranceProvider, TISSGuide, TISSGuideItem
from apps.billing.services.lab_order_billing import (
    _active_insurance,
    _active_price_table,
    _unit_value,
)
from apps.emr.models import SurgicalCase


def generate_sadt_guide_for_surgical_case(case: SurgicalCase) -> TISSGuide:
    """Generate (or return the existing) SP/SADT guide for a finalized SurgicalCase.

    Raises ``rest_framework.ValidationError`` when the case is not billable (not
    finalized, no encounter, or no active convênio). Idempotent: a second call
    returns the guide created by the first.
    """
    with transaction.atomic():
        case = SurgicalCase.objects.select_for_update().select_related("patient").get(pk=case.pk)

        existing = TISSGuide.objects.filter(surgical_case=case).first()
        if existing is not None:
            return existing

        if case.status != SurgicalCase.Status.FINALIZADA:
            raise ValidationError("Somente cirurgias finalizadas podem ser faturadas.")
        if case.encounter_id is None:
            raise ValidationError("Cirurgia sem atendimento (encounter) não pode gerar guia.")

        insurance = _active_insurance(case.patient_id)
        if insurance is None:
            raise ValidationError("Paciente sem convênio ativo — cirurgia não faturável por TISS.")
        provider = InsuranceProvider.objects.filter(ans_code=insurance.provider_ans_code).first()
        if provider is None:
            raise ValidationError(
                f"Operadora ANS {insurance.provider_ans_code} não cadastrada em faturamento."
            )

        today = timezone.now().date()
        price_table = _active_price_table(provider, today)
        competency = today.strftime("%Y-%m")

        guide = TISSGuide.objects.create(
            guide_type="sadt",
            encounter_id=case.encounter_id,
            patient_id=case.patient_id,
            provider=provider,
            price_table=price_table,
            surgical_case=case,
            status="draft",
            insured_card_number=insurance.card_number or "",
            competency=competency,
        )

        for proc in case.procedures.select_related("tuss_code").all():
            tuss = proc.tuss_code
            if tuss is None:
                continue
            TISSGuideItem.objects.create(
                guide=guide,
                tuss_code=tuss,
                description=tuss.description or proc.tuss_code_value,
                quantity=Decimal(proc.quantity),
                unit_value=_unit_value(price_table, tuss),
            )

        # No procedure resolved to a billable TUSS line — there is nothing to bill.
        # Raise INSIDE the atomic block so the just-created guide rolls back
        # (keeping the "one guide per case" invariant and this function idempotent:
        # a later, billable re-run is not blocked by an empty guide left behind).
        if not guide.items.exists():
            raise ValidationError(
                "Cirurgia sem procedimentos faturáveis: nenhum procedimento com código TUSS."
            )

        return guide
