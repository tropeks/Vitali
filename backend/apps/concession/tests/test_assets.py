"""C1-T1 — EquipmentAsset + AssetService (comodato fleet).

Covers: create asset, place at facility, list enabled services, monthly
depreciation math (exact Decimal), asset_tag uniqueness.
"""

from decimal import Decimal

from django.db import IntegrityError, transaction

from apps.concession.models import (
    AssetService,
    ConcessionService,
    EquipmentAsset,
)
from apps.organization.models import Facility, LegalEntity
from apps.test_utils import TenantTestCase


class EquipmentAssetModelTest(TenantTestCase):
    def setUp(self):
        self.legal_entity = LegalEntity.objects.create(code="LE-OP", name="Operadora TCX")
        self.facility = Facility.objects.create(
            code="F-001", name="Clínica Cliente 1", legal_entity=self.legal_entity
        )
        self.service_rx = ConcessionService.objects.create(code="RX-TORAX", name="Raio-X Tórax")
        self.service_us = ConcessionService.objects.create(code="US-ABD", name="Ultrassom Abdômen")

    def test_create_asset_starts_at_warehouse(self):
        asset = EquipmentAsset.objects.create(asset_tag="AT-1020", model="Fuji Drypix")
        self.assertEqual(asset.status, EquipmentAsset.Status.ACTIVE)
        self.assertEqual(asset.ownership, EquipmentAsset.Ownership.OPERATOR)
        self.assertTrue(asset.active)
        # nullable current_location == at warehouse
        self.assertIsNone(asset.current_location)

    def test_place_asset_at_facility(self):
        asset = EquipmentAsset.objects.create(asset_tag="AT-1021", model="GE Vivid")
        asset.current_location = self.facility
        asset.save(update_fields=["current_location", "updated_at"])
        asset.refresh_from_db()
        self.assertEqual(asset.current_location_id, self.facility.id)

    def test_list_enabled_services(self):
        asset = EquipmentAsset.objects.create(asset_tag="AT-1022", model="Multi")
        AssetService.objects.create(asset=asset, service=self.service_rx)
        AssetService.objects.create(asset=asset, service=self.service_us)
        codes = sorted(asset.enabled_services.values_list("service__code", flat=True))
        self.assertEqual(codes, ["RX-TORAX", "US-ABD"])

    def test_asset_service_unique_pair(self):
        asset = EquipmentAsset.objects.create(asset_tag="AT-1023", model="Multi")
        AssetService.objects.create(asset=asset, service=self.service_rx)
        with self.assertRaises(IntegrityError), transaction.atomic():
            AssetService.objects.create(asset=asset, service=self.service_rx)

    def test_monthly_depreciation_exact(self):
        asset = EquipmentAsset(
            asset_tag="AT-1024",
            model="CR",
            purchase_cost=Decimal("60000.00"),
            useful_life_months=60,
        )
        self.assertEqual(asset.monthly_depreciation, Decimal("1000.00"))

    def test_monthly_depreciation_rounds_half_up(self):
        asset = EquipmentAsset(
            asset_tag="AT-1025",
            model="CR",
            purchase_cost=Decimal("10000.00"),
            useful_life_months=60,
        )
        # 10000 / 60 = 166.6666... -> 166.67
        self.assertEqual(asset.monthly_depreciation, Decimal("166.67"))

    def test_monthly_depreciation_zero_when_incomplete(self):
        asset = EquipmentAsset(asset_tag="AT-1026", model="CR")
        self.assertEqual(asset.monthly_depreciation, Decimal("0.00"))

    def test_asset_tag_unique(self):
        EquipmentAsset.objects.create(asset_tag="AT-DUP", model="A")
        with self.assertRaises(IntegrityError), transaction.atomic():
            EquipmentAsset.objects.create(asset_tag="AT-DUP", model="B")
