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


@override_settings(CACHES=LOCMEM)
class InvitationMembershipTests(TenantTestCase):
    """Accepting an invitation grants membership for the inviting tenant and binds
    the issued token to it (closes the SetPasswordView gap)."""

    def setUp(self):
        cache.clear()
        self.tenant = self.__class__.tenant
        self.role = Role.objects.create(name="medico", permissions=["emr.read"], is_system=True)
        self.user = User.objects.create_user(
            email="invitee@vitali.com", full_name="Invitee", password=PW, role=self.role
        )

    def _make_invitation(self, tenant):
        import hashlib
        from datetime import timedelta

        import jwt
        from django.conf import settings
        from django.utils import timezone

        from apps.core.models import UserInvitation

        expires_at = timezone.now() + timedelta(hours=72)
        token = jwt.encode(
            {
                "user_id": str(self.user.id),
                "purpose": "password_set",
                "exp": int(expires_at.timestamp()),
                "jti": "t",
            },
            settings.SECRET_KEY,
            algorithm="HS256",
        )
        UserInvitation.objects.create(
            user=self.user,
            tenant=tenant,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=expires_at,
        )
        return token

    def test_accept_creates_membership_and_schema_bound_token(self):
        from rest_framework.test import APIClient
        from rest_framework_simplejwt.tokens import AccessToken

        token = self._make_invitation(self.tenant)
        client = APIClient()
        client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        resp = client.post(
            f"/api/v1/auth/set-password/{token}/",
            {"password": "An0ther!Pass#2024"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        # Membership now exists for the inviting tenant…
        self.assertTrue(
            UserTenantMembership.objects.filter(
                user=self.user, tenant=self.tenant, is_active=True
            ).exists()
        )
        # …and the issued access token is stamped with that tenant's schema.
        access = AccessToken(resp.json()["access"])
        self.assertEqual(access[SCHEMA_CLAIM], self.tenant.schema_name)

    @override_settings(ENFORCE_TENANT_MEMBERSHIP=True)
    def test_invited_user_can_authenticate_after_accept_under_enforcement(self):
        from rest_framework.test import APIClient

        token = self._make_invitation(self.tenant)
        client = APIClient()
        client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        client.post(
            f"/api/v1/auth/set-password/{token}/",
            {"password": "An0ther!Pass#2024"},
            format="json",
        )
        # The membership created at accept lets get_user pass under enforcement.
        m = UserTenantMembership.objects.get(user=self.user, tenant=self.tenant)
        self.assertTrue(m.is_active)
        access = tokens_for_user(self.user).access_token
        self.assertEqual(TenantJWTAuthentication().get_user(access).pk, self.user.pk)


@override_settings(CACHES=LOCMEM)
class EffectiveRoleTests(TenantTestCase):
    """M2 — permission resolution uses the per-tenant membership role (gated by
    ENFORCE_TENANT_MEMBERSHIP), falling back to the global User.role."""

    def setUp(self):
        cache.clear()
        self.tenant = self.__class__.tenant
        self.global_role = Role.objects.create(
            name="recepcao", permissions=["schedule.read"], is_system=True
        )
        self.tenant_role = Role.objects.create(
            name="admin", permissions=["schedule.read", "emr.sign"], is_system=True
        )
        self.user = User.objects.create_user(
            email="multi@vitali.com", full_name="Multi", password=PW, role=self.global_role
        )

    def _fresh(self):
        # Reload to drop the per-instance effective-role memo between assertions.
        return User.objects.get(pk=self.user.pk)

    @override_settings(ENFORCE_TENANT_MEMBERSHIP=False)
    def test_flag_off_returns_global_role(self):
        UserTenantMembership.objects.create(
            user=self.user, tenant=self.tenant, role=self.tenant_role, is_active=True
        )
        self.assertEqual(self._fresh().effective_role().pk, self.global_role.pk)

    @override_settings(ENFORCE_TENANT_MEMBERSHIP=True)
    def test_membership_role_overrides_global(self):
        UserTenantMembership.objects.create(
            user=self.user, tenant=self.tenant, role=self.tenant_role, is_active=True
        )
        u = self._fresh()
        self.assertEqual(u.effective_role().pk, self.tenant_role.pk)
        # …and the permission check reflects it (emr.sign only on the tenant role).
        self.assertTrue(u.has_role_permission("emr.sign"))

    @override_settings(ENFORCE_TENANT_MEMBERSHIP=True)
    def test_no_membership_falls_back_to_global(self):
        u = self._fresh()
        self.assertEqual(u.effective_role().pk, self.global_role.pk)
        self.assertFalse(u.has_role_permission("emr.sign"))

    @override_settings(ENFORCE_TENANT_MEMBERSHIP=True)
    def test_membership_without_role_falls_back_to_global(self):
        UserTenantMembership.objects.create(
            user=self.user, tenant=self.tenant, role=None, is_active=True
        )
        self.assertEqual(self._fresh().effective_role().pk, self.global_role.pk)

    @override_settings(ENFORCE_TENANT_MEMBERSHIP=True)
    def test_inactive_membership_falls_back_to_global(self):
        UserTenantMembership.objects.create(
            user=self.user, tenant=self.tenant, role=self.tenant_role, is_active=False
        )
        self.assertEqual(self._fresh().effective_role().pk, self.global_role.pk)

    @override_settings(ENFORCE_TENANT_MEMBERSHIP=True)
    def test_effective_role_is_memoized_per_request(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        UserTenantMembership.objects.create(
            user=self.user, tenant=self.tenant, role=self.tenant_role, is_active=True
        )
        u = self._fresh()
        with CaptureQueriesContext(connection) as ctx:
            u.effective_role()
            u.effective_role()
            u.effective_role()
        membership_queries = [
            q for q in ctx.captured_queries if "core_usertenantmembership" in q["sql"].lower()
        ]
        self.assertEqual(len(membership_queries), 1)
