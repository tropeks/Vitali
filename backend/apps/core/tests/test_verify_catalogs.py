"""
Tests for the verify_catalogs management command (Onda 2 / item 2.6).

Covers: exits cleanly when every essential catalog has rows, raises
CommandError (non-zero exit when run via `manage.py`) when any is empty,
--allow-empty skips a named catalog, and --json emits a valid, machine
-readable report.
"""

from __future__ import annotations

import json
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.models import CID10Code, CNESEstablishment, TUSSCode, UcumUnit
from apps.test_utils import TenantTestCase


def _clear_essential_catalogs():
    from apps.core.models import (
        AnvisaPresentation,
        AnvisaProduct,
        CBOCode,
        CIDOMorphology,
        SIGTAPProcedure,
    )

    AnvisaPresentation.objects.all().delete()
    AnvisaProduct.objects.all().delete()
    CBOCode.objects.all().delete()
    CID10Code.objects.all().delete()
    CIDOMorphology.objects.all().delete()
    CNESEstablishment.objects.all().delete()
    SIGTAPProcedure.objects.all().delete()
    TUSSCode.objects.all().delete()
    UcumUnit.objects.all().delete()


def _seed_everything():
    from apps.core.models import (
        AnvisaPresentation,
        AnvisaProduct,
        CBOCode,
        CIDOMorphology,
        SIGTAPProcedure,
    )

    CID10Code.objects.create(code="A00", description="Cólera", category="A00-A09")
    TUSSCode.objects.create(
        code="10101012", description="Consulta", group="procedimento", version="2024-01"
    )
    CNESEstablishment.objects.create(code="1000001", display="Hospital São João")
    product = AnvisaProduct.objects.create(code="1000000000000", display="Dipirona")
    AnvisaPresentation.objects.create(code="1000000000001", product=product, ean="7891000000000")
    SIGTAPProcedure.objects.create(code="0301010013", display="Consulta médica")
    CBOCode.objects.create(code="225125", display="Médico clínico")
    CIDOMorphology.objects.create(code="8500/3", display="Carcinoma ductal invasivo")
    UcumUnit.objects.create(code="mg", display="milligram")


class VerifyCatalogsCommandTests(TenantTestCase):
    def setUp(self):
        _clear_essential_catalogs()

    def _run(self, **options):
        out, err = StringIO(), StringIO()
        call_command("verify_catalogs", stdout=out, stderr=err, **options)
        return out.getvalue(), err.getvalue()

    def test_passes_when_every_catalog_loaded(self):
        _seed_everything()
        out, _err = self._run()
        self.assertIn("Todos os catálogos essenciais", out)

    def test_raises_command_error_when_a_catalog_is_empty(self):
        _seed_everything()
        UcumUnit.objects.all().delete()
        with self.assertRaises(CommandError) as ctx:
            self._run()
        self.assertIn("ucum", str(ctx.exception))

    def test_raises_command_error_listing_every_empty_catalog(self):
        # Nothing seeded — every essential catalog is empty.
        with self.assertRaises(CommandError) as ctx:
            self._run()
        message = str(ctx.exception)
        self.assertIn("9 catálogo", message)

    def test_allow_empty_skips_named_catalog(self):
        _seed_everything()
        UcumUnit.objects.all().delete()
        # Must not raise: ucum is explicitly allowed to be empty.
        out, _err = self._run(allow_empty=["ucum"])
        self.assertIn("SKIP", out)

    def test_allow_empty_does_not_mask_other_empty_catalogs(self):
        _seed_everything()
        UcumUnit.objects.all().delete()
        TUSSCode.objects.all().delete()
        with self.assertRaises(CommandError) as ctx:
            self._run(allow_empty=["ucum"])
        self.assertIn("tuss", str(ctx.exception))
        self.assertNotIn("ucum", str(ctx.exception))

    def test_json_report_is_valid_and_reflects_state(self):
        _seed_everything()
        UcumUnit.objects.all().delete()
        out, err = StringIO(), StringIO()
        # --json + failure still raises CommandError (the CI-friendly report is
        # on stdout regardless; the caller decides how to surface the exception).
        try:
            call_command("verify_catalogs", stdout=out, stderr=err, json=True)
        except CommandError:
            pass
        payload = json.loads(out.getvalue())
        self.assertFalse(payload["ok"])
        ucum_row = next(row for row in payload["catalogs"] if row["catalog"] == "ucum")
        self.assertTrue(ucum_row["empty"])
        self.assertEqual(ucum_row["count"], 0)
