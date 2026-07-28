"""B0-T5b — missing transitions: SupplyRequisition cancel + MaintenanceTicket start/complete."""

from __future__ import annotations

from decimal import Decimal

from rest_framework.test import APIClient

from apps.concession.asset_models import EquipmentAsset, MaintenanceTicket
from apps.concession.logistics_models import (
    RequisitionItem,
    SupplyRequisition,
)
from apps.concession.tests.factories import (
    make_facility,
    make_material,
    make_user,
)
from apps.core.models import AuditLog, FeatureFlag
from apps.test_utils import TenantTestCase

BASE = "/api/v1/concession"


class TransitionsApiTests(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="diagnostic_concession",
            defaults={"is_enabled": True},
        )
        self.user = make_user()
        self.client.force_authenticate(user=self.user)
        self.fac = make_facility()

    # ── SupplyRequisition cancel ──────────────────────────────────────────────
    def test_cancel_requisition_200(self):
        req = SupplyRequisition.objects.create(requesting_facility=self.fac, requested_by=self.user)
        RequisitionItem.objects.create(
            requisition=req, material=make_material(), quantity=Decimal("5")
        )
        resp = self.client.post(f"{BASE}/supply-requisitions/{req.pk}/cancel/")
        self.assertEqual(resp.status_code, 200, resp.content)
        req.refresh_from_db()
        self.assertEqual(req.status, SupplyRequisition.Status.CANCELLED)
        self.assertTrue(
            AuditLog.objects.filter(resource_type="SupplyRequisition", action="cancel").exists()
        )

    def test_cannot_cancel_fulfilled_requisition_400(self):
        req = SupplyRequisition.objects.create(
            requesting_facility=self.fac,
            requested_by=self.user,
            status=SupplyRequisition.Status.FULFILLED,
        )
        resp = self.client.post(f"{BASE}/supply-requisitions/{req.pk}/cancel/")
        self.assertEqual(resp.status_code, 400, resp.content)

    # ── MaintenanceTicket start / complete ────────────────────────────────────
    def test_start_then_complete_ticket(self):
        asset = EquipmentAsset.objects.create(asset_tag="AT-MT", model="Fuji")
        ticket = MaintenanceTicket.objects.create(asset=asset, description="Não liga")

        resp = self.client.post(f"{BASE}/maintenance-tickets/{ticket.pk}/start/")
        self.assertEqual(resp.status_code, 200, resp.content)
        ticket.refresh_from_db()
        asset.refresh_from_db()
        self.assertEqual(ticket.status, MaintenanceTicket.Status.IN_PROGRESS)
        self.assertIsNotNone(ticket.started_at)
        self.assertEqual(asset.status, EquipmentAsset.Status.IN_MAINTENANCE)

        resp = self.client.post(
            f"{BASE}/maintenance-tickets/{ticket.pk}/complete/",
            {"resolution": "Trocado fusível", "cost": "120.00"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        ticket.refresh_from_db()
        asset.refresh_from_db()
        self.assertEqual(ticket.status, MaintenanceTicket.Status.COMPLETED)
        self.assertIsNotNone(ticket.completed_at)
        self.assertEqual(ticket.cost, Decimal("120.00"))
        self.assertEqual(asset.status, EquipmentAsset.Status.ACTIVE)
        self.assertTrue(
            AuditLog.objects.filter(resource_type="MaintenanceTicket", action="complete").exists()
        )

    def test_tier_gate_403(self):
        asset = EquipmentAsset.objects.create(asset_tag="AT-GATE", model="X")
        ticket = MaintenanceTicket.objects.create(asset=asset)
        FeatureFlag.objects.filter(
            tenant=self.__class__.tenant, module_key="diagnostic_concession"
        ).update(is_enabled=False)
        resp = self.client.post(f"{BASE}/maintenance-tickets/{ticket.pk}/start/")
        self.assertEqual(resp.status_code, 403, resp.content)
