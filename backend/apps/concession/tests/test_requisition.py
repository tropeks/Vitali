"""C3-T1 — SupplyRequisition + RequisitionItem, status flow."""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError

from apps.concession.logistics_models import RequisitionItem, SupplyRequisition
from apps.concession.services_logistics import approve_requisition, submit_requisition
from apps.concession.tests.factories import make_facility, make_material, make_user
from apps.test_utils import TenantTestCase


class SupplyRequisitionTests(TenantTestCase):
    def setUp(self):
        self.user = make_user()
        self.facility = make_facility()
        self.material = make_material()

    def _draft_with_item(self):
        req = SupplyRequisition.objects.create(
            requesting_facility=self.facility, requested_by=self.user
        )
        RequisitionItem.objects.create(
            requisition=req, material=self.material, quantity=Decimal("10")
        )
        return req

    def test_create_requisition_defaults_to_draft(self):
        req = self._draft_with_item()
        self.assertEqual(req.status, SupplyRequisition.Status.DRAFT)
        self.assertEqual(req.items.count(), 1)
        self.assertEqual(req.requesting_facility, self.facility)

    def test_submit_then_approve_flow(self):
        req = self._draft_with_item()
        submit_requisition(req)
        req.refresh_from_db()
        self.assertEqual(req.status, SupplyRequisition.Status.SUBMITTED)
        self.assertIsNotNone(req.submitted_at)

        approve_requisition(req)
        req.refresh_from_db()
        self.assertEqual(req.status, SupplyRequisition.Status.APPROVED)
        self.assertIsNotNone(req.approved_at)

    def test_cannot_submit_empty_requisition(self):
        req = SupplyRequisition.objects.create(
            requesting_facility=self.facility, requested_by=self.user
        )
        with self.assertRaises(ValidationError):
            submit_requisition(req)

    def test_cannot_approve_a_draft(self):
        req = self._draft_with_item()
        with self.assertRaises(ValidationError):
            approve_requisition(req)
