"""
Tests for S-110 — F-04 welcome message wired into FSM opt-in transition.

Five cases:
1. do_opt_in with linked patient → task delayed + opt_in_completed audit
2. do_opt_in without patient → no task, log skip
3. send_post_opt_in_welcome happy path → send_text + opt_in_welcome_sent audit
4. send_post_opt_in_welcome fail-open → opt_in_welcome_failed audit on MaxRetriesExceededError
5. send_post_opt_in_welcome no-op when opt_in reverted between enqueue and run

Notes on test harness:
- FastTenantTestCase wraps each test in a savepoint, so transaction.on_commit
  callbacks don't fire. We patch apps.whatsapp.services.opt_in.transaction.on_commit
  to call the callback immediately.
- send_post_opt_in_welcome.__wrapped__ is a bound method (self = task object).
  Call it as __wrapped__(contact_id, correlation_id) — no explicit self needed.
- The task does `from apps.whatsapp.gateway import get_gateway` inside its body,
  so we patch at the source: apps.whatsapp.gateway.get_gateway.
"""

from unittest.mock import MagicMock, patch

from apps.core.models import AuditLog
from apps.test_utils import TenantTestCase
from apps.whatsapp.models import WhatsAppContact
from apps.whatsapp.tasks import send_post_opt_in_welcome


def _make_patient(cpf="52998224725", phone="5511900000099"):
    from apps.emr.models import Patient

    patient = Patient.objects.create(
        full_name="Maria Silva",
        cpf=cpf,
        birth_date="1985-06-15",
        gender="F",
        whatsapp=phone,
    )
    return patient


class OptInCascadeModelTests(TenantTestCase):
    """Tests that WhatsAppContact.do_opt_in triggers the cascade correctly."""

    def test_do_opt_in_with_patient_enqueues_welcome_task(self):
        """When a contact with a linked patient opts in, the welcome task is delayed
        and an opt_in_completed AuditLog is written."""
        patient = _make_patient()
        contact = WhatsAppContact.objects.create(phone="5511900000099", patient=patient)

        with (
            patch(
                "apps.whatsapp.services.opt_in.transaction.on_commit",
                side_effect=lambda fn: fn(),
            ),
            patch("apps.whatsapp.tasks.send_post_opt_in_welcome.delay") as mock_delay,
        ):
            contact.do_opt_in()

        # Task must have been enqueued exactly once
        mock_delay.assert_called_once()
        args = mock_delay.call_args[0]
        self.assertEqual(args[0], str(contact.id))  # first arg is contact_id
        correlation_id = args[1]
        self.assertIsNotNone(correlation_id)

        # AuditLog with action=opt_in_completed must exist
        log = AuditLog.objects.get(
            action="opt_in_completed",
            resource_type="whatsapp_contact",
            resource_id=str(contact.id),
        )
        self.assertEqual(log.new_data["phone"], contact.phone)
        self.assertEqual(log.new_data["patient_id"], str(patient.id))
        self.assertEqual(log.new_data["correlation_id"], correlation_id)

    def test_do_opt_in_without_patient_skips_welcome(self):
        """When a contact has no linked patient, no task is enqueued and no audit written."""
        contact = WhatsAppContact.objects.create(phone="5511900000098")
        self.assertIsNone(contact.patient_id)

        with (
            patch(
                "apps.whatsapp.services.opt_in.transaction.on_commit",
                side_effect=lambda fn: fn(),
            ),
            patch("apps.whatsapp.tasks.send_post_opt_in_welcome.delay") as mock_delay,
        ):
            contact.do_opt_in()

        mock_delay.assert_not_called()
        self.assertFalse(
            AuditLog.objects.filter(
                action="opt_in_completed",
                resource_type="whatsapp_contact",
                resource_id=str(contact.id),
            ).exists()
        )


class OptInWelcomeTaskTests(TenantTestCase):
    """Tests for the send_post_opt_in_welcome Celery task.

    __wrapped__ on a Celery bind=True task is a bound method where 'self' is the
    task object. Call as send_post_opt_in_welcome.__wrapped__(contact_id, corr_id).

    get_gateway is imported inside the task body, so patch at the source module:
    apps.whatsapp.gateway.get_gateway.
    """

    def _make_opted_in_contact(self, phone="5511900000097", cpf="65123478907"):
        patient = _make_patient(cpf=cpf, phone=phone)
        contact = WhatsAppContact.objects.create(phone=phone, patient=patient, opt_in=True)
        return contact

    def test_welcome_task_sends_message_on_happy_path(self):
        """Happy path: gateway.send_text is called and opt_in_welcome_sent audit is written."""
        contact = self._make_opted_in_contact()
        correlation_id = "test-corr-id-happy"

        mock_gateway = MagicMock()
        # Patch at the source module (task imports get_gateway locally)
        with patch("apps.whatsapp.gateway.get_gateway", return_value=mock_gateway):
            send_post_opt_in_welcome.__wrapped__(str(contact.id), correlation_id)

        mock_gateway.send_text.assert_called_once()
        call_args = mock_gateway.send_text.call_args[0]
        self.assertEqual(call_args[0], contact.phone)
        self.assertIn("Maria Silva", call_args[1])

        log = AuditLog.objects.get(
            action="opt_in_welcome_sent",
            resource_type="whatsapp_contact",
            resource_id=str(contact.id),
        )
        self.assertEqual(log.new_data["correlation_id"], correlation_id)

    def test_welcome_task_fail_open_writes_failed_audit(self):
        """When retries are exhausted, opt_in_welcome_failed audit is written (fail-open).

        We patch send_text to raise, and patch self.retry to raise MaxRetriesExceededError
        immediately (simulating exhausted retries) so the fail-open path runs synchronously.
        """
        from celery.exceptions import MaxRetriesExceededError

        contact = self._make_opted_in_contact(phone="5511900000096", cpf="54687419006")
        correlation_id = "test-corr-id-fail"

        mock_gateway = MagicMock()
        mock_gateway.send_text.side_effect = RuntimeError("network down")

        with (
            patch("apps.whatsapp.gateway.get_gateway", return_value=mock_gateway),
            patch.object(
                send_post_opt_in_welcome,
                "retry",
                side_effect=MaxRetriesExceededError(),
            ),
        ):
            send_post_opt_in_welcome.__wrapped__(str(contact.id), correlation_id)

        log = AuditLog.objects.get(
            action="opt_in_welcome_failed",
            resource_type="whatsapp_contact",
            resource_id=str(contact.id),
        )
        self.assertEqual(log.new_data["reason"], "max_retries_exceeded")
        self.assertEqual(log.new_data["correlation_id"], correlation_id)

    def test_welcome_task_no_op_when_opt_in_reverted(self):
        """If contact.opt_in is False at task execution time, no message is sent."""
        contact = self._make_opted_in_contact(phone="5511900000095", cpf="95524361072")
        # Revoke opt-in between enqueue and run
        contact.opt_in = False
        contact.save(update_fields=["opt_in"])

        mock_gateway = MagicMock()
        with patch("apps.whatsapp.gateway.get_gateway", return_value=mock_gateway):
            send_post_opt_in_welcome.__wrapped__(str(contact.id), "corr-reverted")

        mock_gateway.send_text.assert_not_called()
        self.assertFalse(
            AuditLog.objects.filter(
                action="opt_in_welcome_sent",
                resource_type="whatsapp_contact",
                resource_id=str(contact.id),
            ).exists()
        )
