"""Regression tests for tenant default roles used by HR onboarding and E2E."""

from django.core.management import call_command

from apps.core.models import Role
from apps.core.permissions import DEFAULT_ROLES
from apps.test_utils import TenantTestCase


HR_ONBOARDING_ROLE_KEYS = {
    "admin",
    "medico",
    "enfermeiro",
    "recepcao",
    "faturista",
    "farmaceutico",
    "dentista",
}


class DefaultRolesContractTests(TenantTestCase):
    def test_default_roles_cover_hr_onboarding_choices(self):
        assert HR_ONBOARDING_ROLE_KEYS.issubset(DEFAULT_ROLES)

    def test_legacy_recepcionista_alias_kept_for_existing_permissions(self):
        assert "recepcionista" in DEFAULT_ROLES
        assert DEFAULT_ROLES["recepcao"] == DEFAULT_ROLES["recepcionista"]

    def test_create_default_roles_seeds_hr_onboarding_roles(self):
        Role.objects.all().delete()

        call_command("create_default_roles", schema=self.__class__.tenant.schema_name)

        seeded = set(Role.objects.values_list("name", flat=True))
        assert HR_ONBOARDING_ROLE_KEYS.issubset(seeded)
