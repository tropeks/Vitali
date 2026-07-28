"""B0-T2 — AssetService viewset (asset → enabled exams)."""

from __future__ import annotations

from rest_framework.test import APIClient

from apps.concession.asset_models import AssetService, EquipmentAsset
from apps.concession.models import ConcessionService
from apps.concession.tests.factories import make_user
from apps.core.models import AuditLog, FeatureFlag
from apps.test_utils import TenantTestCase

BASE = "/api/v1/concession"


class AssetServiceApiTests(TenantTestCase):
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
        self.asset = EquipmentAsset.objects.create(asset_tag="AT-1", model="Fuji")
        self.service = ConcessionService.objects.create(code="RX", name="Raio-X")

    def test_create_asset_service_201_and_audited(self):
        resp = self.client.post(
            f"{BASE}/asset-services/",
            {"asset": self.asset.id, "service": self.service.id},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(
            AssetService.objects.filter(asset=self.asset, service=self.service).count(), 1
        )
        self.assertTrue(
            AuditLog.objects.filter(resource_type="AssetService", action="create").exists()
        )

    def test_list_filtered_by_asset(self):
        AssetService.objects.create(asset=self.asset, service=self.service)
        other = EquipmentAsset.objects.create(asset_tag="AT-2", model="GE")
        svc2 = ConcessionService.objects.create(code="US", name="Ultrassom")
        AssetService.objects.create(asset=other, service=svc2)
        resp = self.client.get(f"{BASE}/asset-services/", {"asset": self.asset.id})
        self.assertEqual(resp.status_code, 200, resp.content)
        results = resp.data["results"] if isinstance(resp.data, dict) else resp.data
        self.assertEqual(len(results), 1)

    def test_delete_asset_service_204(self):
        link = AssetService.objects.create(asset=self.asset, service=self.service)
        resp = self.client.delete(f"{BASE}/asset-services/{link.pk}/")
        self.assertEqual(resp.status_code, 204, resp.content)

    def test_tier_gate_403(self):
        FeatureFlag.objects.filter(
            tenant=self.__class__.tenant, module_key="diagnostic_concession"
        ).update(is_enabled=False)
        self.assertEqual(self.client.get(f"{BASE}/asset-services/").status_code, 403)
