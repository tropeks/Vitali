from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import connection
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import AuditLog, Role, User
from apps.governance.models import DomainEventOutbox, IntegrationInbox
from apps.governance.services import InboxEnvelope, InboxService
from apps.governance.tasks import dispatch_outbox, process_inbox
from apps.test_utils import TenantTestCase


class InboxServiceTests(TenantTestCase):
    def _envelope(self, **overrides):
        values = {
            "source": "connector-test",
            "message_type": "test.received",
            "payload": {"patient": "secret"},
            "headers": {"authorization": "secret"},
            "idempotency_key": "connector-test:1",
            "correlation_id": "trace-1",
        }
        values.update(overrides)
        return InboxEnvelope(**values)

    def test_receive_is_idempotent_and_collision_safe(self):
        first, created = InboxService.receive(self._envelope())
        second, created_again = InboxService.receive(self._envelope())
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first.pk, second.pk)
        with self.assertRaises(ValidationError):
            InboxService.receive(self._envelope(payload={"different": True}))

    def test_payload_and_headers_are_encrypted_at_rest(self):
        message, _ = InboxService.receive(self._envelope())
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT payload, headers FROM governance_integrationinbox WHERE id = %s",
                [message.pk],
            )
            payload, headers = cursor.fetchone()
        self.assertNotIn("patient", payload)
        self.assertNotIn("authorization", headers)

    def test_claim_failure_dead_and_replay_lifecycle(self):
        message, _ = InboxService.receive(self._envelope())
        claimed = InboxService.claim_batch()
        self.assertEqual(claimed[0].pk, message.pk)
        message.refresh_from_db()
        self.assertEqual(message.attempts, 1)
        InboxService.mark_failed(message, error="invalid", retry_at=timezone.now(), max_attempts=1)
        message.refresh_from_db()
        self.assertEqual(message.status, IntegrationInbox.Status.DEAD)
        InboxService.replay(message)
        message.refresh_from_db()
        self.assertEqual(message.status, IntegrationInbox.Status.RECEIVED)
        self.assertEqual(message.replay_count, 1)

    @patch("apps.governance.tasks.handle_inbox")
    def test_worker_processes_inside_requested_schema(self, handler):
        message, _ = InboxService.receive(self._envelope())
        result = process_inbox(self.tenant.schema_name)
        message.refresh_from_db()
        self.assertEqual(result["completed"], 1)
        self.assertEqual(message.status, IntegrationInbox.Status.COMPLETED)
        handler.assert_called_once()


class IntegrationOperationsAPITests(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        operator_role = Role.objects.create(
            name="integration-operator",
            permissions=["integrations.operations.read", "integrations.replay"],
        )
        viewer_role = Role.objects.create(
            name="integration-viewer", permissions=["integrations.operations.read"]
        )
        self.operator = User.objects.create_user(
            email="integration-op@test.local", role=operator_role
        )
        self.viewer = User.objects.create_user(
            email="integration-view@test.local", role=viewer_role
        )
        self.message, _ = InboxService.receive(
            InboxEnvelope(
                source="test",
                message_type="test.received",
                payload={"phi": "never-return"},
                headers={"token": "never-return"},
                idempotency_key="api:1",
            )
        )
        self.message.status = IntegrationInbox.Status.DEAD
        self.message.save(update_fields=("status",))

    def test_read_requires_permission_and_redacts_payload(self):
        self.client.force_authenticate(self.viewer)
        response = self.client.get("/api/v1/governance/integration-inbox/")
        self.assertEqual(response.status_code, 200)
        body = response.json()["results"][0]
        self.assertNotIn("payload", body)
        self.assertNotIn("headers", body)

    def test_replay_requires_permission_and_is_audited(self):
        self.client.force_authenticate(self.viewer)
        denied = self.client.post(f"/api/v1/governance/integration-inbox/{self.message.pk}/replay/")
        self.assertEqual(denied.status_code, 403)
        self.client.force_authenticate(self.operator)
        response = self.client.post(
            f"/api/v1/governance/integration-inbox/{self.message.pk}/replay/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            AuditLog.for_current_tenant()
            .filter(action="integration_replay", resource_id=str(self.message.pk))
            .exists()
        )


class OutboxDispatchWorkerTests(TenantTestCase):
    @patch("apps.governance.tasks.publish_outbox")
    def test_dispatch_marks_event_published(self, publisher):
        event = DomainEventOutbox.objects.create(
            idempotency_key="dispatch:1",
            aggregate_type="patient",
            aggregate_id="P-1",
            event_type="patient.updated",
            payload={"id": "P-1"},
            occurred_at=timezone.now(),
            available_at=timezone.now() - timedelta(seconds=1),
        )
        result = dispatch_outbox(self.tenant.schema_name)
        event.refresh_from_db()
        self.assertEqual(result["published"], 1)
        self.assertEqual(event.status, DomainEventOutbox.Status.PUBLISHED)
        publisher.assert_called_once()
