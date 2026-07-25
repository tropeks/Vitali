"""C1-T4 — Gated REST (assets / asset-movements / maintenance-tickets).

Covers: 201 create + list, and the tier gate — when the tenant lacks the
`diagnostic_concession` FeatureFlag, endpoints return 403.
"""

from rest_framework.test import APIClient

from apps.concession.models import ConcessionService, EquipmentAsset
from apps.core.models import FeatureFlag, User
from apps.organization.models import Facility, LegalEntity
from apps.test_utils import TenantTestCase

ASSETS_URL = "/api/v1/concession/assets/"
MOVEMENTS_URL = "/api/v1/concession/asset-movements/"
TICKETS_URL = "/api/v1/concession/maintenance-tickets/"


def _enable_concession(tenant, on=True):
    FeatureFlag.objects.update_or_create(
        tenant=tenant, module_key="diagnostic_concession", defaults={"is_enabled": on}
    )


class ConcessionApiTest(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        _enable_concession(self.__class__.tenant)

        self.user = User.objects.create_user(
            email="concession@test.com", password="Test123!", full_name="Concession User"
        )
        self.client.force_authenticate(user=self.user)

        self.le = LegalEntity.objects.create(code="LE-API", name="Op")
        self.fac = Facility.objects.create(code="F-API", name="Unit API", legal_entity=self.le)
        self.service = ConcessionService.objects.create(code="RX-API", name="Raio-X")

    def test_create_asset_201(self):
        resp = self.client.post(
            ASSETS_URL,
            {
                "asset_tag": "AT-API-1",
                "model": "Fuji",
                "name": "Raio-X Sala 1",
                "purchase_cost": "60000.00",
                "useful_life_months": 60,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(EquipmentAsset.objects.filter(asset_tag="AT-API-1").count(), 1)

    def test_list_assets_200(self):
        EquipmentAsset.objects.create(asset_tag="AT-API-2", model="X")
        resp = self.client.get(ASSETS_URL)
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_create_movement_201_relocates_asset(self):
        asset = EquipmentAsset.objects.create(asset_tag="AT-API-3", model="X")
        resp = self.client.post(
            MOVEMENTS_URL,
            {
                "asset": asset.id,
                "movement_type": "DEPLOYMENT",
                "to_facility": str(self.fac.id),
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        asset.refresh_from_db()
        self.assertEqual(asset.current_location_id, self.fac.id)

    def test_create_maintenance_ticket_201(self):
        asset = EquipmentAsset.objects.create(asset_tag="AT-API-4", model="X")
        resp = self.client.post(
            TICKETS_URL,
            {
                "asset": asset.id,
                "facility": str(self.fac.id),
                "description": "Não liga",
                "cost": "120.00",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        asset.refresh_from_db()
        self.assertEqual(asset.status, EquipmentAsset.Status.IN_MAINTENANCE)

    def test_tier_gate_returns_403_without_feature_flag(self):
        FeatureFlag.objects.filter(
            tenant=self.__class__.tenant, module_key="diagnostic_concession"
        ).delete()
        for url in (ASSETS_URL, MOVEMENTS_URL, TICKETS_URL):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 403, f"{url} -> {resp.status_code}")
