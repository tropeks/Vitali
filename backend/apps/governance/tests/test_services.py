from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from django_tenants.utils import get_public_schema_name, schema_context

from apps.core.models import AuditLog, Role, Tenant, User
from apps.governance.models import ApprovalRequest, DomainEventOutbox
from apps.governance.services import ApprovalService, EventEnvelope, OutboxService
from apps.test_utils import TenantTestCase


class ApprovalServiceTests(TenantTestCase):
    def setUp(self):
        maker_role = Role.objects.create(
            name="workflow-maker-test", permissions=["workflow.read", "workflow.request"]
        )
        checker_role = Role.objects.create(
            name="workflow-checker-test",
            permissions=["workflow.read", "workflow.approve", "finance.approve"],
        )
        self.maker = User.objects.create_user(email="maker@test.local", role=maker_role)
        self.checker = User.objects.create_user(email="checker@test.local", role=checker_role)

    def _create(self, steps=None):
        return ApprovalService.create(
            requested_by=self.maker,
            workflow_key="purchase-order",
            reference_type="purchase_order",
            reference_id="PO-1",
            title="Pedido PO-1",
            step_permissions=steps or ["finance.approve"],
            context={"amount": "1000.00"},
        )

    def test_checker_approves_and_audit_is_tenant_scoped(self):
        approval = self._create()

        ApprovalService.decide(approval_id=approval.pk, actor=self.checker, approve=True)

        approval.refresh_from_db()
        self.assertEqual(approval.status, ApprovalRequest.Status.APPROVED)
        self.assertEqual(approval.steps.get().decided_by, self.checker)
        self.assertEqual(
            AuditLog.for_current_tenant().filter(resource_id=str(approval.pk)).count(), 2
        )
        self.assertTrue(
            DomainEventOutbox.objects.filter(
                aggregate_id=str(approval.pk), event_type="approval.approved"
            ).exists()
        )

    def test_maker_cannot_check_own_request_even_with_permissions(self):
        self.maker.role.permissions += ["workflow.approve", "finance.approve"]
        self.maker.role.save(update_fields=["permissions"])
        approval = self._create()

        with self.assertRaises(PermissionDenied):
            ApprovalService.decide(approval_id=approval.pk, actor=self.maker, approve=True)

    def test_checker_must_hold_current_step_alcada(self):
        approval = self._create(["board.approve"])

        with self.assertRaises(PermissionDenied):
            ApprovalService.decide(approval_id=approval.pk, actor=self.checker, approve=True)

    def test_rejection_ends_workflow_and_prevents_second_decision(self):
        approval = self._create()
        ApprovalService.decide(
            approval_id=approval.pk, actor=self.checker, approve=False, note="Fora da política"
        )

        approval.refresh_from_db()
        self.assertEqual(approval.status, ApprovalRequest.Status.REJECTED)
        with self.assertRaises(ValidationError):
            ApprovalService.decide(approval_id=approval.pk, actor=self.checker, approve=True)

    def test_only_maker_can_cancel_pending_request(self):
        approval = self._create()
        with self.assertRaises(PermissionDenied):
            ApprovalService.cancel(approval_id=approval.pk, actor=self.checker)

        ApprovalService.cancel(approval_id=approval.pk, actor=self.maker)
        approval.refresh_from_db()
        self.assertEqual(approval.status, ApprovalRequest.Status.CANCELLED)


class OutboxServiceTests(TenantTestCase):
    def _event(self, **overrides):
        values = {
            "aggregate_type": "approval_request",
            "aggregate_id": "A-1",
            "event_type": "approval.approved",
            "payload": {"status": "approved"},
            "idempotency_key": "approval:A-1:approved",
        }
        values.update(overrides)
        return EventEnvelope(**values)

    def test_append_is_idempotent_for_same_envelope(self):
        first, created = OutboxService.append(self._event())
        second, created_again = OutboxService.append(self._event())

        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(DomainEventOutbox.objects.count(), 1)

    def test_idempotency_key_collision_with_different_payload_is_rejected(self):
        OutboxService.append(self._event())
        with self.assertRaises(ValidationError):
            OutboxService.append(self._event(payload={"status": "rejected"}))

    def test_event_envelope_cannot_be_changed_or_deleted(self):
        event, _ = OutboxService.append(self._event())
        event.payload = {"tampered": True}
        with self.assertRaises(ValidationError):
            event.save()
        with self.assertRaises(ValidationError):
            DomainEventOutbox.objects.filter(pk=event.pk).update(event_type="tampered")
        with self.assertRaises(ValidationError):
            event.delete()

    def test_dispatch_lifecycle_tracks_attempt_and_terminal_state(self):
        event, _ = OutboxService.append(self._event())

        claimed = OutboxService.claim_batch()
        event.refresh_from_db()
        self.assertEqual(claimed[0].pk, event.pk)
        self.assertEqual(event.status, DomainEventOutbox.Status.PROCESSING)
        self.assertEqual(event.attempts, 1)

        OutboxService.mark_failed(
            event, error="broker offline", retry_at=timezone.now() + timedelta(minutes=1)
        )
        event.refresh_from_db()
        self.assertEqual(event.status, DomainEventOutbox.Status.FAILED)
        self.assertEqual(event.last_error, "broker offline")


class OutboxTenantIsolationTests(TenantTestCase):
    def setUp(self):
        self.schema_a = self.__class__.tenant.schema_name
        with schema_context(get_public_schema_name()):
            self.tenant_b = Tenant.objects.create(name="Governance Clinic B", slug="governance-b")

    def tearDown(self):
        with schema_context(get_public_schema_name()):
            try:
                self.tenant_b.delete(force_drop=True)
            except Exception:
                self.tenant_b.delete()

    def test_outbox_is_physically_isolated_by_tenant_schema(self):
        with schema_context(self.schema_a):
            OutboxService.append(
                EventEnvelope(
                    aggregate_type="patient",
                    aggregate_id="P-1",
                    event_type="patient.updated",
                    payload={"id": "P-1"},
                    idempotency_key="tenant-a:patient:P-1:updated",
                )
            )
            self.assertEqual(DomainEventOutbox.objects.count(), 1)

        with schema_context(self.tenant_b.schema_name):
            self.assertEqual(DomainEventOutbox.objects.count(), 0)
