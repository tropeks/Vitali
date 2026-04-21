"""
Tests for S-066 Waitlist management.

Tests:
  - Cancellation notifies next waitlist entry
  - SIM/NÃO response disambiguates booking vs waitlist
  - expire_waitlist_notifications is idempotent
  - WaitlistEntry is scoped to the correct professional
"""
import datetime
from datetime import date, time, timedelta
from unittest.mock import MagicMock, patch, call

from django.utils import timezone

from apps.test_utils import TenantTestCase


class TestWaitlist(TenantTestCase):

    def setUp(self):
        from apps.emr.models import Patient, Professional, WaitlistEntry
        from django.contrib.auth import get_user_model

        User = get_user_model()

        self.user1 = User.objects.create_user(
            email="waitlist_doc1@clinic.test",
            password="TestPass123!",
            full_name="Doc One",
            is_staff=True,
        )
        self.user2 = User.objects.create_user(
            email="waitlist_doc2@clinic.test",
            password="TestPass123!",
            full_name="Doc Two",
        )

        self.professional1 = Professional.objects.create(
            user=self.user1,
            council_type="CRM",
            council_number="111111",
            council_state="SP",
        )
        self.professional2 = Professional.objects.create(
            user=self.user2,
            council_type="CRM",
            council_number="222222",
            council_state="SP",
        )
        self.patient1 = Patient.objects.create(
            full_name="Patient One",
            cpf="111.111.111-11",
            birth_date=datetime.date(1990, 1, 1),
            gender="M",
            phone="5511999990001",
        )
        self.patient2 = Patient.objects.create(
            full_name="Patient Two",
            cpf="222.222.222-22",
            birth_date=datetime.date(1991, 2, 2),
            gender="F",
            phone="5511999990002",
        )

        today = date.today()
        self.entry1 = WaitlistEntry.objects.create(
            patient=self.patient1,
            professional=self.professional1,
            preferred_date_from=today,
            preferred_date_to=today + timedelta(days=30),
            status="waiting",
            priority=0,
        )
        self.entry2 = WaitlistEntry.objects.create(
            patient=self.patient2,
            professional=self.professional1,
            preferred_date_from=today,
            preferred_date_to=today + timedelta(days=30),
            status="waiting",
            priority=1,
        )

    def test_cancellation_notifies_next_waitlist_entry(self):
        """
        notify_next_waitlist_entry picks the first waiting entry (by priority+created_at)
        and sends WhatsApp notification, setting status to 'notified'.
        """
        from apps.emr.tasks_waitlist import notify_next_waitlist_entry
        from apps.emr.models import WaitlistEntry

        slot = {
            "start": (timezone.now() + timedelta(days=1)).isoformat(),
            "end": (timezone.now() + timedelta(days=1, hours=1)).isoformat(),
        }

        with patch("apps.emr.tasks_waitlist.get_gateway") as mock_gw, \
             patch("apps.emr.tasks_waitlist.expire_single_waitlist_entry.apply_async"):
            mock_gateway = MagicMock()
            mock_gw.return_value = mock_gateway

            notify_next_waitlist_entry(str(self.professional1.id), slot)

        # entry1 should be notified (lower priority = higher rank)
        self.entry1.refresh_from_db()
        self.assertEqual(self.entry1.status, "notified")
        self.assertIsNotNone(self.entry1.expires_at)
        self.assertEqual(self.entry1.offered_slot, slot)

        # entry2 should still be waiting
        self.entry2.refresh_from_db()
        self.assertEqual(self.entry2.status, "waiting")

        # WhatsApp should have been sent
        mock_gateway.send_text.assert_called_once()
        call_args = mock_gateway.send_text.call_args
        msg_text = call_args[0][1] if call_args[0] else call_args[1].get("text", "")
        self.assertIn("SIM", msg_text)

    def test_sim_nao_disambiguates_booking_vs_waitlist(self):
        """
        WhatsApp message contains SIM and NÃO keywords for clear action.
        The message must mention the doctor name, date, and time.
        """
        from apps.emr.tasks_waitlist import _format_whatsapp_message

        slot = {
            "start": "2026-04-10T14:00:00",
            "end": "2026-04-10T14:30:00",
        }
        message = _format_whatsapp_message(self.entry1, slot)

        self.assertIn("SIM", message)
        self.assertIn("NÃO", message)
        self.assertIn("10/04/2026", message)
        self.assertIn("14:00", message)
        # Should mention part of the doctor name
        self.assertTrue(
            "One" in message or "Doc" in message,
            f"Expected doctor name in message: {message}"
        )

    def test_waitlist_expire_task_is_idempotent(self):
        """
        expire_waitlist_notifications should not double-expire an entry.
        If entry is already 'expired', it should not process it again.
        """
        from apps.emr.tasks_waitlist import expire_waitlist_notifications
        from apps.emr.models import WaitlistEntry

        # Set entry1 to 'notified' with expired expires_at
        self.entry1.status = "notified"
        self.entry1.notified_at = timezone.now() - timedelta(minutes=40)
        self.entry1.expires_at = timezone.now() - timedelta(minutes=10)
        self.entry1.offered_slot = {"start": "2026-04-10T14:00:00", "end": "2026-04-10T14:30:00"}
        self.entry1.save()

        with patch("apps.emr.tasks_waitlist.notify_next_waitlist_entry.delay"):
            # First call
            count1 = expire_waitlist_notifications()
            # Second call — should not expire again
            count2 = expire_waitlist_notifications()

        self.assertEqual(count1, 1)
        self.assertEqual(count2, 0)  # Already expired — not re-expired

        self.entry1.refresh_from_db()
        self.assertEqual(self.entry1.status, "expired")

    def test_waitlist_entry_scoped_to_correct_professional(self):
        """
        notify_next_waitlist_entry for professional2 should NOT touch entries
        for professional1.
        """
        from apps.emr.tasks_waitlist import notify_next_waitlist_entry

        slot = {
            "start": (timezone.now() + timedelta(days=1)).isoformat(),
            "end": (timezone.now() + timedelta(days=1, hours=1)).isoformat(),
        }

        with patch("apps.emr.tasks_waitlist.get_gateway") as mock_gw, \
             patch("apps.emr.tasks_waitlist.expire_single_waitlist_entry.apply_async"):
            mock_gw.return_value = MagicMock()
            # Notify for professional2 — has no waiting entries
            notify_next_waitlist_entry(str(self.professional2.id), slot)

        # Both entries for professional1 should remain 'waiting'
        self.entry1.refresh_from_db()
        self.entry2.refresh_from_db()
        self.assertEqual(self.entry1.status, "waiting")
        self.assertEqual(self.entry2.status, "waiting")

    def test_waitlist_create_view(self):
        """POST /emr/waitlist/ creates a WaitlistEntry (staff user, explicit patient_id)."""
        from rest_framework.test import APIClient
        from rest_framework_simplejwt.tokens import RefreshToken
        from apps.emr.models import WaitlistEntry

        client = APIClient()
        client.defaults['SERVER_NAME'] = self.__class__.domain.domain
        # user1 is is_staff=True
        refresh = RefreshToken.for_user(self.user1)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}")

        today = date.today()
        data = {
            "patient_id": str(self.patient1.id),
            "professional_id": str(self.professional2.id),
            "preferred_date_from": today.isoformat(),
            "preferred_date_to": (today + timedelta(days=14)).isoformat(),
        }
        response = client.post("/api/v1/waitlist/", data)
        self.assertEqual(response.status_code, 201)
        self.assertTrue(
            WaitlistEntry.objects.filter(
                patient=self.patient1,
                professional=self.professional2,
                status="waiting",
            ).exists()
        )

    def test_waitlist_cancel_view(self):
        """DELETE /emr/waitlist/{id}/ cancels the entry (staff user)."""
        from rest_framework.test import APIClient
        from rest_framework_simplejwt.tokens import RefreshToken

        client = APIClient()
        client.defaults['SERVER_NAME'] = self.__class__.domain.domain
        # user1 is is_staff=True
        refresh = RefreshToken.for_user(self.user1)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}")

        response = client.delete(f"/api/v1/waitlist/{self.entry1.id}/")
        self.assertEqual(response.status_code, 200)

        self.entry1.refresh_from_db()
        self.assertEqual(self.entry1.status, "cancelled")
