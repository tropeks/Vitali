"""C3-T4 — gated REST surface + tier gate + audit."""

from __future__ import annotations

from decimal import Decimal

from rest_framework.test import APIClient

from apps.concession.tests.factories import (
    make_facility,
    make_material,
    make_user,
    make_warehouse,
    stock_item_with_qty,
)
from apps.core.models import AuditLog, FeatureFlag
from apps.test_utils import TenantTestCase

BASE = "/api/v1/concession"


class ConcessionApiTests(TenantTestCase):
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

        self.facility = make_facility()
        self.material = make_material()
        self.source_wh = make_warehouse(code="CENTRAL", name="Central")
        self.unit_wh = make_warehouse(code="UNIT-WH", name="Unidade WH")
        self.stock = stock_item_with_qty(self.material, self.source_wh, 100, self.user)

    def _create_requisition(self):
        return self.client.post(
            f"{BASE}/supply-requisitions/",
            {
                "requesting_facility": str(self.facility.pk),
                "notes": "reposição semanal",
                "items": [{"material": str(self.material.pk), "quantity": "30"}],
            },
            format="json",
        )

    def test_full_flow_returns_201_and_lists(self):
        # Requisition
        resp = self._create_requisition()
        self.assertEqual(resp.status_code, 201, resp.data)
        req_id = resp.data["id"]
        self.assertEqual(resp.data["status"], "draft")

        self.assertEqual(
            self.client.post(f"{BASE}/supply-requisitions/{req_id}/submit/").status_code, 200
        )
        self.assertEqual(
            self.client.post(f"{BASE}/supply-requisitions/{req_id}/approve/").status_code, 200
        )

        # Pick list
        resp = self.client.post(f"{BASE}/pick-lists/", {"requisition": req_id}, format="json")
        self.assertEqual(resp.status_code, 201, resp.data)
        pl_id = resp.data["id"]
        pick_item_id = resp.data["items"][0]["id"]

        resp = self.client.post(
            f"{BASE}/pick-lists/{pl_id}/pick/",
            {
                "pick_item": pick_item_id,
                "source_stock_item": str(self.stock.pk),
                "picked_qty": "30",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["status"], "picked")

        # Dispatch
        resp = self.client.post(
            f"{BASE}/dispatches/",
            {
                "pick_list": pl_id,
                "manifest_code": "QR-API-1",
                "source_warehouse": str(self.source_wh.pk),
                "destination_warehouse": str(self.unit_wh.pk),
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        disp_id = resp.data["id"]

        self.assertEqual(self.client.post(f"{BASE}/dispatches/{disp_id}/ship/").status_code, 200)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, Decimal("70"))

        # Deliver → proof (201)
        resp = self.client.post(
            f"{BASE}/dispatches/{disp_id}/deliver/",
            {
                "received_by": "Enfermeira Ana",
                "signature_ref": "s3://sig/x.png",
                "geo_lat": "-23.550520",
                "geo_lng": "-46.633308",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)

        # Lists
        self.assertEqual(self.client.get(f"{BASE}/supply-requisitions/").status_code, 200)
        self.assertEqual(self.client.get(f"{BASE}/dispatches/").status_code, 200)
        pods = self.client.get(f"{BASE}/proof-of-deliveries/")
        self.assertEqual(pods.status_code, 200)
        results = pods.data["results"] if isinstance(pods.data, dict) else pods.data
        self.assertEqual(len(results), 1)

        # Audit written for the create.
        self.assertTrue(
            AuditLog.objects.filter(resource_type="SupplyRequisition", action="create").exists()
        )

    def test_tier_gate_blocks_without_feature_flag(self):
        FeatureFlag.objects.filter(
            tenant=self.__class__.tenant, module_key="diagnostic_concession"
        ).update(is_enabled=False)
        resp = self._create_requisition()
        self.assertEqual(resp.status_code, 403)

        # A read is gated too.
        self.assertEqual(self.client.get(f"{BASE}/supply-requisitions/").status_code, 403)

    def test_unauthenticated_is_rejected(self):
        self.client.logout()
        resp = self.client.get(f"{BASE}/supply-requisitions/")
        self.assertIn(resp.status_code, (401, 403))
