"""
C6 — Centro Cirúrgico material/OPME consumption service (rastreabilidade).

Recording the consumption of a :class:`SurgicalMaterial` goes ONLY through this
module so the ``quantity_consumed`` bump and the pharmacy-stock decrement move
together inside one ``transaction.atomic`` under a row lock — mirroring
:mod:`apps.emr.services.surgery_intraop` (atomic + ``select_for_update`` + raise
``ValidationError``; the viewset surfaces that as HTTP 400).

Consumption traceability
------------------------
``record_consumption`` always increments ``quantity_consumed``. IF the material
maps to a catalogued pharmacy lot (``stock_item`` is set), it ALSO appends a
:class:`pharmacy.StockMovement` of the existing consumption kind
(``movement_type="dispense"`` — a **negative** quantity is a saída; see
``StockMovement.MOVEMENT_TYPES`` and the F()-based atomic decrement in
``StockMovement.save``) linked to both the ``stock_item`` and the
``surgical_case``, so the stock ledger row is traceable to the surgery that
consumed it. If there is no ``stock_item`` (uncatalogued OPME) only
``quantity_consumed`` is tracked — no stock movement.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.emr.models import SurgicalMaterial
from apps.pharmacy.models import StockMovement

# The existing consumption/saída movement kind (StockMovement.MOVEMENT_TYPES).
# A negative quantity is a saída; StockMovement.save() applies the F()-based
# decrement and rejects a movement that would drive stock negative.
_CONSUMPTION_MOVEMENT_TYPE = "dispense"


@transaction.atomic
def record_consumption(
    material: SurgicalMaterial,
    quantity: int,
    *,
    actor: Any | None = None,
) -> SurgicalMaterial:
    """Record ``quantity`` consumed of ``material`` — atomically, under a lock.

    Increments ``quantity_consumed`` and, if the material is linked to a
    catalogued ``stock_item``, appends a traced :class:`StockMovement` (kind
    ``dispense``, negative quantity, ``surgical_case=material.case``) that
    decrements the stock lot. Raises ``ValidationError`` if ``quantity`` is not a
    positive integer.
    """
    if quantity is None or quantity <= 0:
        raise ValidationError("A quantidade consumida deve ser maior que zero.")

    locked = SurgicalMaterial.objects.select_for_update().get(pk=material.pk)
    locked.quantity_consumed = (locked.quantity_consumed or 0) + quantity
    locked.save(update_fields=["quantity_consumed", "updated_at"])

    stock_item = locked.stock_item
    if stock_item is not None:
        # StockMovement.save() does the F()-based atomic decrement + non-negative
        # guard; a shortfall raises ValueError (surfaced as a 500 — the caller is
        # expected to consume within stock, like the dispense flow).
        # (Bind to a local so mypy narrows StockItem|None → StockItem.)
        StockMovement.objects.create(
            stock_item=stock_item,
            movement_type=_CONSUMPTION_MOVEMENT_TYPE,
            quantity=-Decimal(quantity),
            reference=f"Consumo cirúrgico {locked.case_id}",
            notes=f"Consumo de material/OPME no caso {locked.case_id}",
            performed_by=actor,
            surgical_case=locked.case,
        )

    return locked
