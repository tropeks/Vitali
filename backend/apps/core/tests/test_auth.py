"""
Sprint 1 — Auth tests.

Run: python manage.py test apps.core.tests.test_auth --settings=healthos.settings.development
"""
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.core.models import AuditLog, Role, User


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class AuthTestCase(TestCase):
    """Base class — creates a tenant schema (handled by django-tenants test runner)."""

    def setUp(self):
        self.client = APIClient()
        self.role = Role.objects.create(
            name="admin",
            permissions=["emr.read", "emr.write"],
            is_system=True,
        )
        self.user = User.objects.create_user(
            email="test@vitali.com",
            full_name="Test User",
            password="Str0ng!Pass#2024",
            role=self.role,
        )
        self.login_url = "/api/v1/auth/login"
        self.logout_url = "/api/v1/auth/logout"
        self.refresh_url = "/api/v1/auth/refresh"
        self.password_url = "/api/v1/auth/password"

    # ── Login ─────────────────────────────────────────────────────────────────

    def test_login_success(self):
        resp = self.client.post(
            self.login_url,
            {"email": "test@vitali.com", "password": "Str0ng!Pass#2024"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("access", data)
        self.assertIn("refresh", data)
        self.assertEqual(data["user"]["email"], "test@vitali.com")

    def test_login_success_creates_audit_log(self):
        self.client.post(
            self.login_url,
            {"email": "test@vitali.com", "password": "Str0ng!Pass#2024"},
            format="json",
        )
        self.assertTrue(
            AuditLog.objects.filter(action="login_success").exists()
        )

    def test_login_wrong_password(self):
        resp = self.client.post(
            self.login_url,
            {"email": "test@vitali.com", "password": "wrongpassword"},
            format="json",
        )
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["error"]["code"], "INVALID_CREDENTIALS")

    def test_login_wrong_password_creates_failed_audit_log(self):
        self.client.post(
            self.login_url,
            {"email": "test@vitali.com", "password": "wrongpassword"},
            format="json",
        )
        self.assertTrue(
            AuditLog.objects.filter(action="login_failed").exists()
        )

    def test_login_nonexistent_user(self):
        resp = self.client.post(
            self.login_url,
            {"email": "nobody@vitali.com", "password": "password"},
            format="json",
        )
        self.assertEqual(resp.status_code, 401)

    def test_login_inactive_user(self):
        self.user.is_active = False
        self.user.save()
        resp = self.client.post(
            self.login_url,
            {"email": "test@vitali.com", "password": "Str0ng!Pass#2024"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"]["code"], "USER_INACTIVE")

    # ── Account Lockout ───────────────────────────────────────────────────────

    def test_login_account_lockout_after_5_failures(self):
        for _ in range(5):
            self.client.post(
                self.login_url,
                {"email": "test@vitali.com", "password": "wrongpassword"},
                format="json",
            )

        resp = self.client.post(
            self.login_url,
            {"email": "test@vitali.com", "password": "Str0ng!Pass#2024"},
            format="json",
        )
        self.assertEqual(resp.status_code, 429)
        data = resp.json()
        self.assertEqual(data["error"]["code"], "ACCOUNT_LOCKED")
        self.assertIn("retry_after", data["error"])

    def test_lockout_cleared_on_successful_login(self):
        """After a successful login, attempt counter resets."""
        for _ in range(3):
            self.client.post(
                self.login_url,
                {"email": "test@vitali.com", "password": "wrong"},
                format="json",
            )
        # Successful login
        resp = self.client.post(
            self.login_url,
            {"email": "test@vitali.com", "password": "Str0ng!Pass#2024"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)

    # ── Logout ────────────────────────────────────────────────────────────────

    def test_logout_blacklists_token(self):
        login = self.client.post(
            self.login_url,
            {"email": "test@vitali.com", "password": "Str0ng!Pass#2024"},
            format="json",
        )
        tokens = login.json()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

        resp = self.client.post(
            self.logout_url,
            {"refresh": tokens["refresh"]},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)

        # Refresh should now fail (blacklisted)
        resp2 = self.client.post(
            self.refresh_url,
            {"refresh": tokens["refresh"]},
            format="json",
        )
        self.assertIn(resp2.status_code, [401, 400])

    def test_logout_requires_authentication(self):
        resp = self.client.post(self.logout_url, {"refresh": "fake"}, format="json")
        self.assertEqual(resp.status_code, 401)

    # ── Token Refresh ─────────────────────────────────────────────────────────

    def test_refresh_token_rotation(self):
        login = self.client.post(
            self.login_url,
            {"email": "test@vitali.com", "password": "Str0ng!Pass#2024"},
            format="json",
        )
        original_refresh = login.json()["refresh"]

        resp = self.client.post(
            self.refresh_url,
            {"refresh": original_refresh},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        new_tokens = resp.json()
        self.assertIn("access", new_tokens)
        self.assertIn("refresh", new_tokens)
        # New refresh token should differ from original
        self.assertNotEqual(new_tokens["refresh"], original_refresh)

    def test_refresh_with_invalid_token_fails(self):
        resp = self.client.post(
            self.refresh_url,
            {"refresh": "not.a.valid.token"},
            format="json",
        )
        self.assertIn(resp.status_code, [400, 401])

    # ── Change Password ───────────────────────────────────────────────────────

    def test_change_password_success(self):
        login = self.client.post(
            self.login_url,
            {"email": "test@vitali.com", "password": "Str0ng!Pass#2024"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.json()['access']}")

        resp = self.client.put(
            self.password_url,
            {
                "current_password": "Str0ng!Pass#2024",
                "new_password": "N3wStr0ng!Pass#2024",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200)

        # Old password should no longer work
        resp2 = self.client.post(
            self.login_url,
            {"email": "test@vitali.com", "password": "Str0ng!Pass#2024"},
            format="json",
        )
        self.assertEqual(resp2.status_code, 401)

    def test_change_password_wrong_current(self):
        login = self.client.post(
            self.login_url,
            {"email": "test@vitali.com", "password": "Str0ng!Pass#2024"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.json()['access']}")

        resp = self.client.put(
            self.password_url,
            {"current_password": "wrongpassword", "new_password": "N3wStr0ng!Pass#2024"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "WRONG_PASSWORD")

    def test_change_password_weak_new_password(self):
        login = self.client.post(
            self.login_url,
            {"email": "test@vitali.com", "password": "Str0ng!Pass#2024"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.json()['access']}")

        resp = self.client.put(
            self.password_url,
            {"current_password": "Str0ng!Pass#2024", "new_password": "weakpass"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_change_password_creates_audit_log(self):
        login = self.client.post(
            self.login_url,
            {"email": "test@vitali.com", "password": "Str0ng!Pass#2024"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.json()['access']}")
        self.client.put(
            self.password_url,
            {
                "current_password": "Str0ng!Pass#2024",
                "new_password": "N3wStr0ng!Pass#2024",
            },
            format="json",
        )
        self.assertTrue(AuditLog.objects.filter(action="password_changed").exists())


class TenantRegistrationTestCase(TestCase):
    """Tests for S-005 — Tenant Registration API."""

    def setUp(self):
        self.client = APIClient()
        self.url = "/api/v1/platform/tenants"

    def test_tenant_registration_creates_schema(self):
        """Tenant registration returns 201 and creates tenant + domain + admin."""
        with patch("django_tenants.utils.schema_context"):
            resp = self.client.post(
                self.url,
                {
                    "name": "Clínica Exemplo",
                    "slug": "clinica-exemplo",
                    "cnpj": "11222333000181",
                    "admin_email": "admin@clinica.com",
                    "admin_full_name": "Admin Clínica",
                    "admin_password": "Str0ng!Admin#2024",
                },
                format="json",
            )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertIn("tenant", data)
        self.assertIn("domain", data)
        self.assertIn("admin_user", data)
        self.assertIn("trial_ends_at", data)
        self.assertEqual(data["tenant"]["slug"], "clinica-exemplo")
        self.assertEqual(data["tenant"]["status"], "trial")

    def test_tenant_registration_duplicate_slug(self):
        from apps.core.models import Tenant
        Tenant.objects.create(name="Existing", slug="existing-clinic")
        resp = self.client.post(
            self.url,
            {
                "name": "Other",
                "slug": "existing-clinic",
                "admin_email": "a@b.com",
                "admin_full_name": "Admin",
                "admin_password": "Str0ng!Admin#2024",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_tenant_registration_invalid_cnpj(self):
        resp = self.client.post(
            self.url,
            {
                "name": "Test",
                "slug": "test-tenant-2",
                "cnpj": "00000000000000",
                "admin_email": "a@b.com",
                "admin_full_name": "Admin",
                "admin_password": "Str0ng!Admin#2024",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("cnpj", resp.json()["error"]["details"])
