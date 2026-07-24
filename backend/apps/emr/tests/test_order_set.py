"""Sprint M1-S3-T2 — OrderSet / OrderSetItem versioning + approval + apply.

Covers:
- an order set is versioned (key + version, unique together);
- publishing is approval-gated via governance.ApprovalRequest (maker-checker):
  a draft cannot be applied; submit mints an approval; a different actor approves;
  only then is the version APPROVED;
- applying an approved order set to an encounter instantiates its items as
  concrete AppliedOrder rows;
- a version is frozen once approved: its items are immutable and content edits
  are rejected — changes require a new version.
"""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction

from apps.core.models import Role, User
from apps.emr.models import (
    AppliedOrder,
    Encounter,
    OrderSet,
    OrderSetItem,
    Patient,
    Professional,
)
from apps.emr.services.reconciliation import OrderSetService
from apps.governance.models import ApprovalRequest
from apps.governance.services import ApprovalService
from apps.test_utils import TenantTestCase


class OrderSetTests(TenantTestCase):
    def setUp(self):
        author_role = Role.objects.create(
            name="os_author", permissions=["emr.read", "emr.write", "workflow.request"]
        )
        approver_role = Role.objects.create(
            name="os_approver",
            permissions=["workflow.approve", "emr.order_set_approve"],
        )
        self.author = User.objects.create_user(
            email="os_author@t.com", password="pw", role=author_role
        )
        self.approver = User.objects.create_user(
            email="os_approver@t.com", password="pw", role=approver_role
        )
        self.patient = Patient.objects.create(
            full_name="OS Patient", birth_date="1985-02-02", gender="F", cpf="99988877766"
        )
        self.prof = Professional.objects.create(
            user=self.author, council_type="CRM", council_number="3030", council_state="SP"
        )
        self.encounter = Encounter.objects.create(
            patient=self.patient, professional=self.prof, chief_complaint="Sepse"
        )

    def _draft_with_items(self, key="sepsis-bundle"):
        order_set = OrderSet.objects.create(key=key, name="Bundle de Sepse", created_by=self.author)
        OrderSetItem.objects.create(
            order_set=order_set,
            order_type=OrderSetItem.OrderType.LAB,
            label="Lactato arterial",
            sequence=1,
        )
        OrderSetItem.objects.create(
            order_set=order_set,
            order_type=OrderSetItem.OrderType.MEDICATION,
            label="Ceftriaxona 2g IV",
            dosage_instructions="1x/dia",
            sequence=2,
        )
        return order_set

    def test_versioned_unique_key_version(self):
        self._draft_with_items()
        with self.assertRaises(IntegrityError), transaction.atomic():
            OrderSet.objects.create(
                key="sepsis-bundle", name="Dup", version=1, created_by=self.author
            )

    def test_draft_cannot_be_applied(self):
        order_set = self._draft_with_items()
        with self.assertRaises(ValidationError):
            order_set.apply_to_encounter(self.encounter, self.author)

    def test_approval_gated_publish_then_apply(self):
        order_set = self._draft_with_items()
        approval = OrderSetService.submit(order_set=order_set, requested_by=self.author)
        order_set.refresh_from_db()
        self.assertEqual(order_set.status, OrderSet.Status.PENDING_APPROVAL)
        self.assertEqual(approval.status, ApprovalRequest.Status.PENDING)

        # Maker cannot approve their own request.
        with self.assertRaises(PermissionDenied):
            ApprovalService.decide(approval_id=approval.pk, actor=self.author, approve=True)

        ApprovalService.decide(approval_id=approval.pk, actor=self.approver, approve=True)
        OrderSetService.sync_from_approval(order_set=order_set)
        order_set.refresh_from_db()
        self.assertEqual(order_set.status, OrderSet.Status.APPROVED)
        self.assertIsNotNone(order_set.approved_at)

        application = order_set.apply_to_encounter(self.encounter, self.author)
        orders = AppliedOrder.objects.filter(application=application)
        self.assertEqual(orders.count(), 2)
        self.assertEqual(
            set(orders.values_list("label", flat=True)),
            {"Lactato arterial", "Ceftriaxona 2g IV"},
        )
        self.assertTrue(all(o.encounter_id == self.encounter.id for o in orders))

    def test_rejection_returns_to_draft(self):
        order_set = self._draft_with_items()
        approval = OrderSetService.submit(order_set=order_set, requested_by=self.author)
        ApprovalService.decide(approval_id=approval.pk, actor=self.approver, approve=False)
        OrderSetService.sync_from_approval(order_set=order_set)
        order_set.refresh_from_db()
        self.assertEqual(order_set.status, OrderSet.Status.DRAFT)

    def test_frozen_after_approval(self):
        order_set = self._draft_with_items()
        OrderSetService.publish(
            order_set=order_set, requested_by=self.author, approver=self.approver
        )
        order_set.refresh_from_db()
        self.assertEqual(order_set.status, OrderSet.Status.APPROVED)

        # Content edit rejected.
        order_set.name = "Renomeado"
        with self.assertRaises(ValidationError):
            order_set.save()

        # Items immutable (add / edit / delete).
        with self.assertRaises(ValidationError):
            OrderSetItem.objects.create(
                order_set=order_set, order_type=OrderSetItem.OrderType.LAB, label="Extra"
            )
        existing = order_set.items.first()
        existing.label = "Alterado"
        with self.assertRaises(ValidationError):
            existing.save()
        with self.assertRaises(ValidationError):
            existing.delete()

    def test_new_version_clones_items_as_draft(self):
        order_set = self._draft_with_items()
        OrderSetService.publish(
            order_set=order_set, requested_by=self.author, approver=self.approver
        )
        order_set.refresh_from_db()
        v2 = order_set.create_new_version(self.author)
        self.assertEqual(v2.version, 2)
        self.assertEqual(v2.status, OrderSet.Status.DRAFT)
        self.assertEqual(v2.items.count(), order_set.items.count())
        # The new draft is editable again.
        v2.name = "Bundle de Sepse (revisado)"
        v2.save()
