"""
Regression tests for the professional-settlement defect fixes:

  #1 StockReceipt.approve select_for_update over nullable OUTER JOIN (500 on PG)
  #2 NFeReceipt.approve CNPJ×tenant fail-open (null-CNPJ tenant must be rejected)
  #3 return_receipt must restore PurchaseOrderItem.quantity_received + guard negative stock
  #4 map_item drug/material XOR + existence validation (was 500 via CheckConstraint)
  #6 external_id idempotency backed by a partial UniqueConstraint (TOCTOU)

Run: docker compose exec -T django pytest apps/pharmacy/tests/test_settlement_fixes.py
"""

from decimal import Decimal

from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from apps.core.models import FeatureFlag, Role, User
from apps.pharmacy.models import (
    Drug,
    Material,
    NFeCatalogMapping,
    NFeReceipt,
    NFeReceiptItem,
    PurchaseOrder,
    PurchaseOrderItem,
    StockItem,
    StockMovement,
    StockReceipt,
    StockReceiptLine,
    Supplier,
)
from apps.test_utils import TenantTestCase


def _enable_pharmacy(tenant):
    FeatureFlag.objects.update_or_create(
        tenant=tenant, module_key="pharmacy", defaults={"is_enabled": True}
    )


class SettlementFixTestCase(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        _enable_pharmacy(self.__class__.tenant)

        self.role = Role.objects.create(
            name="farm_settlement",
            permissions=[
                "pharmacy.read",
                "pharmacy.stock_manage",
                "pharmacy.procurement_manage",
            ],
        )
        self.user = User.objects.create_user(
            email="farm_settlement@test.com",
            password="Test123!",
            full_name="Farm Settlement",
            role=self.role,
        )
        self.client.force_authenticate(user=self.user)

        self.supplier = Supplier.objects.create(name="Distribuidora Test", is_active=True)
        self.drug = Drug.objects.create(
            name="Amoxicilina 500mg",
            generic_name="Amoxicilina",
            controlled_class="none",
            is_active=True,
        )
        # Ensure a clean CNPJ baseline (shared FastTenant reused across classes).
        self.__class__.tenant.cnpj = None
        self.__class__.tenant.save(update_fields=["cnpj"])

    # ── helpers ────────────────────────────────────────────────────────────
    def _make_receipt(self, ordered="100.000", received="0.000", line_qty="30.000"):
        po = PurchaseOrder.objects.create(supplier=self.supplier, status="draft")
        item = PurchaseOrderItem.objects.create(
            po=po,
            drug=self.drug,
            quantity_ordered=Decimal(ordered),
            quantity_received=Decimal(received),
            unit_price=Decimal("10.00"),
        )
        receipt = StockReceipt.objects.create(
            purchase_order=po,
            received_by=self.user,
            status=StockReceipt.Status.PENDING,
        )
        line = StockReceiptLine.objects.create(
            receipt=receipt,
            purchase_item=item,
            quantity=Decimal(line_qty),
            lot_number="LOT-SET",
        )
        return po, item, receipt, line

    # ── #1 approve happy-path (would 500 on Postgres before the fix) ─────────
    def test_stock_receipt_approve_happy_path(self):
        _po, item, receipt, _line = self._make_receipt()
        resp = self.client.post(f"/api/v1/pharmacy/stock/receipts/{receipt.id}/approve/")
        self.assertEqual(resp.status_code, 200, resp.data)
        receipt.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(receipt.status, StockReceipt.Status.APPROVED)
        self.assertEqual(item.quantity_received, Decimal("30.000"))
        stock = StockItem.objects.get(drug=self.drug, lot_number="LOT-SET")
        self.assertEqual(stock.quantity, Decimal("30.000"))

    def test_stock_receipt_approve_writes_audit(self):
        from apps.core.models import AuditLog

        _po, _item, receipt, _line = self._make_receipt()
        self.client.post(f"/api/v1/pharmacy/stock/receipts/{receipt.id}/approve/")
        self.assertTrue(
            AuditLog.objects.filter(
                action="approve_stock_receipt", resource_id=str(receipt.id)
            ).exists()
        )

    # ── #3 return restores quantity_received ─────────────────────────────────
    def test_return_restores_quantity_received(self):
        _po, item, receipt, _line = self._make_receipt()
        approve = self.client.post(f"/api/v1/pharmacy/stock/receipts/{receipt.id}/approve/")
        self.assertEqual(approve.status_code, 200, approve.data)
        item.refresh_from_db()
        self.assertEqual(item.quantity_received, Decimal("30.000"))

        ret = self.client.post(f"/api/v1/pharmacy/stock/receipts/{receipt.id}/return/")
        self.assertEqual(ret.status_code, 200, ret.data)
        receipt.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(receipt.status, StockReceipt.Status.RETURNED)
        # quantity_received rolled back to its pre-approve value.
        self.assertEqual(item.quantity_received, Decimal("0.000"))
        stock = StockItem.objects.get(drug=self.drug, lot_number="LOT-SET")
        self.assertEqual(stock.quantity, Decimal("0.000"))

    def test_return_negative_stock_is_clean_400_not_inconsistent(self):
        """If stock was already consumed, return must 400 and keep receipt APPROVED."""
        _po, _item, receipt, line = self._make_receipt()
        self.client.post(f"/api/v1/pharmacy/stock/receipts/{receipt.id}/approve/")
        line.refresh_from_db()
        # Consume all of the received stock so the negative return would go below zero.
        StockMovement.objects.create(
            stock_item=line.stock_item,
            movement_type="adjustment",
            quantity=Decimal("-30.000"),
            reference="manual-consume",
            performed_by=self.user,
        )
        ret = self.client.post(f"/api/v1/pharmacy/stock/receipts/{receipt.id}/return/")
        self.assertEqual(ret.status_code, 400, ret.data)
        receipt.refresh_from_db()
        # Rolled back: still APPROVED, quantity_received untouched.
        self.assertEqual(receipt.status, StockReceipt.Status.APPROVED)

    # ── #2 null-CNPJ tenant rejection (fail closed) ──────────────────────────
    def _make_nfe(self, recipient="11222333000181", confirmed=True):
        receipt = NFeReceipt.objects.create(
            access_key="1" * 44,
            issuer_cnpj="99888777000166",
            recipient_cnpj=recipient,
            xml="<nfe/>",
            status="pending",
        )
        nfe_item = NFeReceiptItem.objects.create(
            receipt=receipt,
            sequence=1,
            description="Item",
            quantity=Decimal("1.000"),
            unit_price=Decimal("1.0000"),
        )
        if confirmed:
            NFeCatalogMapping.objects.create(
                item=nfe_item,
                drug=self.drug,
                match_type="manual",
                confidence=100,
                status="confirmed",
            )
        return receipt

    def test_nfe_approve_rejects_when_tenant_has_no_cnpj(self):
        self.__class__.tenant.cnpj = None
        self.__class__.tenant.save(update_fields=["cnpj"])
        receipt = self._make_nfe()
        resp = self.client.post(f"/api/v1/pharmacy/nfe-receipts/{receipt.id}/approve/")
        self.assertEqual(resp.status_code, 409, resp.data)
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, "pending")

    def test_nfe_approve_ok_when_cnpj_matches(self):
        self.__class__.tenant.cnpj = "11.222.333/0001-81"
        self.__class__.tenant.save(update_fields=["cnpj"])
        receipt = self._make_nfe(recipient="11222333000181")
        resp = self.client.post(f"/api/v1/pharmacy/nfe-receipts/{receipt.id}/approve/")
        self.assertEqual(resp.status_code, 200, resp.data)
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, "approved")

    # ── #4 map_item validation ───────────────────────────────────────────────
    def _nfe_item_for_map(self):
        receipt = NFeReceipt.objects.create(
            access_key="2" * 44,
            issuer_cnpj="99888777000166",
            recipient_cnpj="11222333000181",
            xml="<nfe/>",
            status="pending",
        )
        return receipt, NFeReceiptItem.objects.create(
            receipt=receipt,
            sequence=1,
            description="Item",
            quantity=Decimal("1.000"),
            unit_price=Decimal("1.0000"),
        )

    def test_map_item_requires_exactly_one_target(self):
        receipt, item = self._nfe_item_for_map()
        url = f"/api/v1/pharmacy/nfe-receipts/{receipt.id}/items/{item.id}/map/"

        # neither → 400
        resp = self.client.post(url, {}, format="json")
        self.assertEqual(resp.status_code, 400, resp.data)

        # both → 400
        material = Material.objects.create(name="Gaze", is_active=True)
        resp = self.client.post(
            url, {"drug": str(self.drug.id), "material": str(material.id)}, format="json"
        )
        self.assertEqual(resp.status_code, 400, resp.data)

        # nonexistent drug id → 400 (not 500)
        resp = self.client.post(
            url, {"drug": "00000000-0000-0000-0000-000000000000"}, format="json"
        )
        self.assertEqual(resp.status_code, 400, resp.data)

        # valid single target → 200
        resp = self.client.post(url, {"drug": str(self.drug.id)}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)

    def test_map_item_malformed_uuid_is_400(self):
        receipt, item = self._nfe_item_for_map()
        url = f"/api/v1/pharmacy/nfe-receipts/{receipt.id}/items/{item.id}/map/"
        resp = self.client.post(url, {"drug": "not-a-uuid"}, format="json")
        self.assertEqual(resp.status_code, 400, resp.data)

    # ── #6 external_id idempotency constraint ────────────────────────────────
    def test_external_id_unique_when_present(self):
        NFeReceipt.objects.create(
            access_key="3" * 44,
            issuer_cnpj="99888777000166",
            recipient_cnpj="11222333000181",
            xml="<nfe/>",
            external_id="IDEMP-KEY-1",
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                NFeReceipt.objects.create(
                    access_key="4" * 44,
                    issuer_cnpj="99888777000166",
                    recipient_cnpj="11222333000181",
                    xml="<nfe/>",
                    external_id="IDEMP-KEY-1",
                )

    def test_blank_external_id_not_constrained(self):
        # Partial constraint excludes '' → multiple blank rows are allowed.
        NFeReceipt.objects.create(
            access_key="5" * 44,
            issuer_cnpj="99888777000166",
            recipient_cnpj="11222333000181",
            xml="<nfe/>",
            external_id="",
        )
        NFeReceipt.objects.create(
            access_key="6" * 44,
            issuer_cnpj="99888777000166",
            recipient_cnpj="11222333000181",
            xml="<nfe/>",
            external_id="",
        )
        self.assertEqual(NFeReceipt.objects.filter(external_id="").count(), 2)
