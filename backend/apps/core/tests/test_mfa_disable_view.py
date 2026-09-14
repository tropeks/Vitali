"""
3.10 regression: MFADisableView must be gated on real platform-admin status
(is_platform_admin / is_superuser), not the Django-admin-site ``is_staff``
flag. Before the fix, any tenant user who happened to have is_staff=True
(never set by normal provisioning, but not enforced either) could delete the
TOTPDevice of ANY user on the platform, in ANY tenant — the user_id lookup is
deliberately global (Vitali-ops action), which is exactly what made the
is_staff gate dangerous.

Run: pytest apps/core/tests/test_mfa_disable_view.py -v
"""

from apps.core.mfa import get_or_create_device
from apps.core.models import Role, TOTPDevice, User
from apps.test_utils import TenantTestCase

PW = "Str0ng!Pass#2024"


class MFADisableViewPermissionTests(TenantTestCase):
    def setUp(self):
        from rest_framework.test import APIClient

        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain

        self.target = User.objects.create_user(
            email="mfa-target@clinic.test", full_name="Target", password=PW
        )
        device = get_or_create_device(self.target)
        device.is_active = True
        device.save(update_fields=["is_active"])

    def _post_disable(self, user):
        self.client.force_authenticate(user=user)
        return self.client.post(
            "/api/v1/auth/mfa/disable/", {"user_id": str(self.target.id)}, format="json"
        )

    def test_bare_is_staff_no_longer_disables_mfa(self):
        """is_staff=True with no admin role/superuser must be rejected."""
        bare_staff = User.objects.create_user(
            email="bare-staff@clinic.test",
            full_name="Bare Staff",
            password=PW,
            is_staff=True,
        )
        resp = self._post_disable(bare_staff)
        self.assertEqual(resp.status_code, 403)
        self.target.refresh_from_db()
        self.assertTrue(self.target.totp_device.is_active)

    def test_tenant_admin_role_alone_is_not_enough(self):
        """A tenant-admin role (role_has_admin_capability) is NOT the same as
        platform admin — this endpoint is a Vitali-ops action (unscoped
        cross-tenant lookup), so it must stay is_superuser-gated."""
        admin_role = Role.objects.create(name="admin", permissions=["admin"], is_system=True)
        tenant_admin = User.objects.create_user(
            email="tenant-admin@clinic.test",
            full_name="Tenant Admin",
            password=PW,
            role=admin_role,
        )
        resp = self._post_disable(tenant_admin)
        self.assertEqual(resp.status_code, 403)

    def test_platform_admin_can_disable_mfa(self):
        platform_admin = User.objects.create_user(
            email="platform-admin@clinic.test",
            full_name="Platform Admin",
            password=PW,
            is_staff=True,
            is_superuser=True,
        )
        resp = self._post_disable(platform_admin)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(TOTPDevice.objects.filter(user=self.target).exists())
