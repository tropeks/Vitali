"""
M2-S3-T4 — LabOrder → SP/SADT billing bridge.
============================================
When a laboratory order is finalized, generate one TISS **SP/SADT** guide billing
its items, reusing the existing ``TISSGuide`` / ``TISSGuideItem`` creation and
pricing it from the provider's active ``PriceTable`` (per TUSS code).

Bridge assumptions (documented — the LIS domain does not model everything TISS
needs, so the bridge fills the gaps honestly, never fabricating clinical data):

  * **Finalized** = ``LabOrder.status == COMPLETED`` (the LIS has no dedicated
    "approved" state; COMPLETED is the terminal, results-validated state).
  * **Encounter**: the guide requires one (``TISSGuide.encounter`` is PROTECT);
    ``LabOrder.encounter`` must be set. No encounter → the order is not billable.
  * **Provider + card**: taken from the patient's active ``PatientInsurance``
    (``provider_ans_code`` → ``InsuranceProvider.ans_code``; ``card_number`` →
    ``insured_card_number``). No active convênio matching a registered provider →
    not billable (a private/particular order is out of TISS scope).
  * **TUSS per item**: resolved by matching the ordered ``LabTest.code`` against a
    public ``core.TUSSCode.code`` (lab procedures are TUSS-coded). A test whose
    code is not a known TUSS is SKIPPED (it cannot be billed to a payer) rather
    than fabricating a code.
  * **Price**: the negotiated ``PriceTableItem.negotiated_value`` for that TUSS in
    the provider's active ``PriceTable``; ``0`` when no negotiated price exists
    (never invented).
  * **Idempotent**: at most one guide per lab order (DB-enforced by the
    ``uniq_tiss_guide_per_lab_order`` constraint). Re-running returns the
    existing guide.

``apps.billing → apps.emr`` coupling here is covered by the grandfathered
import-linter baseline edge.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.billing.models import (
    InsuranceProvider,
    PriceTable,
    PriceTableItem,
    TISSGuide,
    TISSGuideItem,
)
from apps.core.models import TUSSCode
from apps.emr.models import LabOrder, PatientInsurance


def _active_insurance(patient_id) -> PatientInsurance | None:
    return (
        PatientInsurance.objects.filter(patient_id=patient_id, is_active=True)
        .order_by("-created_at")
        .first()
    )


def _active_price_table(provider: InsuranceProvider, on: date) -> PriceTable | None:
    return (
        PriceTable.objects.filter(provider=provider, is_active=True, valid_from__lte=on)
        .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=on))
        .order_by("-valid_from")
        .first()
    )


def _unit_value(price_table: PriceTable | None, tuss: TUSSCode) -> Decimal:
    if price_table is None:
        return Decimal("0")
    item = PriceTableItem.objects.filter(table=price_table, tuss_code=tuss).first()
    return item.negotiated_value if item is not None else Decimal("0")


def generate_sadt_guide_for_lab_order(order: LabOrder) -> TISSGuide:
    """Generate (or return the existing) SP/SADT guide for a finalized LabOrder.

    Raises ``rest_framework.ValidationError`` when the order is not billable
    (not finalized, no encounter, or no active convênio). Idempotent: a second
    call returns the guide created by the first.
    """
    with transaction.atomic():
        order = LabOrder.objects.select_for_update().select_related("patient").get(pk=order.pk)

        existing = TISSGuide.objects.filter(lab_order=order).first()
        if existing is not None:
            return existing

        if order.status != LabOrder.Status.COMPLETED:
            raise ValidationError("Somente pedidos concluídos podem ser faturados.")
        if order.encounter_id is None:
            raise ValidationError("Pedido sem atendimento (encounter) não pode gerar guia.")

        insurance = _active_insurance(order.patient_id)
        if insurance is None:
            raise ValidationError("Paciente sem convênio ativo — pedido não faturável por TISS.")
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
            encounter_id=order.encounter_id,
            patient_id=order.patient_id,
            provider=provider,
            price_table=price_table,
            lab_order=order,
            status="draft",
            insured_card_number=insurance.card_number or "",
            competency=competency,
        )

        for item in order.items.select_related("test").all():
            code = (item.test.code or "").strip()
            if not code:
                continue
            tuss = TUSSCode.objects.filter(code=code, active=True).first()
            if tuss is None:
                # Not a payer-billable TUSS procedure — skip (never fabricate).
                continue
            TISSGuideItem.objects.create(
                guide=guide,
                tuss_code=tuss,
                description=item.test_name or item.test.name,
                quantity=Decimal("1"),
                unit_value=_unit_value(price_table, tuss),
            )

        # No ordered test resolved to a payer-billable TUSS procedure — there is
        # nothing to bill. Raise INSIDE the atomic block so the just-created guide
        # rolls back (keeping the "one guide per lab order" invariant and this
        # function idempotent: a later, billable re-run is not blocked by an empty
        # guide left behind here).
        if not guide.items.exists():
            raise ValidationError(
                "Pedido sem itens faturáveis: nenhum procedimento com código TUSS correspondente."
            )

        return guide
