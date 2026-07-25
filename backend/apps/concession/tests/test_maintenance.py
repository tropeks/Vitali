"""C1-T3 — MaintenanceTicket (asset status reflects maintenance; cost recorded).

Covers: open -> in_progress -> completed flow, asset status flips to
IN_MAINTENANCE while the ticket is open and back to ACTIVE on completion,
repair cost recorded.
"""

from decimal import Decimal

from apps.concession.models import EquipmentAsset, MaintenanceTicket
from apps.organization.models import Facility, LegalEntity
from apps.test_utils import TenantTestCase


class MaintenanceTicketModelTest(TenantTestCase):
    def setUp(self):
        self.le = LegalEntity.objects.create(code="LE-T", name="Op")
        self.fac = Facility.objects.create(code="F-T1", name="Unit T", legal_entity=self.le)
        self.asset = EquipmentAsset.objects.create(
            asset_tag="AT-T1", model="X", current_location=self.fac
        )

    def test_open_ticket_puts_asset_in_maintenance(self):
        self.assertEqual(self.asset.status, EquipmentAsset.Status.ACTIVE)
        MaintenanceTicket.objects.create(
            asset=self.asset,
            facility=self.fac,
            description="Não liga",
        )
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, EquipmentAsset.Status.IN_MAINTENANCE)

    def test_full_flow_open_in_progress_completed(self):
        ticket = MaintenanceTicket.objects.create(
            asset=self.asset, facility=self.fac, description="Falha na fonte"
        )
        self.assertEqual(ticket.status, MaintenanceTicket.Status.OPEN)

        ticket.start()
        ticket.refresh_from_db()
        self.asset.refresh_from_db()
        self.assertEqual(ticket.status, MaintenanceTicket.Status.IN_PROGRESS)
        self.assertIsNotNone(ticket.started_at)
        self.assertEqual(self.asset.status, EquipmentAsset.Status.IN_MAINTENANCE)

        ticket.complete(resolution="Fonte trocada", cost=Decimal("450.00"))
        ticket.refresh_from_db()
        self.asset.refresh_from_db()
        self.assertEqual(ticket.status, MaintenanceTicket.Status.COMPLETED)
        self.assertIsNotNone(ticket.completed_at)
        self.assertEqual(ticket.cost, Decimal("450.00"))
        self.assertEqual(ticket.resolution, "Fonte trocada")
        # asset back in service
        self.assertEqual(self.asset.status, EquipmentAsset.Status.ACTIVE)

    def test_cancelled_ticket_returns_asset_to_active(self):
        ticket = MaintenanceTicket.objects.create(
            asset=self.asset, facility=self.fac, description="Alarme falso"
        )
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, EquipmentAsset.Status.IN_MAINTENANCE)
        ticket.status = MaintenanceTicket.Status.CANCELLED
        ticket.save()
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, EquipmentAsset.Status.ACTIVE)
