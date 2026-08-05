"""Tests for the import_tuss management command.

Covers:
  * valid import creates TUSSCode rows from fixture;
  * --dry-run rolls back all writes and does NOT persist a SUCCESS TUSSSyncLog;
  * malformed CSV (missing CODIGO) raises CommandError naming the offending line,
    and commits zero rows;
  * second import of the same file is idempotent (upsert by code).

Fixtures live in backend/apps/core/tests/fixtures/ and contain fabricated
FAKE- rows only — no real ANS clinical data.

Run: python manage.py test apps.core.tests.test_import_tuss
"""

import os

from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.models import TUSSCode, TUSSSyncLog
from apps.test_utils import TenantTestCase

# Absolute path to the fixtures directory alongside this file.
_FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

_SAMPLE_CSV = os.path.join(_FIXTURES_DIR, "tuss_sample.csv")
_MALFORMED_CSV = os.path.join(_FIXTURES_DIR, "tuss_malformed.csv")
_TABELA_CSV = os.path.join(_FIXTURES_DIR, "tuss_sample_tabela.csv")
_ANVISA_CSV = os.path.join(_FIXTURES_DIR, "tuss_sample_anvisa.csv")

# tuss_sample.csv has 3 fabricated FAKE- data rows (CODIGO: 10101010, 20202020, 30303030).
_SAMPLE_ROW_COUNT = 3


class ImportTussValidImportTests(TenantTestCase):
    """Happy-path: valid CSV creates the expected TUSSCode rows."""

    def test_valid_import_creates_rows(self):
        """Importing tuss_sample.csv creates exactly 3 TUSSCode rows."""
        count_before = TUSSCode.objects.count()
        call_command("import_tuss", file=_SAMPLE_CSV, tuss_version="2024-01")
        self.assertEqual(TUSSCode.objects.count(), count_before + _SAMPLE_ROW_COUNT)

    def test_imported_codes_have_correct_version(self):
        """All imported rows carry the supplied tuss_version label."""
        call_command("import_tuss", file=_SAMPLE_CSV, tuss_version="2024-01")
        self.assertTrue(TUSSCode.objects.filter(version="2024-01").count() >= _SAMPLE_ROW_COUNT)

    def test_idempotent_upsert(self):
        """Importing the same file twice does not grow the TUSSCode count."""
        call_command("import_tuss", file=_SAMPLE_CSV, tuss_version="2024-01")
        count_after_first = TUSSCode.objects.count()
        call_command("import_tuss", file=_SAMPLE_CSV, tuss_version="2024-01")
        self.assertEqual(TUSSCode.objects.count(), count_after_first)


class ImportTussDryRunTests(TenantTestCase):
    """--dry-run rolls back all DB writes and does not persist a SUCCESS log."""

    def test_dry_run_writes_nothing(self):
        """dry_run=True leaves TUSSCode count unchanged and writes no SUCCESS log."""
        count_before = TUSSCode.objects.count()
        log_count_before = TUSSSyncLog.objects.filter(status=TUSSSyncLog.Status.SUCCESS).count()

        call_command("import_tuss", file=_SAMPLE_CSV, tuss_version="2024-01", dry_run=True)

        # No new TUSSCode rows.
        self.assertEqual(TUSSCode.objects.count(), count_before)
        # No new SUCCESS log entry.
        self.assertEqual(
            TUSSSyncLog.objects.filter(status=TUSSSyncLog.Status.SUCCESS).count(),
            log_count_before,
        )


class ImportTussTableNumberTests(TenantTestCase):
    """A coluna TABELA da fonte alimenta TUSSCode.table_number.

    `table_number` existe desde S1-T2 para a valoração CBHPM distinguir um
    procedimento (tabela 22) de uma diária/taxa (18) ou medicamento (20), mas o
    importer nunca o preenchia — todo código importado ficava com o campo NULL e
    a distinção só existia no papel. As tabelas do padrão TISS são publicadas em
    arquivos separados por número, então o número é fato da fonte, não inferência.
    """

    def test_tabela_column_populates_table_number(self):
        call_command("import_tuss", file=_TABELA_CSV, tuss_version="202607")
        self.assertEqual(TUSSCode.objects.get(code="10101010").table_number, "22")
        self.assertEqual(TUSSCode.objects.get(code="60015071").table_number, "18")
        self.assertEqual(TUSSCode.objects.get(code="90035593").table_number, "20")

    def test_absent_tabela_column_leaves_table_number_untouched(self):
        """Sem a coluna TABELA, o campo NÃO é sobrescrito.

        Mesma regra dos metadados de compatibilidade clínica: um export legado
        (CODIGO;DESCRICAO;GRUPO;SUBGRUPO) não pode apagar o número de tabela já
        gravado por um import anterior que o trazia.
        """
        call_command("import_tuss", file=_TABELA_CSV, tuss_version="202607")
        TUSSCode.objects.filter(code="10101010").update(description="antes")
        call_command("import_tuss", file=_SAMPLE_CSV, tuss_version="2024-01")
        self.assertEqual(TUSSCode.objects.get(code="10101010").table_number, "22")


