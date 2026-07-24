"""
Regression tests for the A01 privilege-escalation / IDOR findings on the
Role and User management endpoints.

Threat model recap:
- RoleListCreateView / UserDetailView were [IsAuthenticated] only, and
  authorization keyed off the user-settable ``role.name == "admin"``. Any
  authenticated tenant user could POST a role named "admin" (or with an
  ``admin`` permission) and PATCH their own ``role_id`` to become tenant admin,
  and could read/edit ANY user (IDOR).

These tests lock in:
- non-admin POST /roles/           → 403
- non-admin PATCH another user     → 403 (write is admin-gated)
- non-admin cannot change own role → role unchanged
- non-admin GET another user       → not visible (404, IDOR fix)
- canonical / is_system admin STILL passes HasPermission("admin") — guards
  against re-introducing the commit-7e921c3 under-grant.
- admin CAN create roles and reassign role_id (legit flow preserved).
"""

from rest_framework.test import APIClient, APIRequestFactory

from apps.core.models import Role, User
from apps.core.permissions import HasPermission, role_has_admin_capability
from apps.test_utils import TenantTestCase


class RBACPrivilegeEscalationTests(TenantTestCase):
    def setUp(self):
        super().setUp()
        # A canonical, system-provisioned admin role (mirrors DEFAULT_ROLES).
        self.admin_role = Role.objects.create(
            name="admin", permissions=["admin", "users.write", "roles.write"], is_system=True
        )
        # A non-privileged clinician role.
        self.clinician_role = Role.objects.create(
            name="medico", permissions=["emr.read", "emr.write"]
        )

        self.admin = User.objects.create_user(
            email="admin@clinic.test",
            password="TestPass123!",
            full_name="Clinic Admin",
            role=self.admin_role,
        )
        self.clinician = User.objects.create_user(
            email="doc@clinic.test",
            password="TestPass123!",
            full_name="Dr Non Admin",
            role=self.clinician_role,
        )
        self.victim = User.objects.create_user(
            email="victim@clinic.test",
            password="TestPass123!",
            full_name="Victim User",
            role=self.clinician_role,
        )

        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain

    # ─── Finding 1: role creation is admin-only ──────────────────────────────

    def test_non_admin_cannot_create_role(self):
        self.client.force_authenticate(user=self.clinician)
        resp = self.client.post(
            "/api/v1/roles/", {"name": "admin", "permissions": ["admin"]}, format="json"
        )
        self.assertEqual(resp.status_code, 403)

    def test_non_admin_cannot_create_role_named_admin_and_escalate(self):
        """The full exploit chain must fail at step 1 (role creation)."""
        self.client.force_authenticate(user=self.clinician)
        resp = self.client.post(
            "/api/v1/roles/",
            {"name": "admin", "permissions": ["admin", "users.write"]},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)
        # No forged role landed in the DB.
        self.assertFalse(
            Role.objects.filter(name="admin", is_system=False).exists(),
        )

    def test_non_admin_cannot_create_user_with_admin_role(self):
        """Secondary escalation route: POST /users/ provisioning a new user bound
        to the admin role (with a known password) must be admin-only."""
        self.client.force_authenticate(user=self.clinician)
        resp = self.client.post(
            "/api/v1/users/",
            {
                "email": "backdoor@clinic.test",
                "full_name": "Backdoor Admin",
                "password": "KnownPass123!",
                "role_id": str(self.admin_role.id),
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(User.objects.filter(email="backdoor@clinic.test").exists())

    def test_admin_can_create_user(self):
        """Legit admin provisioning flow preserved."""
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(
            "/api/v1/users/",
            {
                "email": "newstaff@clinic.test",
                "full_name": "New Staff",
                "password": "KnownPass123!",
                "role_id": str(self.clinician_role.id),
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(User.objects.filter(email="newstaff@clinic.test").exists())

    def test_admin_can_create_role(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(
            "/api/v1/roles/",
            {"name": "recepcao", "permissions": ["schedule.read"]},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        # is_system is read-only — a created role is never a system role.
        self.assertFalse(resp.data["is_system"])

    # ─── Finding 2: IDOR + mass-assignment on UserDetailView ─────────────────

    def test_non_admin_cannot_read_another_user(self):
        """IDOR: a non-admin only sees their own record (queryset scoping → 404)."""
        self.client.force_authenticate(user=self.clinician)
        resp = self.client.get(f"/api/v1/users/{self.victim.id}/")
        self.assertEqual(resp.status_code, 404)

    def test_non_admin_can_read_self(self):
        self.client.force_authenticate(user=self.clinician)
        resp = self.client.get(f"/api/v1/users/{self.clinician.id}/")
        self.assertEqual(resp.status_code, 200)

    def test_non_admin_cannot_patch_another_user(self):
        self.client.force_authenticate(user=self.clinician)
        resp = self.client.patch(
            f"/api/v1/users/{self.victim.id}/",
            {"role_id": str(self.admin_role.id)},
            format="json",
        )
        self.assertIn(resp.status_code, (403, 404))
        self.victim.refresh_from_db()
        self.assertEqual(self.victim.role_id, self.clinician_role.id)

    def test_non_admin_cannot_change_own_role(self):
        """The core escalation: self-PATCH of role_id must not stick."""
        self.client.force_authenticate(user=self.clinician)
        resp = self.client.patch(
            f"/api/v1/users/{self.clinician.id}/",
            {"role_id": str(self.admin_role.id)},
            format="json",
        )
        self.assertIn(resp.status_code, (403, 404))
        self.clinician.refresh_from_db()
        self.assertEqual(self.clinician.role_id, self.clinician_role.id)

    def test_admin_can_reassign_role(self):
        """Legit admin flow preserved: admin reassigns a user's role_id."""
        self.client.force_authenticate(user=self.admin)
        resp = self.client.patch(
            f"/api/v1/users/{self.victim.id}/",
            {"role_id": str(self.admin_role.id)},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.victim.refresh_from_db()
        self.assertEqual(self.victim.role_id, self.admin_role.id)

    # ─── Guard against re-introducing the commit-7e921c3 under-grant ─────────

    def test_canonical_admin_with_admin_permission_passes(self):
        request = APIRequestFactory().get("/")
        request.user = self.admin
        self.assertTrue(HasPermission("admin").has_permission(request, None))

    def test_system_admin_role_without_literal_admin_perm_still_passes(self):
        """A pre-existing is_system admin role whose stored permissions predate
        the literal ``admin`` entry must STILL pass HasPermission("admin")."""
        legacy_role = Role.objects.create(name="admin", permissions=[], is_system=True)
        legacy_admin = User.objects.create_user(
            email="legacy-admin@clinic.test",
            password="TestPass123!",
            full_name="Legacy Admin",
            role=legacy_role,
        )
        request = APIRequestFactory().get("/")
        request.user = legacy_admin
        self.assertTrue(HasPermission("admin").has_permission(request, None))

    def test_user_settable_admin_name_is_not_admin_capability(self):
        """A non-system role merely NAMED 'admin' must NOT grant admin — this is
        the forged-role escalation vector."""
        forged = Role.objects.create(name="admin", permissions=["emr.read"], is_system=False)
        self.assertFalse(role_has_admin_capability(forged))

    def test_clinician_role_lacks_admin_capability(self):
        self.assertFalse(role_has_admin_capability(self.clinician_role))
