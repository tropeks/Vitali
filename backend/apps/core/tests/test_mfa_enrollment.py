"""MFA enrollment enforcement tests (S28-04).

Covers ``apps.core.mfa.mfa_required_for`` (who must use MFA) and
``mfa_enrollment_grace_expired`` (when an un-enrolled covered user gets blocked).
These are the pure-logic primitives the MFARequiredMiddleware builds on.
"""

from datetime import timedelta

from django.test import override_settings
from django.utils import timezone

from apps.core.mfa import mfa_enrollment_grace_expired, mfa_required_for
from apps.core.models import Role, User
from apps.test_utils import TenantTestCase

PW = "Str0ng!Pass#2024"


@override_settings(
    MFA_REQUIRED_ROLES={"admin", "medico", "dentista"},
    MFA_ENROLLMENT_GRACE_DAYS=7,
)
class MFARequiredForTests(TenantTestCase):
    def _user(self, *, role_name=None, is_staff=False, is_superuser=False):
        role = Role.objects.create(name=role_name) if role_name else None
        u = User.objects.create_user(
            email=f"{role_name or 'plain'}-{is_staff}-{is_superuser}@v.com",
            full_name="U",
            password=PW,
            role=role,
        )
        u.is_staff = is_staff
        u.is_superuser = is_superuser
        return u

    def test_superuser_requires_mfa(self):
        self.assertTrue(mfa_required_for(self._user(is_superuser=True)))

    def test_staff_requires_mfa(self):
        self.assertTrue(mfa_required_for(self._user(is_staff=True)))

    def test_sensitive_role_requires_mfa(self):
        self.assertTrue(mfa_required_for(self._user(role_name="medico")))
        self.assertTrue(mfa_required_for(self._user(role_name="admin")))

    def test_regular_role_does_not_require_mfa(self):
        self.assertFalse(mfa_required_for(self._user(role_name="recepcionista")))

    def test_roleless_non_staff_does_not_require_mfa(self):
        self.assertFalse(mfa_required_for(self._user()))


@override_settings(MFA_ENROLLMENT_GRACE_DAYS=7)
class MFAGraceTests(TenantTestCase):
    def _user(self):
        return User.objects.create_user(
            email="grace@v.com", full_name="U", password=PW
        )

    def test_fresh_account_within_grace(self):
        user = self._user()  # created_at = now
        self.assertFalse(mfa_enrollment_grace_expired(user))

    def test_old_account_past_grace(self):
        user = self._user()
        User.objects.filter(pk=user.pk).update(
            created_at=timezone.now() - timedelta(days=8)
        )
        user.refresh_from_db()
        self.assertTrue(mfa_enrollment_grace_expired(user))

    @override_settings(MFA_ENROLLMENT_GRACE_DAYS=0)
    def test_zero_grace_blocks_immediately(self):
        user = self._user()
        self.assertTrue(mfa_enrollment_grace_expired(user))
