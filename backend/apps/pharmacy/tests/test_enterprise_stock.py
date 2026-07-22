from decimal import Decimal

from apps.core.models import Role, User
from apps.pharmacy.models import (
    Drug,
    InventoryCount,
    InventoryCountLine,
    StockItem,
    StockTransfer,
    StockTransferLine,
    Warehouse,
)
from apps.pharmacy.services.enterprise_stock import InventoryService, TransferService
from apps.test_utils import TenantTestCase


class EnterpriseStockServiceTests(TenantTestCase):
    def setUp(self):
        maker_role = Role.objects.create(
            name="stock-maker",
            permissions=[
                "workflow.request",
                "pharmacy.inventory_count",
                "pharmacy.transfer_manage",
            ],
        )
        checker_role = Role.objects.create(
            name="stock-checker",
            permissions=[
                "workflow.approve",
                "pharmacy.inventory_approve",
                "pharmacy.transfer_accept",
            ],
        )
        self.maker = User.objects.create_user(email="stock-maker@test.local", role=maker_role)
        self.checker = User.objects.create_user(email="stock-checker@test.local", role=checker_role)
        self.origin = Warehouse.objects.create(code="CENTRAL", name="Central")
        self.destination = Warehouse.objects.create(code="SAT-1", name="Satélite")
        self.drug = Drug.objects.create(name="Teste")
        self.item = StockItem.objects.create(
            drug=self.drug, lot_number="L-1", warehouse=self.origin
        )
        from apps.pharmacy.models import StockMovement

        StockMovement.objects.create(
            stock_item=self.item,
            movement_type="entry",
            quantity=Decimal("10"),
            performed_by=self.maker,
        )

    def test_blind_count_only_posts_delta_after_checker_approval(self):
        count = InventoryCount.objects.create(warehouse=self.origin, requested_by=self.maker)
        InventoryCountLine.objects.create(
            inventory=count, stock_item=self.item, counted_quantity=Decimal("7")
        )
        InventoryService.submit(count, self.maker)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, Decimal("10"))
        InventoryService.decide(count, self.checker, True)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, Decimal("7"))

    def test_transfer_has_out_and_in_ledger_legs(self):
        transfer = StockTransfer.objects.create(
            origin=self.origin, destination=self.destination, requested_by=self.maker
        )
        line = StockTransferLine.objects.create(
            transfer=transfer, source_item=self.item, quantity=Decimal("4")
        )
        TransferService.ship(transfer, self.maker)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, Decimal("6"))
        TransferService.accept(transfer, self.checker)
        line.refresh_from_db()
        self.assertEqual(line.destination_item.quantity, Decimal("4"))
        self.assertEqual(
            line.source_item.movements.filter(
                reference__startswith=f"transfer:{transfer.pk}"
            ).count(),
            1,
        )
