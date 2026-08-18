"""
Tests for the core.E008 production system check (Onda 2 / item 2.6).

Covers:
  - check_catalogs_loaded_in_production: no errors when every essential catalog
    has at least one row, exactly one core.E008 Error naming the empty ones
    otherwise, and prod-gated (non-production environments are silent even
    with every catalog empty — this is the normal state in dev/CI).
  - the DatabaseError/LookupError branch degrades to a core.W002 Warning
    instead of a false "catalog empty" Error.
"""

from __future__ import annotations

from unittest.mock import patch

from django.test import override_settings

from apps.core.models import (
    AnvisaPresentation,
    AnvisaProduct,
    CBOCode,
    CID10Code,
    CIDOMorphology,
    CNESEstablishment,
    SIGTAPProcedure,
    TUSSCode,
    UcumUnit,
)
from apps.test_utils import TenantTestCase


def _clear_all_catalogs():
    AnvisaPresentation.objects.all().delete()
    AnvisaProduct.objects.all().delete()
    CBOCode.objects.all().delete()
    CID10Code.objects.all().delete()
    CIDOMorphology.objects.all().delete()
    CNESEstablishment.objects.all().delete()
    SIGTAPProcedure.objects.all().delete()
    TUSSCode.objects.all().delete()
    UcumUnit.objects.all().delete()


def _seed_all_catalogs_except(skip_model=None):
    """Create one row in every essential catalog model except ``skip_model``."""
    if skip_model is not CID10Code:
        CID10Code.objects.create(code="A00", description="Cólera", category="A00-A09")
    if skip_model is not TUSSCode:
        TUSSCode.objects.create(
            code="10101012", description="Consulta", group="procedimento", version="2024-01"
        )
    if skip_model is not CNESEstablishment:
        CNESEstablishment.objects.create(code="1000001", display="Hospital São João")
    if skip_model is not AnvisaProduct:
        AnvisaProduct.objects.create(code="1000000000000", display="Dipirona")
    if skip_model is not AnvisaPresentation:
        product = AnvisaProduct.objects.first() or AnvisaProduct.objects.create(
            code="1000000000000", display="Dipirona"
        )
        AnvisaPresentation.objects.create(
            code="1000000000001", product=product, ean="7891000000000"
        )
    if skip_model is not SIGTAPProcedure:
        SIGTAPProcedure.objects.create(code="0301010013", display="Consulta médica")
    if skip_model is not CBOCode:
        CBOCode.objects.create(code="225125", display="Médico clínico")
    if skip_model is not CIDOMorphology:
        CIDOMorphology.objects.create(code="8500/3", display="Carcinoma ductal invasivo")
    if skip_model is not UcumUnit:
        UcumUnit.objects.create(code="mg", display="milligram")


class CatalogsLoadedProductionCheckTests(TenantTestCase):
    """Direct unit tests — call the check function, bypass the registry."""

    def setUp(self):
        _clear_all_catalogs()

    def _run(self, **settings_overrides):
        from apps.core.checks import check_catalogs_loaded_in_production

        with override_settings(**settings_overrides):
            return check_catalogs_loaded_in_production(app_configs=None)

    def test_production_with_every_catalog_loaded_returns_no_errors(self):
        _seed_all_catalogs_except(skip_model=None)
        errors = self._run(ENVIRONMENT="production")
        self.assertEqual(errors, [])

    def test_production_with_tuss_empty_returns_e008(self):
        _seed_all_catalogs_except(skip_model=TUSSCode)
        errors = self._run(ENVIRONMENT="production")
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, "core.E008")
        self.assertIn("TUSS", errors[0].msg)

    def test_production_with_every_catalog_empty_lists_all_in_hint(self):
        errors = self._run(ENVIRONMENT="production")
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, "core.E008")
        for needle in ("TUSS", "CID-10", "CNES", "ANVISA", "SIGTAP", "CBO", "CID-O", "UCUM"):
            self.assertIn(needle, errors[0].msg)

    def test_development_with_every_catalog_empty_returns_no_errors(self):
        """Empty catalogs are the NORMAL dev/CI state — must never block dev."""
        errors = self._run(ENVIRONMENT="development")
        self.assertEqual(errors, [])

    def test_unset_environment_returns_no_errors(self):
        """Same guard as core.E002/E003/E004: unset ENVIRONMENT is treated as non-prod."""
        with override_settings():
            from django.conf import settings

            if hasattr(settings, "ENVIRONMENT"):
                del settings.ENVIRONMENT
            from apps.core.checks import check_catalogs_loaded_in_production

            errors = check_catalogs_loaded_in_production(app_configs=None)
        self.assertEqual(errors, [])

    def test_lookup_error_degrades_to_warning_not_false_positive_error(self):
        """If a catalog model/table can't be resolved, warn — never claim 'empty'."""
        with patch(
            "django.apps.apps.get_model",
            side_effect=LookupError("core.CID10Code not migrated yet"),
        ):
            errors = self._run(ENVIRONMENT="production")
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, "core.W002")
