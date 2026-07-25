"""Sprint C4-T1 — ExamConsumption + record_exam_consumption (model/service layer).

TDD for per-exam supply consumption:
- an exam deducts its recipe's materials from the unit's stock via the ledger,
- ``cost_snapshot`` = Σ qty × unit_cost (exact Decimal, frozen on the row),
- re-recording the same exam is a no-op (idempotent — no double deduction),
- insufficient stock is handled cleanly (ValidationError, no partial deduction).
"""

from decimal import Decimal

from django.core.exceptions import ValidationError

from apps.concession.models import (
    ConcessionService,
    ExamConsumption,
    MaterialUnitCost,
    ServiceRecipe,
)
from apps.concession.services_pnl import record_exam_consumption
from apps.test_utils import TenantTestCase

from .factories import make_facility, make_material, make_user, make_warehouse, stock_item_with_qty


class _Fixtures(TenantTestCase):
    def setUp(self):
        self.user = make_user()
        self.unit = make_facility()
        self.wh = make_warehouse()
        self.gel = make_material("Gel condutor")
        self.film = make_material("Filme radiológico")
        MaterialUnitCost.objects.create(material=self.gel, unit_cost=Decimal("1.50"))
        MaterialUnitCost.objects.create(material=self.film, unit_cost=Decimal("10.00"))
        self.svc = ConcessionService.objects.create(code="SRV-US", name="Ultrassom")
        ServiceRecipe.objects.create(service=self.svc, material=self.gel, quantity=Decimal("2"))
        ServiceRecipe.objects.create(service=self.svc, material=self.film, quantity=Decimal("1"))
        self.gel_stock = stock_item_with_qty(self.gel, self.wh, 10, self.user, lot="G-1")
        self.film_stock = stock_item_with_qty(self.film, self.wh, 10, self.user, lot="F-1")


class TestExamDeductsRecipe(_Fixtures):
    def test_exam_deducts_recipe_materials_from_stock(self):
        record_exam_consumption(
            self.svc, self.unit, "EX-1", warehouse=self.wh, performed_by=self.user
        )
        self.gel_stock.refresh_from_db()
        self.film_stock.refresh_from_db()
        self.assertEqual(self.gel_stock.quantity, Decimal("8.000"))  # 10 − 2
        self.assertEqual(self.film_stock.quantity, Decimal("9.000"))  # 10 − 1

    def test_cost_snapshot_is_exact_decimal(self):
        ec = record_exam_consumption(
            self.svc, self.unit, "EX-2", warehouse=self.wh, performed_by=self.user
        )
        # 2 × 1.50 + 1 × 10.00 = 13.00
        self.assertEqual(ec.cost_snapshot, Decimal("13.00"))

    def test_movements_written_on_ledger(self):
        record_exam_consumption(
            self.svc, self.unit, "EX-3", warehouse=self.wh, performed_by=self.user
        )
        # One OUT movement per recipe material (plus the seeding 'entry' movement).
        out = self.gel_stock.movements.filter(movement_type="dispense")
        self.assertEqual(out.count(), 1)
        self.assertEqual(out.first().quantity, Decimal("-2.000"))


class TestIdempotentRecording(_Fixtures):
    def test_rerecording_same_exam_is_noop(self):
        first = record_exam_consumption(
            self.svc, self.unit, "EX-DUP", warehouse=self.wh, performed_by=self.user
        )
        second = record_exam_consumption(
            self.svc, self.unit, "EX-DUP", warehouse=self.wh, performed_by=self.user
        )
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(ExamConsumption.objects.filter(external_ref="EX-DUP").count(), 1)
        self.gel_stock.refresh_from_db()
        self.assertEqual(self.gel_stock.quantity, Decimal("8.000"))  # deducted once only


class TestInsufficientStock(_Fixtures):
    def test_insufficient_stock_raises_cleanly_without_partial_deduction(self):
        scarce = make_material("Contraste raro")
        MaterialUnitCost.objects.create(material=scarce, unit_cost=Decimal("5.00"))
        big = ConcessionService.objects.create(code="SRV-CT", name="Tomografia")
        # recipe needs 5 but only 1 is in stock
        ServiceRecipe.objects.create(service=big, material=scarce, quantity=Decimal("5"))
        scarce_stock = stock_item_with_qty(scarce, self.wh, 1, self.user, lot="C-1")

        with self.assertRaises(ValidationError):
            record_exam_consumption(
                big, self.unit, "EX-SHORT", warehouse=self.wh, performed_by=self.user
            )

        scarce_stock.refresh_from_db()
        self.assertEqual(scarce_stock.quantity, Decimal("1.000"))  # untouched
        self.assertFalse(ExamConsumption.objects.filter(external_ref="EX-SHORT").exists())

    def test_missing_exam_reference_raises(self):
        with self.assertRaises(ValidationError):
            record_exam_consumption(self.svc, self.unit, "", warehouse=self.wh)


class TestAppendOnly(_Fixtures):
    def test_row_is_append_only(self):
        ec = record_exam_consumption(
            self.svc, self.unit, "EX-AO", warehouse=self.wh, performed_by=self.user
        )
        with self.assertRaises(ValidationError):
            ec.cost_snapshot = Decimal("0")
            ec.save()
        with self.assertRaises(ValidationError):
            ec.delete()
