"""
E3-T1 — ANVISA drug catalog (core.AnvisaProduct) + import_anvisa importer.

Covers the model (governed fields, normalized_display sync, is_controlled, the
by_ean lookup) and the CatalogImporter-backed management command: idempotent
build, dry-run safety, per-line error isolation (malformed CSV), provenance
logging, and EAN lookup. All local — no network.
"""

from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction

from apps.core.catalog_models import AnvisaPresentation, AnvisaProduct
from apps.core.management.commands.import_anvisa import Command as ImportAnvisa
from apps.core.terminology_base import TerminologyImportLog
from apps.test_utils import TenantTestCase

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SAMPLE = FIXTURES / "anvisa_sample.csv"
MALFORMED = FIXTURES / "anvisa_malformed.csv"
CMED_SAMPLE = FIXTURES / "anvisa_cmed_sample.csv"


def run_import(**options):
    out = StringIO()
    call_command(ImportAnvisa(), stdout=out, stderr=out, **options)
    return out.getvalue()


class TestAnvisaProductModel(TenantTestCase):
    def test_defaults_and_normalized_display_sync(self):
        p = AnvisaProduct.objects.create(
            code="R1", display="Amoxicilina Não-Genérico", dcb="Amoxicilina"
        )
        p.refresh_from_db()
        self.assertEqual(p.system, "anvisa")  # redeclared default
        self.assertTrue(p.active)
        self.assertEqual(p.controlled_class, "none")
        self.assertFalse(p.is_controlled)
        self.assertEqual(p.normalized_display, "amoxicilina nao-generico")

    def test_is_controlled_true_for_tarja(self):
        p = AnvisaProduct.objects.create(code="R2", display="Morfina", controlled_class="A1")
        self.assertTrue(p.is_controlled)

    def test_by_ean_lookup(self):
        p = AnvisaProduct.objects.create(code="R3", display="X", ean="7890000000000")
        self.assertEqual(AnvisaProduct.by_ean("7890000000000"), p)
        self.assertEqual(AnvisaProduct.by_ean(" 7890000000000 "), p)  # trimmed
        self.assertIsNone(AnvisaProduct.by_ean(""))
        self.assertIsNone(AnvisaProduct.by_ean(None))
        self.assertIsNone(AnvisaProduct.by_ean("0000000000000"))

    def test_by_ean_ignores_inactive(self):
        AnvisaProduct.objects.create(
            code="R4", display="Inactive", ean="7891231231231", active=False
        )
        self.assertIsNone(AnvisaProduct.by_ean("7891231231231"))

    def test_dcb_holds_long_multi_substance_composition(self):
        """A DCB de um fitoterápico/dinamizado lista TODAS as substâncias da
        associação e passa de 200 caracteres no dado aberto real da ANVISA (o
        maior hoje tem 380). Truncar apagaria parte da composição — dado
        clínico —, então a coluna tem de comportar a associação inteira.
        """
        composicao = (
            "arnica montana, arnica montana l., calendula officinalis l., "
            "hamamelis virginiana l., echinacea angustifolia, echinacea purpurea, "
            "hypericum perforatum l., symphytum officinale l., achillea millefolium l., "
            "chamomilla recutita l., matricaria chamomilla, bellis perennis l., "
            "hedera helix l., ruta graveolens l., aesculus hippocastanum"
        )
        self.assertGreater(len(composicao), 200)
        p = AnvisaProduct.objects.create(code="R5", display="Fitoterápico", dcb=composicao)
        p.refresh_from_db()
        self.assertEqual(p.dcb, composicao)


