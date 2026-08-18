"""
Regression guard for Onda 2 / item 2.7 (docs/DEPTH_BACKLOG.md P1):

seed_demo_data used to plant a fictional core.CNESEstablishment row keyed on
a REAL DATASUS code (CNES 2077469, mislabelled "Hospital das Clínicas" — the
real establishment at that code is HOSP DOM ALVARENGA). Importing the real
CNES catalog afterwards produced a duplicate-by-collision.

This is a static source check, not an integration test: it does not require a
database or tenant schema, so it stays fast and runs anywhere pytest runs.
It fails loudly if:
  1. the exact historical colliding code (2077469) is reintroduced here, or
  2. this command starts creating a SHARED governed-catalog row
     (core.CNESEstablishment / core.UcumUnit / core.TUSSCode / ...) directly,
     unless it uses the reserved, collision-proof prefix documented in the
     command's module docstring ("DEMO-" for numeric catalogs, "DEMO_" for
     UCUM).

See apps/core/management/commands/seed_demo_data.py's module docstring for
the convention this test enforces.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.test import SimpleTestCase

_SEED_COMMAND_PATH = (
    Path(__file__).resolve().parent.parent / "management" / "commands" / "seed_demo_data.py"
)

# Catalog models this command must never write to directly without the
# collision-proof prefix — mirrors ESSENTIAL_CATALOGS in verify_catalogs.py.
_GOVERNED_CATALOG_MODELS = (
    "CID10Code",
    "TUSSCode",
    "CNESEstablishment",
    "AnvisaProduct",
    "AnvisaPresentation",
    "SIGTAPProcedure",
    "CBOCode",
    "CIDOMorphology",
    "UcumUnit",
)

# The exact code that historically collided with a real DATASUS establishment.
_HISTORICAL_COLLISION_CODE = "2077469"


def _strip_module_docstring(source: str) -> str:
    """Return the source with its leading triple-quoted module docstring
    removed, so checks that must only look at EXECUTABLE code (not at prose
    that documents the very bug being guarded against) don't false-positive
    on the docstring's own historical example."""
    marker = '"""'
    start = source.find(marker)
    if start != 0:
        return source  # no leading docstring — nothing to strip
    end = source.find(marker, start + len(marker))
    if end == -1:
        return source
    return source[end + len(marker) :]


class SeedDemoDataCatalogSafetyTests(SimpleTestCase):
    def setUp(self):
        self.source = _SEED_COMMAND_PATH.read_text(encoding="utf-8")
        self.code_only = _strip_module_docstring(self.source)

    def test_seed_command_file_exists(self):
        self.assertTrue(_SEED_COMMAND_PATH.exists(), _SEED_COMMAND_PATH)

    def test_strip_module_docstring_actually_strips_something(self):
        """Sanity check for the helper above: this file DOES have a leading
        docstring, so code_only must be shorter than the full source."""
        self.assertLess(len(self.code_only), len(self.source))

    def test_does_not_reintroduce_the_historical_colliding_code(self):
        """CNES 2077469 (real DATASUS code) must never be hardcoded in the
        executable part of this command again. (It's fine for the module
        docstring above to name it — this checks the code, not the prose.)"""
        self.assertNotIn(
            _HISTORICAL_COLLISION_CODE,
            self.code_only,
            "seed_demo_data.py hardcodes the exact CNES code that historically "
            "collided with a real DATASUS establishment (docs/DEPTH_BACKLOG.md P1). "
            "Never copy a code that 'looks realistic' from documentation — see the "
            "module docstring for the safe (DEMO-prefixed) convention.",
        )

    def test_does_not_construct_governed_catalog_models_directly(self):
        """As of the 2.7 audit this command creates none of the SHARED catalog
        models at all. If a future change adds one, it must go through the
        DEMO-prefixed convention (checked in the next test), not a bare
        ``Model.objects.create(...)`` with a real-looking code — so this test
        only allows the pattern when paired with a DEMO- prefix nearby."""
        for model_name in _GOVERNED_CATALOG_MODELS:
            for match in re.finditer(rf"\b{model_name}\s*(?:\.objects)?\s*\(", self.code_only):
                window_start = max(0, match.start() - 200)
                window_end = min(len(self.code_only), match.end() + 200)
                window = self.code_only[window_start:window_end]
                self.assertRegex(
                    window,
                    r'["\']DEMO[-_]',
                    f"{model_name} is constructed in seed_demo_data.py without a "
                    "DEMO-/DEMO_-prefixed code nearby. Governed catalog rows created "
                    "by this command MUST use a code that cannot collide with a real "
                    "imported catalog row — see the module docstring convention.",
                )

    def test_module_docstring_documents_the_safe_convention(self):
        """The convention must stay documented, not just enforced in this test."""
        self.assertIn("DEMO-", self.source)
        self.assertIn("collide", self.source.lower())
