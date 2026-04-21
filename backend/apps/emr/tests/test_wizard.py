"""
S-054 tests: Tenant onboarding wizard backend endpoints.

Tests:
1. POST /emr/setup/professional/ creates Professional + ScheduleConfig
2. Re-posting is idempotent (update not create)
3. GET /emr/setup/status/ returns correct wizard_complete flag
4. Validation rejects invalid council_type
"""
from django.utils import timezone
from apps.test_utils import TenantTestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.core.models import User
from apps.emr.models import Professional


VALID_PAYLOAD = {
    "council_type": "CRM",
    "council_number": "12345",
    "council_state": "SP",
    "specialty": "Clínica Geral",
    "full_name": "Dra. Ana Costa",
    "working_days": [1, 2, 3, 4, 5],
    "work_start": "08:00",
    "work_end": "18:00",
    "lunch_start": "12:00",
    "lunch_end": "13:00",
    "slot_duration_minutes": 30,
}


class WizardSetupTest(TenantTestCase):
    """Wizard professional setup endpoint tests."""

    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        self.user = User.objects.create_user(
            email="admin@wizard.test",
            password="pass1234",
            is_staff=True,
        )
        self.client.force_authenticate(self.user)

    def test_create_professional_and_schedule(self):
        """POST creates Professional + ScheduleConfig, returns 201."""
        r = self.client.post("/api/v1/emr/setup/professional/", VALID_PAYLOAD, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertIn("professional_id", r.data)
        self.assertTrue(r.data["created"])

        prof = Professional.objects.get(id=r.data["professional_id"])
        self.assertEqual(prof.council_number, "12345")
        self.assertEqual(prof.schedule_config.slot_duration_minutes, 30)
        self.assertEqual(prof.schedule_config.working_days, [1, 2, 3, 4, 5])

    def test_wizard_idempotent_on_repost(self):
        """Re-posting returns 200 with created=False (updates existing)."""
        self.client.post("/api/v1/emr/setup/professional/", VALID_PAYLOAD, format="json")

        updated_payload = {**VALID_PAYLOAD, "specialty": "Cardiologia"}
        r = self.client.post("/api/v1/emr/setup/professional/", updated_payload, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertFalse(r.data["created"])

        # Check only one Professional exists for this user
        self.assertEqual(Professional.objects.filter(user=self.user).count(), 1)

    def test_wizard_status_incomplete(self):
        """GET /emr/setup/status/ returns wizard_complete=False when no professional."""
        r = self.client.get("/api/v1/emr/setup/status/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertFalse(r.data["wizard_complete"])

    def test_wizard_status_complete_after_setup(self):
        """GET /emr/setup/status/ returns wizard_complete=True after setup."""
        self.client.post("/api/v1/emr/setup/professional/", VALID_PAYLOAD, format="json")
        r = self.client.get("/api/v1/emr/setup/status/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertTrue(r.data["wizard_complete"])

    def test_invalid_council_type_rejected(self):
        """POST with invalid council_type returns 400."""
        bad_payload = {**VALID_PAYLOAD, "council_type": "INVALID"}
        r = self.client.post("/api/v1/emr/setup/professional/", bad_payload, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("council_type", str(r.data))

    def test_unauthenticated_rejected(self):
        """Unauthenticated POST returns 401."""
        self.client.force_authenticate(user=None)
        r = self.client.post("/api/v1/emr/setup/professional/", VALID_PAYLOAD, format="json")
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)
