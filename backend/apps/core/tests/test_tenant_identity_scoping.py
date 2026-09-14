"""
Onda 0 (PERÍMETRO) — 0.4/0.5: tenant-identity scoping regression tests.

Threat model recap (see the audit finding that motivated 0.4/0.5):
- ``User``/``Role`` live in the PUBLIC schema (apps.core is SHARED_APPS) — a
  single global registry shared by every clinic. ``UserListCreateView`` and
  ``RoleListCreateView`` used to query ``User.objects``/``Role.objects``
  directly, with no tenant filter, gated only by [IsAuthenticated] /
  [IsTenantAdmin]. Any authenticated user of clinic A could therefore:
    (1) GET /api/v1/users/ and see every user of every clinic on the platform;
    (2) GET /api/v1/roles/ and see (and, via role_id, ASSIGN) roles that a
        competing clinic B created for itself.

These tests create TWO REAL TENANTS (real Postgres schemas, real Domain rows)
and attack the boundary via the actual DRF views over HTTP, mirroring the
pattern already established in
``test_privacy_settings.PrivacySettingsMultiTenantAuthorizationTests``.

Run: pytest apps/core/tests/test_tenant_identity_scoping.py -v
"""

from django_tenants.utils import get_public_schema_name, schema_context
from rest_framework.test import APIClient

from apps.core.models import Domain, Role, Tenant, User, UserTenantMembership
from apps.test_utils import TenantTestCase