class TestAnvisaPresentation(TenantTestCase):
    """Apresentações de um produto ANVISA (fonte: lista de preços CMED).

    O dado aberto de medicamentos da ANVISA é por PRODUTO (registro de 9
    dígitos) e não publica EAN. Quem publica EAN é a lista CMED, cujo registro
    tem 13 dígitos = os 9 do produto + 4 da apresentação. Como a NF-e traz o
    código de barras da CAIXA, o EAN pertence à apresentação, não ao produto —
    daí a tabela filha em vez de um EAN único no produto.
    """

    def setUp(self):
        self.produto = AnvisaProduct.objects.create(
            code="100000001", display="Dipirona 500mg", dcb="dipirona sódica"
        )

    def test_presentation_links_to_product_and_holds_ean(self):
        ap = AnvisaPresentation.objects.create(
            product=self.produto,
            code="1000000010012",
            presentation="500 MG COM CT BL AL PLAS INC X 10",
            ean="7891234567890",
        )
        ap.refresh_from_db()
        self.assertEqual(ap.product, self.produto)
        self.assertEqual(list(self.produto.presentations.all()), [ap])
        self.assertTrue(ap.active)

    def test_by_ean_resolves_product_through_presentation(self):
        """by_ean continua devolvendo o PRODUTO — é o que o matcher de NF-e espera."""
        AnvisaPresentation.objects.create(
            product=self.produto, code="1000000010012", ean="7891234567890"
        )
        self.assertEqual(AnvisaProduct.by_ean("7891234567890"), self.produto)
        self.assertEqual(AnvisaProduct.by_ean(" 7891234567890 "), self.produto)
        self.assertIsNone(AnvisaProduct.by_ean("0000000000000"))

    def test_by_ean_ignores_inactive_presentation_and_product(self):
        AnvisaPresentation.objects.create(
            product=self.produto, code="1000000010013", ean="7899999999999", active=False
        )
        self.assertIsNone(AnvisaProduct.by_ean("7899999999999"))

        outro = AnvisaProduct.objects.create(code="100000002", display="X", active=False)
        AnvisaPresentation.objects.create(product=outro, code="1000000020011", ean="7898888888888")
        self.assertIsNone(AnvisaProduct.by_ean("7898888888888"))

    def test_legacy_ean_on_product_still_resolves(self):
        """O EAN gravado direto no produto (dado antigo) não pode parar de funcionar."""
        legado = AnvisaProduct.objects.create(
            code="100000003", display="Legado", ean="7897777777777"
        )
        self.assertEqual(AnvisaProduct.by_ean("7897777777777"), legado)

    def test_presentation_code_is_unique(self):
        AnvisaPresentation.objects.create(product=self.produto, code="1000000010012")
        with self.assertRaises(IntegrityError), transaction.atomic():
            AnvisaPresentation.objects.create(product=self.produto, code="1000000010012")


class TestImportAnvisaCmed(TenantTestCase):
    """import_anvisa_cmed: carrega as apresentações (EAN/preço) da lista CMED."""

    def setUp(self):
        self.p1 = AnvisaProduct.objects.create(code="100000001", display="FAKE-Produto 1")
        self.p2 = AnvisaProduct.objects.create(code="100000002", display="FAKE-Produto 2")

    def run_cmed(self, **opts):
        out = StringIO()
        call_command("import_anvisa_cmed", stdout=out, stderr=out, **opts)
        return out.getvalue()

    def test_creates_presentations_linked_to_product(self):
        self.run_cmed(source=str(CMED_SAMPLE), cmed_version="2026-08")
        self.assertEqual(self.p1.presentations.count(), 2)
        ap = self.p1.presentations.get(code="1000000010012")
        self.assertEqual(ap.ean, "7891111111111")
        self.assertEqual(str(ap.price_pf), "12.3400")
        self.assertEqual(str(ap.price_pmc), "18.9900")
        self.assertEqual(ap.version, "2026-08")

    def test_blank_price_becomes_null_not_zero(self):
        """Preço ausente na CMED é 'não publicado', não R$ 0,00."""
        self.run_cmed(source=str(CMED_SAMPLE))
        ap = self.p1.presentations.get(code="1000000010013")
        self.assertIsNone(ap.price_pmc)
        semp = self.p2.presentations.get(code="1000000020011")
        self.assertIsNone(semp.price_pf)
        self.assertIsNone(semp.price_pmc)

    def test_orphan_presentation_is_skipped_not_invented(self):
        """Apresentação cujo produto não está no catálogo é pulada — nunca cria produto fantasma."""
        self.run_cmed(source=str(CMED_SAMPLE))
        self.assertFalse(AnvisaProduct.objects.filter(code="999999999").exists())
        self.assertEqual(AnvisaPresentation.objects.filter(code="9999999990001").count(), 0)

    def test_idempotent_rerun(self):
        self.run_cmed(source=str(CMED_SAMPLE))
        self.run_cmed(source=str(CMED_SAMPLE))
        self.assertEqual(AnvisaPresentation.objects.count(), 3)

    def test_dry_run_writes_nothing(self):
        self.run_cmed(source=str(CMED_SAMPLE), dry_run=True)
        self.assertEqual(AnvisaPresentation.objects.count(), 0)

    def test_by_ean_works_end_to_end_after_import(self):
        self.run_cmed(source=str(CMED_SAMPLE))
        self.assertEqual(AnvisaProduct.by_ean("7891111111111"), self.p1)
        self.assertEqual(AnvisaProduct.by_ean("7893333333333"), self.p2)

    def test_missing_file_raises(self):
        with self.assertRaises(CommandError):
            self.run_cmed(source=str(FIXTURES / "nope.csv"))

    def test_all_zero_ean_is_treated_as_absent(self):
        """EAN só de zeros é "sem código de barras", não um código.

        A CMED publica 0000000000000 como placeholder em algumas apresentações.
        Gravá-lo como se fosse EAN faz o matcher de NF-e casar QUALQUER linha sem
        GTIN — que costuma vir zerada — com o produto que calhou de ter o
        placeholder. No staging isso apontava para o KYMRIAH, uma terapia CAR-T
        de milhões: exatamente o tipo de falso positivo que não pode existir num
        catálogo de faturamento.
        """
        from apps.core.management.commands.import_anvisa_cmed import _ean

        self.assertEqual(_ean("0000000000000"), "")
        self.assertEqual(_ean("0000000"), "")
        self.assertEqual(_ean("7891111111111"), "7891111111111")
        self.assertEqual(_ean(""), "")
        # Um EAN legítimo que apenas começa com zero continua válido.
        self.assertEqual(_ean("0781234567890"), "0781234567890")

    def test_zero_ean_row_does_not_resolve_by_ean(self):
        AnvisaPresentation.objects.create(
            product=self.p1, code="1000000019999", ean="0000000000000"
        )
        self.assertIsNone(AnvisaProduct.by_ean("0000000000000"))

    def test_price_parsing_handles_both_decimal_formats(self):
        """Ponto decimal e vírgula decimal têm de dar o MESMO número.

        Regressão: `_price` aplicava a regra brasileira (tira ponto de milhar,
        vírgula vira ponto) em tudo. Num valor já normalizado pelo ETL como
        "13274524.58" isso apagava o ponto e produzia 1327452458 — cem vezes o
        preço real. Só não passou despercebido porque estourou o campo; um valor
        menor teria sido gravado errado em silêncio.
        """
        from apps.core.management.commands.import_anvisa_cmed import _price

        self.assertEqual(_price("13274524.58"), Decimal("13274524.58"))
        self.assertEqual(_price("13.274.524,58"), Decimal("13274524.58"))
        self.assertEqual(_price("15,54"), Decimal("15.54"))
        self.assertEqual(_price("15.54"), Decimal("15.54"))
        self.assertEqual(_price("1234"), Decimal("1234"))
        self.assertIsNone(_price(""))
        self.assertIsNone(_price("-"))


