"""B9 — Medicamento dispensado vira linha de conta.

Último buraco da ponte clínico→financeiro do lado do consumo: material de centro
cirúrgico já era cobrado (``bill_surgical_materials_for_case``), mas medicamento
dispensado em enfermaria, emergência ou ambulatório saía do estoque e não virava
receita nenhuma. O remédio some da prateleira e ninguém cobra.

Duas peças tornaram isto possível, ambas de hoje:

* ``TUSSCode.anvisa_registro`` (B8) — o material sabia seu TUSS por
  ``SimproMaterial.tuss_code``; o medicamento não sabia nada. Agora o registro
  ANVISA (publicado pela ANS em 100% da tabela 20) resolve o código a cobrar;
* o catálogo ANVISA real, com 24.346 apresentações importadas.

Acoplamento por sinal, nunca por import: ``apps.billing -> apps.pharmacy`` é
proibido pelo import-linter, e o inverso também. O encontro é em
``core.dispensation_signals``, com payload primitivo — este módulo nunca vê um
objeto da farmácia.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from django.db import transaction
from django.dispatch import receiver

from apps.billing.models import InsuranceProvider, TISSGuide, TISSGuideItem
from apps.billing.services.lab_order_billing import (
    _active_insurance,
    _active_price_table,
    _unit_value,
)
from apps.core.dispensation_signals import dispensation_billable
from apps.core.terminology import tuss_for_anvisa_registro

logger = logging.getLogger(__name__)


@receiver(dispensation_billable, dispatch_uid="billing_bill_dispensation")
def bill_dispensation(sender, **kwargs):
    """Lança o medicamento dispensado na conta do atendimento.

    Silencioso e tolerante por desenho. Uma dispensação que não vira cobrança é
    o comportamento correto em vários casos legítimos — paciente particular, sem
    convênio cadastrado, medicamento sem TUSS correspondente — e **nenhum deles
    pode impedir o remédio de chegar ao paciente**. Cada saída registra em log
    para o motivo ser auditável em vez de virar mistério.
    """
    try:
        _bill(**kwargs)
    except Exception:
        logger.exception(
            "bill_dispensation: falha ao faturar a dispensação %s. "
            "A dispensação segue válida; a linha pode precisar de lançamento manual.",
            kwargs.get("source_id"),
        )


def _bill(
    *,
    encounter_id=None,
    patient_id=None,
    anvisa_registro: str = "",
    quantity: Decimal = Decimal("0"),
    description: str = "",
    source_id=None,
    **_extra,
):
    if encounter_id is None or source_id is None:
        return
    if quantity is None or Decimal(quantity) <= 0:
        return

    tuss = tuss_for_anvisa_registro(anvisa_registro)
    if tuss is None:
        logger.info(
            "bill_dispensation: sem TUSS para o registro ANVISA %r (dispensação %s) — "
            "medicamento não faturado.",
            anvisa_registro,
            source_id,
        )
        return

    with transaction.atomic():
        # Idempotência: reprocessar a mesma dispensação não cobra o remédio duas
        # vezes. Checado ANTES de mexer na guia.
        if TISSGuideItem.objects.filter(dispensation_source_id=source_id).exists():
            return

        insurance = _active_insurance(patient_id)
        if insurance is None:
            logger.info(
                "bill_dispensation: paciente %s sem convênio ativo — dispensação %s "
                "não faturável por TISS.",
                patient_id,
                source_id,
            )
            return
        provider = InsuranceProvider.objects.filter(ans_code=insurance.provider_ans_code).first()
        if provider is None:
            logger.info(
                "bill_dispensation: operadora ANS %s não cadastrada — dispensação %s não faturada.",
                insurance.provider_ans_code,
                source_id,
            )
            return

        from django.utils import timezone

        today = timezone.now().date()
        price_table = _active_price_table(provider, today)

        # Uma guia de medicamentos por atendimento: as dispensações do mesmo
        # encounter se acumulam nela em vez de gerar uma guia por remédio.
        guide = TISSGuide.objects.filter(
            encounter_id=encounter_id, guide_type="sadt", status="draft"
        ).first()
        if guide is None:
            guide = TISSGuide.objects.create(
                guide_type="sadt",
                encounter_id=encounter_id,
                patient_id=patient_id,
                provider=provider,
                price_table=price_table,
                status="draft",
                insured_card_number=insurance.card_number or "",
                competency=today.strftime("%Y-%m"),
            )

        TISSGuideItem.objects.create(
            guide=guide,
            tuss_code=tuss,
            description=(description or tuss.description or "")[:300],
            quantity=Decimal(quantity),
            unit_value=_unit_value(price_table, tuss),
            dispensation_source_id=source_id,
        )
