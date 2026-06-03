"""Regression tests for the TUSSCode clinical-compatibility metadata (glosa
wedge G3b) and the import_tuss optional-column wiring.

Covers:
  * the four new fields default to INERT values (null age window / sex "B" /
    empty CID whitelist) so the downstream clinical_incompat check fires nothing
    until ANS data is populated;
  * import_tuss with the legacy CODIGO;DESCRICAO;GRUPO;SUBGRUPO export leaves the
    metadata at its inert defaults (no fabrication);
  * import_tuss populates the metadata when — and only when — the ANS source row
    carries the optional columns.

Run: python manage.py test apps.core.tests.test_tuss_clinical_compat
"""

import tempfile
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.models import TUSSCode
from apps.test_utils import TenantTestCase


class TUSSClinicalCompatFieldsTests(TenantTestCase):
    """The new fields exist and default to inert values."""

    def test_defaults_are_inert(self):
        code = TUSSCode.objects.create(
            code="10101012", description="Consulta", group="procedimento", version="2024-01"
        )
        code.refresh_from_db()
        self.assertIsNone(code.age_min_days)
        self.assertIsNone(code.age_max_days)
        self.assertEqual(code.sex_allowed, "B")  # B = both/any → no constraint
        self.assertEqual(code.cid10_whitelist, [])


class ImportTussClinicalCompatTests(TenantTestCase):
    """import_tuss only writes the metadata when the ANS source carries it."""

    def _run_import(self, csv_text: str):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as fh:
            fh.write(csv_text)
            path = fh.name
        try:
            call_command("import_tuss", file=path, tuss_version="2024-01")
        finally:
            Path(path).unlink(missing_ok=True)

    def test_legacy_export_leaves_metadata_inert(self):
        # Legacy 4-column ANS export — NO clinical-compat columns. The importer
        # must leave the metadata at its inert defaults (never fabricate).
        self._run_import(
            "CODIGO;DESCRICAO;GRUPO;SUBGRUPO\n10101012;Consulta;procedimento;clinica\n"
        )
        code = TUSSCode.objects.get(code="10101012")
        self.assertIsNone(code.age_min_days)
        self.assertIsNone(code.age_max_days)
        self.assertEqual(code.sex_allowed, "B")
        self.assertEqual(code.cid10_whitelist, [])

    def test_optional_columns_populate_metadata(self):
        # ANS export that DOES carry the optional clinical-compat columns.
        self._run_import(
            "CODIGO;DESCRICAO;GRUPO;SUBGRUPO;IDADE_MIN_DIAS;IDADE_MAX_DIAS;SEXO;CID10_WHITELIST\n"
            "40901114;Parto;procedimento;obstetricia;4015;18250;F;O80,O82\n"
        )
        code = TUSSCode.objects.get(code="40901114")
        self.assertEqual(code.age_min_days, 4015)
        self.assertEqual(code.age_max_days, 18250)
        self.assertEqual(code.sex_allowed, "F")
        self.assertEqual(code.cid10_whitelist, ["O80", "O82"])

    def test_invalid_sex_falls_back_to_both(self):
        # A malformed SEXO value must NOT become a constraint — defaults to "B".
        self._run_import(
            "CODIGO;DESCRICAO;GRUPO;SUBGRUPO;SEXO\n50000470;Exame;procedimento;lab;X\n"
        )
        code = TUSSCode.objects.get(code="50000470")
        self.assertEqual(code.sex_allowed, "B")

    def test_json_array_cid_whitelist(self):
        # The CID whitelist column may also be a JSON array.
        self._run_import(
            "CODIGO;DESCRICAO;GRUPO;SUBGRUPO;CID10_WHITELIST\n"
            '60000470;Exame;procedimento;lab;"[""C50"",""C51""]"\n'
        )
        code = TUSSCode.objects.get(code="60000470")
        self.assertEqual(code.cid10_whitelist, ["C50", "C51"])

    def test_tuss_version_is_required(self):
        # Omitting --tuss-version must error LOUDLY (required), never silently
        # no-op. The old footgun: a caller passing --version hit Django's built-in
        # version action (print + sys.exit(0)) → a silent successful no-op import.
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as fh:
            fh.write("CODIGO;DESCRICAO;GRUPO;SUBGRUPO\n10101012;Consulta;procedimento;clinica\n")
            path = fh.name
        try:
            with self.assertRaises(CommandError):
                call_command("import_tuss", file=path)
        finally:
            Path(path).unlink(missing_ok=True)
        # And nothing was imported.
        self.assertFalse(TUSSCode.objects.filter(code="10101012").exists())

    def test_cid_whitelist_stored_uppercased(self):
        # CID-10 codes are case-insensitive; the stored whitelist must be
        # normalised to uppercase so the downstream comparison is reliable.
        self._run_import(
            "CODIGO;DESCRICAO;GRUPO;SUBGRUPO;CID10_WHITELIST\n"
            "70000470;Exame;procedimento;lab;c50, c51\n"
        )
        code = TUSSCode.objects.get(code="70000470")
        self.assertEqual(code.cid10_whitelist, ["C50", "C51"])
