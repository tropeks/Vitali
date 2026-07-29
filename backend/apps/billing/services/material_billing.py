"""
B4a — Material/OPME: resolução de preço negociado.
==================================================
Helper de precificação de material, espelho de ``_unit_value`` em
:mod:`apps.billing.services.lab_order_billing` (que resolve o preço de um TUSS
numa ``PriceTable``): dado uma ``PriceTable`` do convênio e um item Simpro,
devolve o ``MaterialPriceItem.negotiated_value`` negociado, ou ``Decimal("0")``
quando não há preço negociado (nunca inventa valor).

B4b — bridge de consumo de material de sala → faturamento/glosa
===============================================================
:func:`bill_surgical_materials_for_case` consome os ``SurgicalMaterial`` de um
caso cirúrgico FINALIZADO e materializa cada material CONSUMIDO na guia SP/SADT
da cirurgia (a mesma gerada pelo B1, idempotente):

  * material com ``simpro`` tabelado (Simpro + TUSS + preço negociado > 0) vira
    um ``TISSGuideItem`` precificado na guia — idempotente via o back-link
    ``TISSGuideItem.surgical_material``;
  * material sem Simpro, sem TUSS, ou sem preço negociado, vira um
    ``GlosaSafetyAlert`` NOT_IN_TABLE/ADVISE (custo não faturável, risco de
    glosa) — idempotente via o ``update_or_create`` na unique_together do alerta.

Nunca fabrica preço nem procedimento; a direção de import é billing → emr
(permitida — grandfathered, como o resto do surgery bridge).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.billing.material_models import MaterialPriceItem
from apps.billing.models import GlosaSafetyAlert, PriceTable, TISSGuide, TISSGuideItem
from apps.billing.services.surgery_billing import generate_sadt_guide_for_surgical_case
from apps.core.simpro_models import SimproMaterial
from apps.emr.models import SurgicalCase


def material_unit_value(price_table: PriceTable | None, simpro: SimproMaterial) -> Decimal:
    """Valor negociado do material ``simpro`` na ``price_table``.

    Devolve ``MaterialPriceItem.negotiated_value`` para (``price_table``,
    ``simpro``), ou ``Decimal("0")`` quando não há tabela ou não há preço
    negociado para o material — nunca fabrica valor (espelha ``_unit_value`` de
    ``lab_order_billing``).
    """
    if price_table is None:
        return Decimal("0")
    item = MaterialPriceItem.objects.filter(table=price_table, simpro=simpro).first()
    return item.negotiated_value if item is not None else Decimal("0")


@dataclass
class MaterialBillingResult:
    """Resumo do bridge de faturamento de material de sala (B4b).

    ``guide_id`` é a guia SP/SADT da cirurgia onde os itens entraram;
    ``items_created`` conta os ``TISSGuideItem`` de material criados nesta
    execução; ``items_existing`` os já existentes (re-run idempotente);
    ``alerts`` os ``GlosaSafetyAlert`` NOT_IN_TABLE emitidos/atualizados.
    """

    guide_id: object
    items_created: int = 0
    items_existing: int = 0
    alerts: int = 0
    alert_ids: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "guide_id": str(self.guide_id),
            "items_created": self.items_created,
            "items_existing": self.items_existing,
            "alerts": self.alerts,
        }


def bill_surgical_materials_for_case(case: SurgicalCase) -> MaterialBillingResult:
    """Materializa os materiais consumidos de um caso cirúrgico na guia SP/SADT.

    Pré-condição: ``case.status == FINALIZADA`` (senão ``ValidationError``). Garante
    a guia SADT da cirurgia (``generate_sadt_guide_for_surgical_case``, idempotente)
    e usa a ``price_table`` já resolvida por ela. Para cada ``SurgicalMaterial`` com
    ``quantity_consumed > 0``:

      * tabelado (``simpro`` + ``simpro.tuss_code`` + ``material_unit_value`` > 0) →
        cria um ``TISSGuideItem`` precificado, idempotente via ``surgical_material``;
      * senão → emite um ``GlosaSafetyAlert`` NOT_IN_TABLE/ADVISE (não faturável,
        risco de glosa), idempotente via ``update_or_create``.

    Tudo em ``transaction.atomic``. Re-rodar não duplica itens nem alertas.
    """
    if case.status != SurgicalCase.Status.FINALIZADA:
        raise ValidationError("Somente cirurgias finalizadas podem ter materiais faturados.")

    with transaction.atomic():
        # Idempotente: garante/retorna a guia SP/SADT da cirurgia (B1) e reusa a
        # price_table que ela já resolveu do provider do convênio ativo.
        guide: TISSGuide = generate_sadt_guide_for_surgical_case(case)
        price_table = guide.price_table

        result = MaterialBillingResult(guide_id=guide.id)

        materials = case.materials.select_related("simpro", "simpro__tuss_code").filter(
            quantity_consumed__gt=0
        )
        for material in materials:
            simpro = material.simpro
            tuss = simpro.tuss_code if simpro is not None else None
            unit_value = (
                material_unit_value(price_table, simpro) if simpro is not None else Decimal("0")
            )

            # Inlined (não via bool intermediário) para o mypy estreitar simpro/tuss
            # a não-None dentro do ramo faturável.
            if simpro is not None and tuss is not None and unit_value > 0:
                # Idempotência do item: existe uma linha pra este material? pula.
                existing = TISSGuideItem.objects.filter(
                    guide=guide, surgical_material=material
                ).first()
                if existing is not None:
                    result.items_existing += 1
                    continue
                TISSGuideItem.objects.create(
                    guide=guide,
                    tuss_code=tuss,
                    description=simpro.display or material.description,
                    quantity=Decimal(material.quantity_consumed),
                    unit_value=unit_value,
                    surgical_material=material,
                )
                result.items_created += 1
            else:
                # Não faturável: material/OPME sem Simpro tabelado ou sem preço
                # negociado. Emite alerta de glosa idempotente (update_or_create na
                # unique_together do GlosaSafetyAlert). Não cria TISSGuideItem.
                simpro_display = simpro.display if simpro is not None else ""
                desc = material.description or simpro_display or material.get_kind_display()
                alert, _created = GlosaSafetyAlert.objects.update_or_create(
                    guide=guide,
                    guide_item=None,
                    check_code=GlosaSafetyAlert.CheckCode.NOT_IN_TABLE,
                    source=GlosaSafetyAlert.Source.ENGINE,
                    defaults={
                        "severity": GlosaSafetyAlert.Severity.ADVISE,
                        "status": GlosaSafetyAlert.Status.FLAGGED,
                        "message": (
                            f"Material/OPME '{desc}' consumido sem código Simpro tabelado ou "
                            f"sem preço negociado — custo não faturável, risco de glosa."
                        ),
                        "recommendation": (
                            "Cadastre o item no catálogo Simpro (com TUSS correspondente) e "
                            "negocie o preço na tabela do convênio antes de refaturar."
                        ),
                        "ans_glosa_code": "",
                    },
                )
                result.alert_ids.append(alert.id)

        # NOT_IN_TABLE alerts are guide-level (guide_item=None); the
        # GlosaSafetyAlert unique_together (nulls_distinct=False) collapses them to
        # ONE row per guide, so the truthful alert count is the DISTINCT row set —
        # multiple untabulated materials share a single consolidated alert row.
        result.alerts = len(set(result.alert_ids))
        return result
