"""Shared setup helpers for concession tests."""

from __future__ import annotations

from decimal import Decimal

from apps.core.models import Role, User
from apps.organization.models import Facility, LegalEntity
from apps.pharmacy.models import Material, StockItem, StockMovement, Warehouse


def make_user(email="ops@test.local", perms=None) -> User:
    role, _ = Role.objects.get_or_create(
        name=f"role-{email}", defaults={"permissions": perms or []}
    )
    return User.objects.create_user(email=email, role=role, full_name="Ops")


def make_facility(code="UNIT-1", name="Unidade 1") -> Facility:
    entity, _ = LegalEntity.objects.get_or_create(code="LE-1", defaults={"name": "Operadora"})
    return Facility.objects.create(code=code, name=name, legal_entity=entity)


def make_material(name="Luva nitrílica") -> Material:
    return Material.objects.create(name=name, unit_of_measure="un")


def make_warehouse(code="CENTRAL", name="Central") -> Warehouse:
    return Warehouse.objects.create(code=code, name=name)


def stock_item_with_qty(material, warehouse, qty, user, lot="L-1") -> StockItem:
    """Create a StockItem and seed it via the pharmacy ledger (entry)."""
    item = StockItem.objects.create(material=material, warehouse=warehouse, lot_number=lot)
    StockMovement.objects.create(
        stock_item=item,
        movement_type="entry",
        quantity=Decimal(str(qty)),
        performed_by=user,
    )
    item.refresh_from_db()
    return item
