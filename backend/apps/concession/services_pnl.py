"""Sprint C4 — consumption recording + contract/unit P&L engine.

``record_exam_consumption`` deducts a service's ``ServiceRecipe`` from the unit's
on-hand stock on the existing ``pharmacy.StockMovement`` ledger (FEFO across
lots) and freezes the consumed cost onto an :class:`ExamConsumption` row —
idempotent per exam, atomic (insufficient stock rolls the whole exam back).

``contract_pnl`` / ``unit_pnl`` roll those rows up against the contract's prices:
revenue (billable only, but volume always counts) − cost (consumption + freight
+ maintenance), with a per-service breakdown. Freight uses each ``Dispatch``'s
freight cost if present; the C3 ``Dispatch`` carries none, so that leg is 0 today
(see TDD_LOG assumption). Maintenance sums ``MaintenanceTicket.cost`` for the
contract's units in the period.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from .asset_models import MaintenanceTicket
from .contract_models import consumption_for
from .logistics_models import Dispatch
from .pnl_models import ExamConsumption, MaterialUnitCost

_TWO_PLACES = Decimal("0.01")
CONSUMPTION_MOVEMENT_TYPE = "dispense"


# ─── Cost basis ───────────────────────────────────────────────────────────────


def material_unit_cost(material) -> Decimal:
    """The operator's registered unit cost for *material*, or 0 (inert) if none."""
    row = MaterialUnitCost.objects.filter(material=material).first()
    return row.unit_cost if row is not None else Decimal("0")


# ─── Recording consumption ────────────────────────────────────────────────────


def _idempotency_key(service, unit, external_ref: str, dicom_study) -> str:
    """Stable per-exam key. A DICOM study identifies the exam by itself; a free
    external ref is scoped by unit+service to avoid cross-service collisions."""
    if dicom_study is not None:
        return f"study:{dicom_study.pk}"
    if external_ref:
        return f"ref:{unit.pk}:{service.pk}:{external_ref}"
    raise ValidationError(
        "record_exam_consumption requires an exam reference (external_ref or dicom_study)."
    )


def _deduct_material(material, needed: Decimal, warehouse, consumption, performed_by) -> None:
    """Write OUT movements draining *needed* of *material* FEFO from the unit's
    stock. Raises cleanly (no partial deduction — caller is atomic) if short."""
    from apps.pharmacy.models import StockItem, StockMovement

    qs = StockItem.objects.filter(material=material, status="available")
    if warehouse is not None:
        qs = qs.filter(warehouse=warehouse)
    lots = list(qs.order_by("expiry_date", "lot_number"))
    available = sum((lot.quantity for lot in lots), Decimal("0"))
    if available < needed:
        raise ValidationError(
            f"Insufficient stock for {material}: need {needed}, have {available}."
        )
    remaining = needed
    ref = f"concession-exam:{consumption.idempotency_key}"
    for lot in lots:
        if remaining <= Decimal("0"):
            break
        take = min(lot.quantity, remaining)
        if take <= Decimal("0"):
            continue
        StockMovement.objects.create(
            stock_item=lot,
            movement_type=CONSUMPTION_MOVEMENT_TYPE,
            quantity=-take,
            reference=ref,
            performed_by=performed_by,
        )
        remaining -= take


@transaction.atomic
def record_exam_consumption(
    service,
    unit,
    external_ref: str = "",
    *,
    dicom_study=None,
    warehouse=None,
    performed_at=None,
    performed_by=None,
) -> ExamConsumption:
    """Record one exam of *service* at *unit*, deducting its recipe from stock.

    Idempotent: a second call for the same exam returns the existing row without
    deducting again. Atomic: if any material is short, nothing is deducted and no
    row is created.
    """
    key = _idempotency_key(service, unit, external_ref, dicom_study)
    existing = ExamConsumption.objects.filter(idempotency_key=key).first()
    if existing is not None:
        return existing  # idempotent no-op

    recipe = consumption_for(service)  # {material: qty_per_exam}
    cost = sum(
        (qty * material_unit_cost(material) for material, qty in recipe.items()),
        Decimal("0"),
    ).quantize(_TWO_PLACES)

    consumption = ExamConsumption.objects.create(
        unit=unit,
        service=service,
        external_ref=external_ref or "",
        dicom_study=dicom_study,
        source_warehouse=warehouse,
        performed_at=performed_at or timezone.now(),
        cost_snapshot=cost,
        idempotency_key=key,
    )
    for material, qty in recipe.items():
        _deduct_material(material, qty, warehouse, consumption, performed_by)
    return consumption


