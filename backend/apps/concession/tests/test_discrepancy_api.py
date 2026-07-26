"""B0-T5a — DispatchDiscrepancy read endpoint (gated, read-only)."""

from __future__ import annotations

from decimal import Decimal

from rest_framework.test import APIClient

from apps.concession.logistics_models import (
    Dispatch,
    DispatchDiscrepancy,
    PickList,
    SupplyRequisition,
)
from apps.concession.tests.factories import (
    make_facility,
    make_material,
    make_user,
    make_warehouse,
)
from apps.core.models import FeatureFlag
from apps.test_utils import TenantTestCase

BASE = "/api/v1/concession"


class DispatchDiscrepancyApiTests(TenantTestCase):
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
        self.wh = make_warehouse()
        self.material = make_material()
        req = SupplyRequisition.objects.create(requesting_facility=self.fac, requested_by=self.user)
        pl = PickList.objects.create(requisition=req)
        self.dispatch = Dispatch.objects.create(
            manifest_code="M-DISC-1",
            pick_list=pl,
            source_warehouse=self.wh,
            destination_facility=self.fac,
        )
        self.disc = DispatchDiscrepancy.objects.create(
            dispatch=self.dispatch,
            type=DispatchDiscrepancy.Type.MISSING,
            material=self.material,
            quantity=Decimal("2"),
            reported_by=self.user,
        )

    def test_list_discrepancies_200(self):
        resp = self.client.get(f"{BASE}/dispatch-discrepancies/")
        self.assertEqual(resp.status_code, 200, resp.content)
        results = resp.data["results"] if isinstance(resp.data, dict) else resp.data
        self.assertEqual(len(results), 1)

    def test_list_filtered_by_dispatch(self):
        resp = self.client.get(
            f"{BASE}/dispatch-discrepancies/", {"dispatch": str(self.dispatch.pk)}
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        results = resp.data["results"] if isinstance(resp.data, dict) else resp.data
        self.assertEqual(len(results), 1)

    def test_retrieve_200(self):
        resp = self.client.get(f"{BASE}/dispatch-discrepancies/{self.disc.pk}/")
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_read_only_no_post(self):
        resp = self.client.post(
            f"{BASE}/dispatch-discrepancies/",
            {"dispatch": str(self.dispatch.pk), "type": "missing"},
            format="json",
        )
        self.assertEqual(resp.status_code, 405, resp.content)

    def test_tier_gate_403(self):
        FeatureFlag.objects.filter(
            tenant=self.__class__.tenant, module_key="diagnostic_concession"
        ).update(is_enabled=False)
        self.assertEqual(self.client.get(f"{BASE}/dispatch-discrepancies/").status_code, 403)