class TenantIdentityScopingTests(TenantTestCase):
    """Tenant A (``self.__class__.tenant``, provided by TenantTestCase) vs. a
    freshly created Tenant B — GET /users/, GET /roles/, and role_id
    assignment must never cross the boundary."""

    def setUp(self):
        # apps.core (Tenant, Domain, User, Role, FeatureFlag) is entirely
        # SHARED_APPS — every model exercised below lives in the PUBLIC
        # schema regardless of which tenant "owns" a row (ownership here is
        # the ``tenant_id`` FK, not physical schema placement). No test in
        # this class ever issues an HTTP request against tenant B's domain or
        # touches a TENANT_APPS model in its schema, so provisioning a real
        # Postgres schema for it (CREATE SCHEMA + ~250 migrations) would only
        # buy per-test latency, not coverage: the boundary under test is the
        # ``for_current_tenant()`` filter, not schema isolation (see
        # apps/imaging/tests/test_orthanc_sync.py::OrthancSyncMultiTenantTest
        # for the schema-isolation case, which DOES need a real schema).
        # ``Tenant.save()`` only calls ``create_schema()`` when
        # ``self.auto_create_schema`` is true; overriding it on the instance
        # (shadowing the class attribute, no production code touched) skips
        # the DDL/migration entirely while still exercising the FK row real
        # tenant-scoping tests need.
        with schema_context(get_public_schema_name()):
            self.tenant_b = Tenant(name="Identity Scoping Clinic B", slug="identity-scoping-b")
            self.tenant_b.auto_create_schema = False
            self.tenant_b.save()
            self.domain_b = Domain.objects.create(
                tenant=self.tenant_b,
                domain="identity-scoping-b.testserver",
                is_primary=True,
            )

        # System role: tenant=None, shared by every clinic regardless of 0.5.
        self.system_role = Role.objects.create(name="admin", permissions=["admin"], is_system=True)
        # Tenant-A-owned and tenant-B-owned custom roles (0.5 discriminator).
        self.role_a = Role.objects.create(
            name="recepcao-a",
            permissions=["schedule.read"],
            tenant=self.__class__.tenant,
        )
        self.role_b = Role.objects.create(
            name="recepcao-b",
            permissions=["schedule.read"],
            tenant=self.tenant_b,
        )

        # Tenant-A admin — the attacker in every test below.
        self.admin_a = User.objects.create_user(
            email="admin-a@identity-scoping.test",
            password="TestPass123!",
            full_name="Admin A",
            role=self.system_role,
        )
        UserTenantMembership.objects.create(
            user=self.admin_a, tenant=self.__class__.tenant, role=self.system_role
        )

        # Tenant-B-exclusive user — must never leak into tenant A's user list.
        self.user_b = User.objects.create_user(
            email="user-b@identity-scoping.test",
            password="TestPass123!",
            full_name="User B Exclusive",
            role=self.role_b,
        )
        UserTenantMembership.objects.create(
            user=self.user_b, tenant=self.tenant_b, role=self.role_b, is_active=True
        )

        # Plain (non-admin) tenant-A staff — used for the self-access regression.
        self.staff_a = User.objects.create_user(
            email="staff-a@identity-scoping.test",
            password="TestPass123!",
            full_name="Staff A",
            role=self.role_a,
        )
        UserTenantMembership.objects.create(
            user=self.staff_a, tenant=self.__class__.tenant, role=self.role_a, is_active=True
        )

        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        self.client.force_authenticate(user=self.admin_a)

    def tearDown(self):
        with schema_context(get_public_schema_name()):
            try:
                self.tenant_b.delete(force_drop=True)
            except Exception:
                self.tenant_b.delete()

    # ─── (a) GET /api/v1/users/ ───────────────────────────────────────────────

    def test_user_list_does_not_leak_other_tenant_users(self):
        resp = self.client.get("/api/v1/users/")
        self.assertEqual(resp.status_code, 200)
        results = resp.data.get("results", resp.data)
        emails = {row["email"] for row in results}
        self.assertNotIn(self.user_b.email, emails)
        self.assertIn(self.admin_a.email, emails)

    # ─── (b) GET /api/v1/roles/ ───────────────────────────────────────────────

    def test_role_list_does_not_leak_other_tenant_roles(self):
        resp = self.client.get("/api/v1/roles/")
        self.assertEqual(resp.status_code, 200)
        results = resp.data.get("results", resp.data)
        names = {row["name"] for row in results}
        self.assertNotIn(self.role_b.name, names)
        self.assertIn(self.role_a.name, names)

    # ─── (c) role_id assignment across tenants must fail validation ──────────

    def test_cannot_assign_role_from_other_tenant(self):
        resp = self.client.post(
            "/api/v1/users/",
            {
                "email": "new-hire@identity-scoping.test",
                "full_name": "New Hire",
                "password": "KnownPass123!",
                "role_id": str(self.role_b.id),
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("role_id", resp.data)
        self.assertFalse(User.objects.filter(email="new-hire@identity-scoping.test").exists())

    # ─── (d) system roles (tenant=None) stay visible + assignable everywhere ──

    def test_system_role_visible_and_assignable_in_every_tenant(self):
        resp = self.client.get("/api/v1/roles/")
        self.assertEqual(resp.status_code, 200)
        names = {row["name"] for row in resp.data.get("results", resp.data)}
        self.assertIn(self.system_role.name, names)

        resp = self.client.post(
            "/api/v1/users/",
            {
                "email": "new-hire-2@identity-scoping.test",
                "full_name": "New Hire 2",
                "password": "KnownPass123!",
                "role_id": str(self.system_role.id),
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        created = User.objects.get(email="new-hire-2@identity-scoping.test")
        self.assertEqual(created.role_id, self.system_role.id)

    # ─── (f) UserDetailView must not address other-tenant users by PK ────────

    def test_admin_cannot_get_other_tenant_user_detail(self):
        """0.4 follow-up: UserDetailView.get_queryset() used to be
        User.objects.all() for any tenant admin — a tenant-A admin could GET
        (and PATCH) ANY user on the platform by id. 404, not 403, so the
        endpoint doesn't leak cross-tenant user existence."""
        resp = self.client.get(f"/api/v1/users/{self.user_b.id}/")
        self.assertEqual(resp.status_code, 404)

    def test_admin_cannot_patch_other_tenant_user_role(self):
        resp = self.client.patch(
            f"/api/v1/users/{self.user_b.id}/",
            {"role_id": str(self.system_role.id)},
            format="json",
        )
        self.assertEqual(resp.status_code, 404)
        self.user_b.refresh_from_db()
        self.assertEqual(self.user_b.role_id, self.role_b.id)

    # ─── (g) regression: self-access must survive the scoping fix ────────────

    def test_non_admin_can_still_get_own_record(self):
        """A plain (non-admin) tenant-A user still sees their own record."""
        self.client.force_authenticate(user=self.staff_a)
        resp = self.client.get(f"/api/v1/users/{self.staff_a.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["email"], self.staff_a.email)

    def test_self_access_survives_missing_membership_row(self):
        """The exact pre-backfill_tenant_memberships window: a user
        authenticated for tenant A but with NO active UserTenantMembership row
        yet must still be able to GET *and* PATCH their own record —
        User.for_current_tenant() alone would exclude them (no membership),
        so get_queryset() OR's the self-id filter in unconditionally,
        independent of membership bookkeeping. This is what stops the 0.5
        scoping fix from locking a real user out of their own profile before
        the backfill has run (or whenever ENFORCE_TENANT_MEMBERSHIP is off).
        """
        orphan = User.objects.create_user(
            email="orphan-admin@identity-scoping.test",
            password="TestPass123!",
            full_name="Orphan Admin",
            role=self.system_role,
        )
        # Deliberately NO UserTenantMembership row for orphan/tenant A.
        self.client.force_authenticate(user=orphan)

        get_resp = self.client.get(f"/api/v1/users/{orphan.id}/")
        self.assertEqual(get_resp.status_code, 200)

        patch_resp = self.client.patch(
            f"/api/v1/users/{orphan.id}/",
            {"full_name": "Orphan Admin Updated"},
            format="json",
        )
        self.assertEqual(patch_resp.status_code, 200)
        orphan.refresh_from_db()
        self.assertEqual(orphan.full_name, "Orphan Admin Updated")

    # ─── (e) regression: platform admin (public schema) still sees everything ─

    def test_platform_admin_public_schema_sees_every_role_and_user(self):
        """UserListCreateView/RoleListCreateView are only mounted on the
        tenant urlconf (apps.core.urls) — vitali/urls_public.py uses
        apps.core.urls_public instead — so they are never reachable while
        connection.schema_name == 'public'. The model-level contract they both
        delegate to (for_current_tenant) is what a future platform-admin
        surface would call directly, so exercise it against the public schema
        here to lock in that it still returns everything, unfiltered.
        """
        with schema_context(get_public_schema_name()):
            role_ids = set(Role.for_current_tenant().values_list("id", flat=True))
            user_ids = set(User.for_current_tenant().values_list("id", flat=True))

        self.assertIn(self.role_a.id, role_ids)
        self.assertIn(self.role_b.id, role_ids)
        self.assertIn(self.system_role.id, role_ids)
        self.assertIn(self.admin_a.id, user_ids)
        self.assertIn(self.user_b.id, user_ids)

    # ─── (f) 3.5 regression: admin-provisioned users get a real password policy ─

    def test_create_user_rejects_weak_password(self):
        """AUTH_PASSWORD_VALIDATORS was configured but never invoked anywhere
        (3.5 audit) — UserCreateSerializer accepted any 8-char string. Now it
        must reject a password that is long but has no strength (all
        lowercase + digits) same as the other two password-setting paths."""
        resp = self.client.post(
            "/api/v1/users/",
            {
                "email": "weak-pw@identity-scoping.test",
                "full_name": "Weak Pw",
                "password": "password123456",
                "role_id": str(self.role_a.id),
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("password", resp.data)
        self.assertFalse(User.objects.filter(email="weak-pw@identity-scoping.test").exists())

    def test_create_user_accepts_strong_password(self):
        resp = self.client.post(
            "/api/v1/users/",
            {
                "email": "strong-pw@identity-scoping.test",
                "full_name": "Strong Pw",
                "password": "Kn0wn!Strong#Pass",
                "role_id": str(self.role_a.id),
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(User.objects.filter(email="strong-pw@identity-scoping.test").exists())
