"""
S-061 tests: PilotHealthView — monitoring endpoint.
"""
from django.test import override_settings, TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.core.models import User


class PilotHealthViewTest(TestCase):
    """PilotHealthView — public schema endpoint, platform admin only."""

    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_superuser(
            email="platform_admin@vitali.test",
            password="adminpass",
        )

    def test_unauthenticated_rejected(self):
        """Unauthenticated request returns 401."""
        r = self.client.get("/api/v1/platform/pilot-health/")
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_non_admin_rejected(self):
        """Regular user returns 403."""
        user = User.objects.create_user(email="regular@vitali.test", password="pass")
        self.client.force_authenticate(user)
        r = self.client.get("/api/v1/platform/pilot-health/")
        self.assertIn(r.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_401_UNAUTHORIZED])

    def test_platform_admin_can_access(self):
        """Platform admin gets 200 with correct response shape."""
        self.client.force_authenticate(self.admin)
        r = self.client.get("/api/v1/platform/pilot-health/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn("generated_at", r.data)
        self.assertIn("tenants", r.data)
        self.assertIn("system", r.data)
        # System health keys
        self.assertIn("db_ok", r.data["system"])
        self.assertIn("cache_ok", r.data["system"])
        self.assertTrue(r.data["system"]["db_ok"])
