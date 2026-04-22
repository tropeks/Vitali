"""
S-043: DemoModeMiddleware tests.
Run: python manage.py test apps.core.tests.test_demo_mode
"""

from django.conf import settings as django_settings
from rest_framework.test import APIClient

from apps.core.models import Role, User
from apps.test_utils import TenantTestCase


class DemoModeMiddlewareTestCase(TenantTestCase):
    def setUp(self):
        # @override_settings doesn't reliably propagate into middleware with TenantTestCase.
        # Directly patch the settings attribute and restore it via addCleanup.
        django_settings.DEMO_MODE = True
        self.addCleanup(setattr, django_settings, "DEMO_MODE", False)

        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        role = Role.objects.create(name="admin", permissions=["patients.read"])
        self.user = User.objects.create_user(
            email="demo@test.com", password="Test123!", full_name="Demo User", role=role
        )
        self.client.force_authenticate(user=self.user)

    def test_get_allowed_in_demo_mode(self):
        """GET requests always pass through in demo mode."""
        response = self.client.get("/api/v1/core/features/")
        self.assertNotEqual(response.status_code, 403)

    def test_post_blocked_in_demo_mode(self):
        """POST requests return 403 in demo mode."""
        # Use the patients endpoint which definitely exists in the tenant URL conf
        response = self.client.post("/api/v1/patients/", {}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertIn("[DEMO]", response.json().get("detail", ""))

    def test_patch_blocked_in_demo_mode(self):
        """PATCH requests return 403 in demo mode."""
        import uuid

        response = self.client.patch(f"/api/v1/patients/{uuid.uuid4()}/", {}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_auth_refresh_allowed_in_demo_mode(self):
        """POST /api/v1/auth/refresh is whitelisted — must work in demo mode."""
        # A missing/invalid refresh token should 401, not 403 (demo block would be 403)
        response = self.client.post(
            "/api/v1/auth/refresh",
            {"refresh": "invalid_token"},
            format="json",
        )
        self.assertNotEqual(response.status_code, 403)

    def test_auth_login_allowed_in_demo_mode(self):
        """POST /api/v1/auth/login is whitelisted."""
        response = self.client.post(
            "/api/v1/auth/login",
            {"email": "demo@test.com", "password": "wrong"},
            format="json",
        )
        self.assertNotEqual(response.status_code, 403)


class DemoModeOffTestCase(TenantTestCase):
    def setUp(self):
        django_settings.DEMO_MODE = False
        self.addCleanup(setattr, django_settings, "DEMO_MODE", False)

        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        role = Role.objects.create(name="admin2", permissions=["patients.write"])
        self.user = User.objects.create_user(
            email="nodemo@test.com", password="Test123!", full_name="No Demo", role=role
        )
        self.client.force_authenticate(user=self.user)

    def test_post_not_blocked_when_demo_off(self):
        """When DEMO_MODE=False, writes are not intercepted by DemoModeMiddleware."""
        response = self.client.post("/api/v1/patients/", {}, format="json")
        # Should not be 403 from demo mode (might be 400/422 from validation, but not 403)
        if response.status_code == 403:
            self.assertNotIn("[DEMO]", response.json().get("detail", ""))
