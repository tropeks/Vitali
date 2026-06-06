"""Tenant-membership enforcement tests (Model B).

Covers the cross-tenant isolation fix: a global User must hold an active
UserTenantMembership for the current tenant, enforced on the request (get_user),
the login path, and the refresh path — all gated by ENFORCE_TENANT_MEMBERSHIP.
"""

from django.core.cache import cache
from django.test import override_settings
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.exceptions import InvalidToken

from apps.core.authentication import TenantJWTAuthentication
from apps.core.models import Role, User, UserTenantMembership
from apps.core.tenant_auth import (
    SCHEMA_CLAIM,
    enforce_refresh_membership,
    login_allowed,
    tokens_for_user,
)
from apps.test_utils import TenantTestCase

PW = "Str0ng!Pass#2024"
LOCMEM = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}


@override_settings(CACHES=LOCMEM)
class TenantMembershipTests(TenantTestCase):
    def setUp(self):
        cache.clear()
        self.tenant = self.__class__.tenant
        self.role = Role.objects.create(name="admin", permissions=["emr.read"], is_system=True)
        self.user = User.objects.create_user(
            email="member@vitali.com", full_name="Member", password=PW, role=self.role
        )

    def _grant(self, user=None):
        return UserTenantMembership.objects.create(
            user=user or self.user, tenant=self.tenant, role=self.role, is_active=True
        )

    def _access_token(self, user=None):
        """An AccessToken minted in the current tenant (carries the schema claim)."""
        return tokens_for_user(user or self.user).access_token

    # ── get_user enforcement ────────────────────────────────────────────────
    @override_settings(ENFORCE_TENANT_MEMBERSHIP=False)
    def test_get_user_noop_when_disabled(self):
        """Flag off → no membership needed (no lockout window during rollout)."""
        token = self._access_token()
        self.assertEqual(TenantJWTAuthentication().get_user(token).pk, self.user.pk)

    @override_settings(ENFORCE_TENANT_MEMBERSHIP=True)
    def test_get_user_denied_without_membership(self):
        token = self._access_token()
        with self.assertRaises(AuthenticationFailed):
            TenantJWTAuthentication().get_user(token)

    @override_settings(ENFORCE_TENANT_MEMBERSHIP=True)
    def test_get_user_allowed_with_membership(self):
        self._grant()
        token = self._access_token()
        self.assertEqual(TenantJWTAuthentication().get_user(token).pk, self.user.pk)

    @override_settings(ENFORCE_TENANT_MEMBERSHIP=True)
    def test_get_user_denied_when_membership_inactive(self):
        m = self._grant()
        m.is_active = False
        m.save(update_fields=["is_active"])
        with self.assertRaises(AuthenticationFailed):
            TenantJWTAuthentication().get_user(self._access_token())

    @override_settings(ENFORCE_TENANT_MEMBERSHIP=True)
    def test_get_user_superuser_bypasses(self):
        su = User.objects.create_user(
            email="root@vitali.com", full_name="Root", password=PW, is_superuser=True
        )
        self.assertEqual(TenantJWTAuthentication().get_user(self._access_token(su)).pk, su.pk)

    @override_settings(ENFORCE_TENANT_MEMBERSHIP=True)
    def test_get_user_rejects_foreign_schema_claim(self):
        """Token minted for another tenant (schema claim mismatch) → 401, even if a
        membership row somehow existed. Defense-in-depth for cross-tenant replay."""
        self._grant()
        token = self._access_token()
        token[SCHEMA_CLAIM] = "some_other_clinic"
        with self.assertRaises(AuthenticationFailed):
            TenantJWTAuthentication().get_user(token)

    @override_settings(ENFORCE_TENANT_MEMBERSHIP=True)
    def test_global_inactive_user_denied_before_membership(self):
        self._grant()
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        with self.assertRaises(AuthenticationFailed):
            TenantJWTAuthentication().get_user(self._access_token())

    # ── login_allowed ─────────────────────────────────────────────────────────
    @override_settings(ENFORCE_TENANT_MEMBERSHIP=False)
    def test_login_allowed_noop_when_disabled(self):
        self.assertTrue(login_allowed(self.user))

    @override_settings(ENFORCE_TENANT_MEMBERSHIP=True)
    def test_login_allowed_requires_membership(self):
        self.assertFalse(login_allowed(self.user))
        self._grant()
        self.assertTrue(login_allowed(self.user))

    # ── refresh guard ─────────────────────────────────────────────────────────
    @override_settings(ENFORCE_TENANT_MEMBERSHIP=True)
    def test_refresh_denied_without_membership(self):
        refresh = tokens_for_user(self.user)
        with self.assertRaises(InvalidToken):
            enforce_refresh_membership(refresh)

    @override_settings(ENFORCE_TENANT_MEMBERSHIP=True)
    def test_refresh_allowed_with_membership(self):
        self._grant()
        enforce_refresh_membership(tokens_for_user(self.user))  # no raise

    @override_settings(ENFORCE_TENANT_MEMBERSHIP=True)
    def test_refresh_rejects_foreign_schema_claim(self):
        self._grant()
        refresh = tokens_for_user(self.user)
        refresh[SCHEMA_CLAIM] = "some_other_clinic"
        with self.assertRaises(InvalidToken):
            enforce_refresh_membership(refresh)

    # ── login endpoint (integration) ────────────────────────────────────────
    @override_settings(ENFORCE_TENANT_MEMBERSHIP=True)
    def test_login_without_membership_returns_generic_401(self):
        """No enumeration oracle: same code as a bad password."""
        from rest_framework.test import APIClient

        client = APIClient()
        client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        resp = client.post(
            "/api/v1/auth/login",
            {"email": "member@vitali.com", "password": PW},
            format="json",
        )
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["error"]["code"], "INVALID_CREDENTIALS")

    @override_settings(ENFORCE_TENANT_MEMBERSHIP=True)
    def test_login_with_membership_succeeds_and_token_has_schema_claim(self):
        from rest_framework.test import APIClient
        from rest_framework_simplejwt.tokens import AccessToken

        self._grant()
        client = APIClient()
        client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        resp = client.post(
            "/api/v1/auth/login",
            {"email": "member@vitali.com", "password": PW},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        access = AccessToken(resp.json()["access"])
        self.assertEqual(access[SCHEMA_CLAIM], self.tenant.schema_name)


@override_settings(CACHES=LOCMEM)
class BackfillTenantMembershipCommandTests(TenantTestCase):
    """The backfill command infers membership from per-tenant data references."""

    def setUp(self):
        self.tenant = self.__class__.tenant
        self.role = Role.objects.create(name="medico", permissions=["emr.read"], is_system=True)
        self.user = User.objects.create_user(
            email="doc@vitali.com", full_name="Doc", password=PW, role=self.role
        )

    def test_backfill_infers_membership_from_professional(self):
        from apps.emr.models import Professional

        Professional.objects.create(
            user=self.user,
            council_type="CRM",
            council_number="1",
            council_state="SP",
            is_active=True,
        )
        self.assertFalse(
            UserTenantMembership.objects.filter(user=self.user, tenant=self.tenant).exists()
        )

        from django.core.management import call_command

        call_command("backfill_tenant_memberships")
        self.assertTrue(
            UserTenantMembership.objects.filter(
                user=self.user, tenant=self.tenant, is_active=True
            ).exists()
        )

    def test_backfill_is_idempotent(self):
        from django.core.management import call_command

        from apps.emr.models import Professional

        Professional.objects.create(
            user=self.user,
            council_type="CRM",
            council_number="2",
            council_state="SP",
            is_active=True,
        )
        call_command("backfill_tenant_memberships")
        call_command("backfill_tenant_memberships")
        self.assertEqual(
            UserTenantMembership.objects.filter(user=self.user, tenant=self.tenant).count(), 1
        )

    def test_backfill_dry_run_writes_nothing(self):
        from django.core.management import call_command

        from apps.emr.models import Professional

        Professional.objects.create(
            user=self.user,
            council_type="CRM",
            council_number="3",
            council_state="SP",
            is_active=True,
        )
        call_command("backfill_tenant_memberships", "--dry-run")
        self.assertFalse(
            UserTenantMembership.objects.filter(user=self.user, tenant=self.tenant).exists()
        )
