"""
S-042: Purchase Orders tests.
Run: python manage.py test apps.pharmacy.tests.test_purchase_orders
"""
import datetime
from decimal import Decimal

from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIClient

from apps.core.models import FeatureFlag, Role, User
from apps.pharmacy.models import Drug, PurchaseOrder, PurchaseOrderItem, StockItem, StockMovement, Supplier


def _enable_pharmacy(tenant):
    FeatureFlag.objects.update_or_create(
        tenant=tenant, module_key="pharmacy", defaults={"is_enabled": True}
    )


class PurchaseOrderTestCase(TenantTestCase):

    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain

        _enable_pharmacy(self.__class__.tenant)

        self.role = Role.objects.create(
            name="farmaceutico_po",
            permissions=["pharmacy.read", "pharmacy.stock_manage"],
        )
        self.user = User.objects.create_user(
            email="farm_po@test.com", password="Test123!", full_name="Farm PO", role=self.role
        )
        self.client.force_authenticate(user=self.user)

        self.supplier = Supplier.objects.create(name="Distribuidora Test", is_active=True)
        self.drug = Drug.objects.create(
            name="Amoxicilina 500mg",
            generic_name="Amoxicilina",
            controlled_class="none",
            is_active=True,
        )

    def test_create_po(self):
        resp = self.client.post(
            "/api/v1/pharmacy/purchase-orders/",
            {
                "supplier": str(self.supplier.id),
                "status": "draft",
                "notes": "Test PO",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["status"], "draft")

    def test_po_item_xor_validation_both_drug_and_material(self):
        """Serializer must raise 400 when both drug and material are set on a PO item."""
        from apps.pharmacy.serializers import PurchaseOrderItemSerializer
        from apps.pharmacy.models import Material
        material = Material.objects.create(name="Gaze", is_active=True)
        serializer = PurchaseOrderItemSerializer(data={
            "drug": str(self.drug.id),
            "material": str(material.id),
            "quantity_ordered": "10.000",
            "unit_price": "5.00",
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn("non_field_errors", serializer.errors)

    def test_po_item_xor_validation_neither(self):
        """Serializer must raise 400 when neither drug nor material is set."""
        from apps.pharmacy.serializers import PurchaseOrderItemSerializer
        serializer = PurchaseOrderItemSerializer(data={
            "quantity_ordered": "10.000",
            "unit_price": "5.00",
        })
        self.assertFalse(serializer.is_valid())

    def test_receive_full_creates_stock_movement(self):
        """Receiving a PO creates StockMovement with type purchase_order_receiving."""
        po = PurchaseOrder.objects.create(supplier=self.supplier, status="draft")
        item = PurchaseOrderItem.objects.create(
            po=po,
            drug=self.drug,
            quantity_ordered=Decimal("100.000"),
            unit_price=Decimal("10.00"),
        )

        resp = self.client.post(
            f"/api/v1/pharmacy/purchase-orders/{po.id}/receive/",
            {
                "items": [
                    {
                        "item_id": str(item.id),
                        "quantity_received": "100.000",
                        "lot_number": "LOT-001",
                        "expiry_date": str(datetime.date.today().replace(year=datetime.date.today().year + 1)),
                    }
                ]
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200)

        # PO status → received
        po.refresh_from_db()
        self.assertEqual(po.status, "received")

        # StockMovement created
        self.assertTrue(
            StockMovement.objects.filter(
                movement_type="purchase_order_receiving"
            ).exists()
        )

        # StockItem quantity updated
        stock = StockItem.objects.get(drug=self.drug, lot_number="LOT-001")
        self.assertEqual(stock.quantity, Decimal("100.000"))

    def test_receive_partial_sets_partial_status(self):
        """Receiving less than ordered sets PO to partial status."""
        po = PurchaseOrder.objects.create(supplier=self.supplier, status="draft")
        item = PurchaseOrderItem.objects.create(
            po=po,
            drug=self.drug,
            quantity_ordered=Decimal("100.000"),
            unit_price=Decimal("10.00"),
        )

        resp = self.client.post(
            f"/api/v1/pharmacy/purchase-orders/{po.id}/receive/",
            {
                "items": [
                    {
                        "item_id": str(item.id),
                        "quantity_received": "50.000",
                        "lot_number": "LOT-002",
                        "expiry_date": str(datetime.date.today().replace(year=datetime.date.today().year + 1)),
                    }
                ]
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        po.refresh_from_db()
        self.assertEqual(po.status, "partial")

    def test_stockitem_unique_constraint_prevents_duplicate_lots(self):
        """UniqueConstraint(nulls_distinct=False) prevents duplicate (drug, lot_number, expiry_date)."""
        expiry = datetime.date.today().replace(year=datetime.date.today().year + 1)
        StockItem.objects.create(drug=self.drug, lot_number="LOT-X", expiry_date=expiry)
        with self.assertRaises(Exception):
            StockItem.objects.create(drug=self.drug, lot_number="LOT-X", expiry_date=expiry)

    def test_stockitem_unique_constraint_null_expiry_prevents_duplicates(self):
        """Regression: UniqueConstraint(nulls_distinct=False) must prevent duplicate lots when expiry_date=None.
        PostgreSQL's legacy UNIQUE allows duplicate NULL-containing rows; nulls_distinct=False fixes this."""
        StockItem.objects.create(drug=self.drug, lot_number="LOT-NULL", expiry_date=None)
        with self.assertRaises(Exception):
            StockItem.objects.create(drug=self.drug, lot_number="LOT-NULL", expiry_date=None)

    def test_cancelled_po_cannot_be_received(self):
        """Receiving a cancelled PO returns 400."""
        po = PurchaseOrder.objects.create(
            supplier=self.supplier, status=PurchaseOrder.Status.CANCELLED
        )
        item = PurchaseOrderItem.objects.create(
            po=po, drug=self.drug, quantity_ordered=Decimal("10"), unit_price=Decimal("5")
        )
        resp = self.client.post(
            f"/api/v1/pharmacy/purchase-orders/{po.id}/receive/",
            {"items": [{"item_id": str(item.id), "quantity_received": "5"}]},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_pharmacy_module_off_blocks_po_endpoints(self):
        """When pharmacy module flag is off, PO endpoints return 403."""
        FeatureFlag.objects.filter(
            tenant=self.__class__.tenant, module_key="pharmacy"
        ).delete()
        resp = self.client.get("/api/v1/pharmacy/purchase-orders/")
        self.assertEqual(resp.status_code, 403)