class TestImportAnvisaValid(TenantTestCase):
    def test_creates_rows_with_all_fields(self):
        run_import(source=str(SAMPLE))
        self.assertEqual(AnvisaProduct.objects.count(), 3)
        amox = AnvisaProduct.objects.get(code="1000000000001")
        self.assertEqual(amox.display, "FAKE-Amoxicilina 500mg")
        self.assertEqual(amox.dcb, "Amoxicilina")
        self.assertEqual(amox.ean, "7891111111111")
        self.assertEqual(amox.therapeutic_class, "ANTIBACTERIANOS")
        self.assertEqual(amox.controlled_class, "none")
        self.assertEqual(amox.system, "anvisa")

    def test_tarja_imported_for_controlled(self):
        run_import(source=str(SAMPLE))
        morfina = AnvisaProduct.objects.get(code="1000000000002")
        self.assertEqual(morfina.controlled_class, "A1")
        self.assertTrue(morfina.is_controlled)

    def test_normalized_display_populated(self):
        run_import(source=str(SAMPLE))
        p = AnvisaProduct.objects.get(code="1000000000002")
        self.assertEqual(p.normalized_display, "fake-morfina 10mg/ml")

    def test_ean_lookup_after_import(self):
        run_import(source=str(SAMPLE))
        p = AnvisaProduct.by_ean("7893333333333")
        self.assertIsNotNone(p)
        self.assertEqual(p.code, "1000000000003")

    def test_idempotent_rerun_updates_not_duplicates(self):
        run_import(source=str(SAMPLE))
        run_import(source=str(SAMPLE))
        self.assertEqual(AnvisaProduct.objects.count(), 3)

    def test_provenance_log_written(self):
        run_import(source=str(SAMPLE), anvisa_version="2024")
        log = TerminologyImportLog.objects.filter(system="anvisa").latest("ran_at")
        self.assertEqual(log.provenance, "ANVISA")
        self.assertEqual(log.version, "2024")
        self.assertEqual(log.row_count_added, 3)
        self.assertEqual(log.status, TerminologyImportLog.Status.SUCCESS)
        self.assertFalse(log.dry_run)


class TestImportAnvisaDryRun(TenantTestCase):
    def test_dry_run_writes_nothing(self):
        run_import(source=str(SAMPLE), dry_run=True)
        self.assertEqual(AnvisaProduct.objects.count(), 0)
        log = TerminologyImportLog.objects.filter(system="anvisa").latest("ran_at")
        self.assertTrue(log.dry_run)
        self.assertEqual(log.row_count_added, 3)  # counts what WOULD happen


class TestImportAnvisaMalformed(TenantTestCase):
    def test_malformed_csv_aborts_with_line_numbers(self):
        # Parse-time validation fails loud: nothing committed, both bad lines named.
        with self.assertRaises(CommandError) as ctx:
            run_import(source=str(MALFORMED))
        msg = str(ctx.exception)
        self.assertIn("REGISTRO is empty", msg)
        self.assertIn("PRODUTO is empty", msg)
        self.assertEqual(AnvisaProduct.objects.count(), 0)

    def test_missing_file_raises(self):
        with self.assertRaises(CommandError):
            run_import(source=str(FIXTURES / "does_not_exist.csv"))
