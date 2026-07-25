"""C1-T2 — AssetMovement (append-only ledger that relocates the asset).

Covers: deployment moves asset to a facility, retrieval returns it to the
warehouse, swap exchanges two assets' locations, ledger is immutable.
"""

from django.core.exceptions import ValidationError

from apps.concession.models import AssetMovement, EquipmentAsset
from apps.organization.models import Facility, LegalEntity
from apps.test_utils import TenantTestCase


class AssetMovementModelTest(TenantTestCase):
    def setUp(self):
        self.le = LegalEntity.objects.create(code="LE-M", name="Op")
        self.fac1 = Facility.objects.create(code="F-M1", name="Unit A", legal_entity=self.le)
        self.fac2 = Facility.objects.create(code="F-M2", name="Unit B", legal_entity=self.le)

    def test_deployment_moves_asset_to_facility(self):
        asset = EquipmentAsset.objects.create(asset_tag="AT-M1", model="X")
        self.assertIsNone(asset.current_location)
        AssetMovement.objects.create(
            asset=asset,
            movement_type=AssetMovement.MovementType.DEPLOYMENT,
            to_facility=self.fac1,
        )
        asset.refresh_from_db()
        self.assertEqual(asset.current_location_id, self.fac1.id)

    def test_retrieval_returns_asset_to_warehouse(self):
        asset = EquipmentAsset.objects.create(
            asset_tag="AT-M2", model="X", current_location=self.fac1
        )
        AssetMovement.objects.create(
            asset=asset,
            movement_type=AssetMovement.MovementType.RETRIEVAL,
            from_facility=self.fac1,
        )
        asset.refresh_from_db()
        self.assertIsNone(asset.current_location)

    def test_swap_exchanges_two_assets_locations(self):
        a1 = EquipmentAsset.objects.create(asset_tag="AT-M3", model="X", current_location=self.fac1)
        a2 = EquipmentAsset.objects.create(asset_tag="AT-M4", model="X", current_location=self.fac2)
        AssetMovement.objects.create(
            asset=a1,
            swapped_with=a2,
            movement_type=AssetMovement.MovementType.SWAP,
            from_facility=self.fac1,
            to_facility=self.fac2,
        )
        a1.refresh_from_db()
        a2.refresh_from_db()
        self.assertEqual(a1.current_location_id, self.fac2.id)
        self.assertEqual(a2.current_location_id, self.fac1.id)

    def test_ledger_is_append_only_no_update(self):
        asset = EquipmentAsset.objects.create(asset_tag="AT-M5", model="X")
        mv = AssetMovement.objects.create(
            asset=asset,
            movement_type=AssetMovement.MovementType.DEPLOYMENT,
            to_facility=self.fac1,
        )
        mv.notes = "tampered"
        with self.assertRaises(ValidationError):
            mv.save()
        # reloaded instance also cannot be updated
        reloaded = AssetMovement.objects.get(pk=mv.pk)
        with self.assertRaises(ValidationError):
            reloaded.save()

    def test_ledger_is_append_only_no_delete(self):
        asset = EquipmentAsset.objects.create(asset_tag="AT-M6", model="X")
        mv = AssetMovement.objects.create(
            asset=asset,
            movement_type=AssetMovement.MovementType.DEPLOYMENT,
            to_facility=self.fac1,
        )
        with self.assertRaises(ValidationError):
            mv.delete()
