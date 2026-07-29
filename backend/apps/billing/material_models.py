"""
Billing — Material/OPME: preço negociado por convênio (Sprint B4a)
==================================================================
Per-tenant material pricing model, kept in a dedicated module (imported at the
end of ``apps/billing/models.py``) so the material-pricing source integrates as
an additive leaf — exactly like ``inpatient_models`` / ``sus_models`` /
``revenue_models`` — without churning the TISS billing file.

Domínio
-------
Material/OPME **não** precifica por TUSS/PriceTable como os procedimentos: a
referência é a tabela **Simpro** (:class:`~apps.core.simpro_models.SimproMaterial`,
SHARED). O convênio negocia um valor em cima do preço de referência Simpro
(tipicamente Simpro menos um deflator). :class:`MaterialPriceItem` é esse valor
negociado por (``PriceTable`` do convênio, item Simpro) — o espelho exato de
:class:`~apps.billing.models.PriceTableItem` (que faz o mesmo para procedimentos
TUSS), reutilizando a mesma ``PriceTable``.

O bridge de consumo (material de sala → custo/glosa) é o Sprint B4b, fora do
escopo aqui. Este módulo modela apenas a FONTE DE PREÇO.

Cross-schema FK note
--------------------
``core.SimproMaterial`` vive no schema PUBLIC/SHARED. PostgreSQL não impõe
integridade de FK entre schemas (tenant → public), então — exatamente como
``PriceTableItem.tuss_code`` → ``core.TUSSCode`` — o FK ``simpro`` usa
``on_delete=PROTECT`` como enforcement application-layer, e confia no signal
``protect_simpro_material_deletion`` (apps/core/signals.py) para bloquear a
deleção de um material referenciado por qualquer tenant.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models

# ─── B4a: valor negociado de material/OPME por convênio ──────────────────────


class MaterialPriceItem(models.Model):
    """Valor negociado de um material/OPME Simpro em uma tabela de preços. Per-tenant.

    Espelha :class:`~apps.billing.models.PriceTableItem` (procedimentos TUSS),
    mas para material: a mesma ``PriceTable`` do convênio, com o item de preço
    apontando para um ``core.SimproMaterial`` (SHARED) em vez de ``core.TUSSCode``.
    ``negotiated_value`` é o valor efetivamente negociado com o convênio para
    aquele material (tipicamente Simpro menos deflator).
    """

    table = models.ForeignKey(
        "billing.PriceTable", on_delete=models.CASCADE, related_name="material_items"
    )
    # FK to public-schema SimproMaterial — app-layer PROTECT only (cross-schema
    # limit), espelhando PriceTableItem.tuss_code. O signal
    # protect_simpro_material_deletion compensa a falta de FK cross-schema real.
    simpro = models.ForeignKey(
        "core.SimproMaterial",
        on_delete=models.PROTECT,
        related_name="material_price_items",
        verbose_name="Material Simpro",
    )
    negotiated_value = models.DecimalField(
        "Valor negociado (R$)",
        max_digits=12,
        decimal_places=4,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Valor negociado do material com o convênio (tipicamente Simpro menos deflator).",
    )

    class Meta:
        verbose_name = "Item de Material (preço negociado)"
        verbose_name_plural = "Itens de Material (preço negociado)"
        unique_together = [("table", "simpro")]

    def __str__(self):
        return f"{self.simpro.code} — R${self.negotiated_value}"
