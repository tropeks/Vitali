"""
B4a — Material/OPME: resolução de preço negociado.
==================================================
Helper de precificação de material, espelho de ``_unit_value`` em
:mod:`apps.billing.services.lab_order_billing` (que resolve o preço de um TUSS
numa ``PriceTable``): dado uma ``PriceTable`` do convênio e um item Simpro,
devolve o ``MaterialPriceItem.negotiated_value`` negociado, ou ``Decimal("0")``
quando não há preço negociado (nunca inventa valor).

Será consumido pelo bridge de consumo de material (Sprint B4b): ao materializar
o custo/glosa de um material de sala, o B4b resolve o item Simpro do material e
chama este helper para obter o valor faturável.
"""

from __future__ import annotations

from decimal import Decimal

from apps.billing.material_models import MaterialPriceItem
from apps.billing.models import PriceTable
from apps.core.simpro_models import SimproMaterial


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