# ─── P&L engine ───────────────────────────────────────────────────────────────


def _in_period(qs, field: str, start, end):
    if start is not None:
        qs = qs.filter(**{f"{field}__date__gte": start})
    if end is not None:
        qs = qs.filter(**{f"{field}__date__lte": end})
    return qs


def _freight_for(units, start, end) -> Decimal:
    """Σ freight over dispatches to *units* in the period. The C3 ``Dispatch``
    carries no freight field, so this is 0 today (defensive getattr hook)."""
    qs = _in_period(
        Dispatch.objects.filter(destination_facility__in=units), "created_at", start, end
    )
    total = Decimal("0")
    for dispatch in qs:
        freight = getattr(dispatch, "freight_cost", None)
        if freight:
            total += freight
    return total


def _maintenance_for(units, start, end) -> Decimal:
    """Σ ``MaintenanceTicket.cost`` for the contract's units in the period."""
    qs = MaintenanceTicket.objects.filter(cost__isnull=False).filter(
        models.Q(facility__in=units) | models.Q(asset__current_location__in=units)
    )
    qs = _in_period(qs, "created_at", start, end)
    return sum((ticket.cost for ticket in qs if ticket.cost is not None), Decimal("0"))


def _pnl_over_units(contract, units, start, end) -> dict:
    """Core roll-up shared by contract_pnl and unit_pnl."""
    exams = _in_period(
        ExamConsumption.objects.filter(unit__in=units).select_related("service", "unit"),
        "performed_at",
        start,
        end,
    )

    revenue = Decimal("0")
    consumption_cost = Decimal("0")
    exam_volume = 0
    by_service: dict = {}

    for exam in exams:
        exam_volume += 1
        price = contract.resolve_price(exam.service, exam.unit)
        line_revenue = price.billable_revenue if price is not None else Decimal("0")
        revenue += line_revenue
        consumption_cost += exam.cost_snapshot

        line = by_service.setdefault(
            exam.service_id,
            {
                "service": exam.service_id,
                "service_code": exam.service.code,
                "service_name": exam.service.name,
                "exam_volume": 0,
                "revenue": Decimal("0"),
                "consumption_cost": Decimal("0"),
            },
        )
        line["exam_volume"] += 1
        line["revenue"] += line_revenue
        line["consumption_cost"] += exam.cost_snapshot

    freight = _freight_for(units, start, end)
    maintenance = _maintenance_for(units, start, end)
    cost = consumption_cost + freight + maintenance
    result = revenue - cost

    return {
        "contract": contract.pk,
        "units": [u.pk for u in units],
        "start": start,
        "end": end,
        "exam_volume": exam_volume,
        "revenue": revenue,
        "cost": cost,
        "result": result,
        "cost_breakdown": {
            "consumption": consumption_cost,
            "freight": freight,
            "maintenance": maintenance,
        },
        "by_service": sorted(by_service.values(), key=lambda line: line["service_code"]),
    }


def contract_pnl(contract, start=None, end=None) -> dict:
    """P&L for the whole contract across all its units in ``[start, end]``.

    ``revenue`` counts billable prices only (non-billable → 0), but
    ``exam_volume`` counts every exam. ``cost`` = consumption + freight +
    maintenance. ``result = revenue − cost``. Includes a per-service breakdown.
    """
    units = list(contract.units.all())
    return _pnl_over_units(contract, units, start, end)


def unit_pnl(contract, unit, start=None, end=None) -> dict:
    """P&L for a single *unit* of *contract* in ``[start, end]``."""
    return _pnl_over_units(contract, [unit], start, end)


__all__ = [
    "material_unit_cost",
    "record_exam_consumption",
    "contract_pnl",
    "unit_pnl",
]
