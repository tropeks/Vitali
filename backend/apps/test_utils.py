"""
Shared test utilities for HealthOS test suite.

TenantTestCase: wraps FastTenantTestCase so the 'fast_test' schema is
created once per session (not per class), avoiding the schema-create/drop
cascade that breaks subsequent TenantTestCase classes.

FastTenantTestCase doesn't set cls.domain when reusing an existing tenant,
so we patch that here.

FastTenantTestCase.setUpClass does NOT call super().setUpClass(), which means
Django's @override_settings class decorators are never applied. We fix that
here by explicitly enabling/disabling _overridden_settings and _modified_settings.

MFATestMixin (DX-05): provides create_totp_device(user) helper so S-062 tests
don't repeat TOTP device setup boilerplate.
"""

from django.test import modify_settings, override_settings
from django_tenants.test.cases import FastTenantTestCase
from django_tenants.utils import get_tenant_domain_model


class MFATestMixin:
    """
    Mixin for test cases that need MFA/TOTP device setup.

    Usage:
        class MyTest(MFATestMixin, TenantTestCase):
            def test_something(self):
                device, backup_codes = self.create_totp_device(self.user)
    """

    def create_totp_device(self, user, activate=True):
        """
        Create an active TOTPDevice for *user*.

        Returns (device, backup_codes) where backup_codes is the plain-text list
        returned on first activation (single-use codes).
        """
        import json

        from django.utils import timezone

        from apps.core.mfa import generate_backup_codes, generate_totp_secret, hash_backup_code
        from apps.core.models import TOTPDevice

        secret = generate_totp_secret()
        plain_codes = generate_backup_codes()
        hashed_codes = [hash_backup_code(c) for c in plain_codes]

        device = TOTPDevice.objects.create(
            user=user,
            encrypted_secret=secret,
            encrypted_backup_codes=json.dumps(hashed_codes),
            is_active=activate,
            confirmed_at=timezone.now() if activate else None,
        )
        return device, plain_codes

    def get_mfa_jwt_tokens(self, user):
        """
        Return (access_token, refresh_token) for *user* with mfa_verified=True claim.
        Useful for tests that hit endpoints guarded by MFARequiredMiddleware.
        """
        from rest_framework_simplejwt.tokens import RefreshToken

        refresh = RefreshToken.for_user(user)
        refresh["mfa_verified"] = True
        return str(refresh.access_token), str(refresh)


class TenantTestCase(FastTenantTestCase):
    """
    Drop-in replacement for django_tenants.test.cases.TenantTestCase.

    Uses FastTenantTestCase under the hood (creates schema once, reuses it)
    and ensures cls.domain is always populated — even when the schema was
    created by a previous test class in the same session.

    Also applies @override_settings and @modify_settings class decorators
    that FastTenantTestCase skips by not calling super().setUpClass().
    """

    @classmethod
    def use_existing_tenant(cls):
        """Called when the fast_test schema already exists. Fetch cls.domain."""
        DomainModel = get_tenant_domain_model()
        domain_str = cls.get_test_tenant_domain()
        try:
            cls.domain = DomainModel.objects.get(
                tenant=cls.tenant,
                domain=domain_str,
            )
        except DomainModel.DoesNotExist:
            cls.domain = DomainModel(tenant=cls.tenant, domain=domain_str)
            cls.domain.save()

    @classmethod
    def setUpClass(cls):
        super().setUpClass()  # FastTenantTestCase.setUpClass (tenant setup)
        # Apply @override_settings / @modify_settings class decorators.
        # FastTenantTestCase skips super().setUpClass() so Django never does this.
        if cls._overridden_settings:
            cls._cls_overridden_context = override_settings(**cls._overridden_settings)
            cls._cls_overridden_context.enable()
        if cls._modified_settings:
            cls._cls_modified_context = modify_settings(cls._modified_settings)
            cls._cls_modified_context.enable()

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "_cls_modified_context"):
            cls._cls_modified_context.disable()
            del cls._cls_modified_context
        if hasattr(cls, "_cls_overridden_context"):
            cls._cls_overridden_context.disable()
            del cls._cls_overridden_context
        super().tearDownClass()  # FastTenantTestCase.tearDownClass