class ImportTussAnvisaBridgeTests(TenantTestCase):
    """A coluna REGISTRO ANVISA da tabela 20 vira ``TUSSCode.anvisa_registro``.

    É a ponte que faltava entre o medicamento faturado e o medicamento
    registrado. Material já tinha caminho — ``SimproMaterial`` carrega o TUSS,
    então ``bill_surgical_materials_for_case`` precifica pela PriceTable. Para
    medicamento não havia nada: ``Drug.anvisa_code`` é texto solto e o catálogo
    ANVISA não sabia dizer qual TUSS cobrar.

    A ANS publica o registro ANVISA em 100% dos 44.574 termos da tabela 20, então
    a ligação é **fato da fonte**, não inferência nossa.
    """

    def test_registro_anvisa_column_populates_the_bridge(self):
        call_command("import_tuss", file=_ANVISA_CSV, tuss_version="202607")
        med = TUSSCode.objects.get(code="90035593")
        self.assertEqual(med.anvisa_registro, "1018003900019")
        self.assertEqual(med.table_number, "20")

    def test_absent_column_leaves_the_bridge_untouched(self):
        """Export legado sem a coluna não pode apagar a ponte já gravada."""
        call_command("import_tuss", file=_ANVISA_CSV, tuss_version="202607")
        call_command("import_tuss", file=_SAMPLE_CSV, tuss_version="2024-01")
        self.assertEqual(TUSSCode.objects.get(code="90035593").anvisa_registro, "1018003900019")

    def test_lookup_finds_the_tuss_of_a_registered_drug(self):
        from apps.core.terminology import tuss_for_anvisa_registro

        call_command("import_tuss", file=_ANVISA_CSV, tuss_version="202607")
        found = tuss_for_anvisa_registro("1018003900019")
        self.assertIsNotNone(found)
        self.assertEqual(found.code, "90035593")

    def test_lookup_falls_back_from_presentation_to_product(self):
        """O registro de 13 dígitos é produto (9) + apresentação (4).

        Uma dispensação costuma conhecer só o produto. Quando não há TUSS para a
        apresentação exata, cair para qualquer apresentação do MESMO produto é
        melhor que não faturar — é o mesmo medicamento.
        """
        from apps.core.terminology import tuss_for_anvisa_registro

        call_command("import_tuss", file=_ANVISA_CSV, tuss_version="202607")
        found = tuss_for_anvisa_registro("101800390")  # só o produto, 9 dígitos
        self.assertIsNotNone(found)
        self.assertEqual(found.code, "90035593")

    def test_lookup_is_blank_safe_and_never_guesses(self):
        from apps.core.terminology import tuss_for_anvisa_registro

        call_command("import_tuss", file=_ANVISA_CSV, tuss_version="202607")
        self.assertIsNone(tuss_for_anvisa_registro(""))
        self.assertIsNone(tuss_for_anvisa_registro(None))
        self.assertIsNone(tuss_for_anvisa_registro("9999999999999"))


class ImportTussMalformedTests(TenantTestCase):
    """Per-line error collection: malformed rows raise CommandError, commit nothing."""

    def test_malformed_csv_reports_lines_no_partial(self):
        """Empty CODIGO raises CommandError naming the offending line; 0 rows committed."""
        count_before = TUSSCode.objects.count()

        with self.assertRaises(CommandError) as ctx:
            call_command("import_tuss", file=_MALFORMED_CSV, tuss_version="2024-01")

        # The error message must mention the TRUE physical line number.
        # tuss_malformed.csv layout:
        #   line 1: # comment (skipped)
        #   line 2: header
        #   line 3: 10101010;FAKE-Consulta basica;... (data row 0, good)
        #   line 4: ;FAKE-Row with missing code;... (data row 1, bad — empty CODIGO)
        # Physical line of the bad row is 4.
        error_msg = str(ctx.exception)
        self.assertIn("Line 4", error_msg)

        # No rows committed — the transaction was rolled back.
        self.assertEqual(TUSSCode.objects.count(), count_before)
