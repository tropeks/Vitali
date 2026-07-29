"""
H2 — triagem sorológica service: the quarentena → liberada/descartada gate.

The bag serology release is driven ONLY through this module (never a raw
``serializer.save``) so the :class:`~apps.emr.blood_donor_models.BloodBagSerology`
row and the bag's ``serology_status`` / ``stock_status`` always move together
inside one ``transaction.atomic`` with ``select_for_update`` on the bag.

Release rule (RDC 34)
---------------------
A bag may only be tested while ``serology_status == quarentena`` (a fresh bag's
H1 default). Registering the mandatory marker panel:

* **all markers nao_reagente** → ``serology_status = liberada`` (bag becomes
  dispensable once not expired; ``is_available()`` flips true).
* **any marker reagente/indeterminado** → ``serology_status = descartada`` AND
  ``stock_status = descartada`` (bag is pulled from stock, never available).

Re-testing a bag that is already ``liberada`` or ``descartada`` is rejected with
``ValidationError`` (the API surfaces this as HTTP 409) — a released/discarded
result is final.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.emr.models import BloodBag, BloodBagSerology


@transaction.atomic
def registrar_sorologia(
    bag: BloodBag,
    resultados: dict[str, Any],
    *,
    by: Any | None = None,
    notes: str = "",
) -> BloodBagSerology:
    """Register the serology panel ``resultados`` for ``bag`` and apply the
    release rule — atomically.

    ``resultados`` maps each :attr:`BloodBagSerology.PANEL` marker to a
    :class:`BloodBagSerology.Result` value (omitted markers default to
    ``nao_reagente``).

    Raises ``ValidationError`` if the bag is not in ``quarentena`` (i.e. it was
    already released or discarded) — surfaced as HTTP 409 by the API.
    """
    locked = BloodBag.objects.select_for_update().get(pk=bag.pk)
    if locked.serology_status != BloodBag.SerologyStatus.QUARENTENA:
        raise ValidationError(
            f"Bolsa {locked.identifier} não está em quarentena "
            f"(situação sorológica: {locked.get_serology_status_display()}); "
            "sorologia já registrada."
        )

    markers = {m: resultados[m] for m in BloodBagSerology.PANEL if m in resultados}
    serology = BloodBagSerology.objects.create(bag=locked, tested_by=by, notes=notes, **markers)

    if serology.all_non_reactive:
        locked.serology_status = BloodBag.SerologyStatus.LIBERADA
        locked.save(update_fields=["serology_status", "updated_at"])
    else:
        locked.serology_status = BloodBag.SerologyStatus.DESCARTADA
        locked.stock_status = BloodBag.StockStatus.DESCARTADA
        locked.save(update_fields=["serology_status", "stock_status", "updated_at"])

    return serology
