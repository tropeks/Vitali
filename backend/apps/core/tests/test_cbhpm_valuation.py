"""
M1-S1 (S1-T2) — CBHPMItem ↔ TUSSCode link + valoração por porte.

Covers the nullable FK from a CBHPM porte row to a TUSS procedure (and the new
TUSSCode.table_number tag), plus the CBHPMItem.valor() helper — porte × valor_ch
as exact Decimal, never float.
"""

from decimal import Decimal

from apps.core.cbhpm_models import CBHPMItem
from apps.core.models import TUSSCode
from apps.test_utils import TenantTestCase


class TestCBHPMTussLink(TenantTestCase):
    def test_fk_link_to_tuss(self):
        tuss = TUSSCode.objects.create(
            code="30715016",
            description="Apendicectomia",
            group="procedimento",
            version="2024",
            table_number="22",
        )
        item = CBHPMItem.objects.create(code="30715016", display="FAKE-Apendicectomia", tuss=tuss)
        item.refresh_from_db()
        self.assertEqual(item.tuss, tuss)
        self.assertEqual(item.tuss.table_number, "22")
        self.assertIn(item, tuss.cbhpm_items.all())

    def test_tuss_is_nullable(self):
        item = CBHPMItem.objects.create(code="10101012", display="Consulta")
        self.assertIsNone(item.tuss)

    def test_table_number_defaults_null(self):
        tuss = TUSSCode.objects.create(
            code="99999999", description="Sem tabela", group="taxa", version="2024"
        )
        self.assertIsNone(tuss.table_number)


class TestCBHPMValuation(TenantTestCase):
    def test_valor_is_exact_decimal(self):
        item = CBHPMItem.objects.create(
            code="30715016",
            display="Apendicectomia",
            porte=Decimal("7.2500"),
            valor_ch=Decimal("12.500000"),
        )
        result = item.valor()
        self.assertIsInstance(result, Decimal)
        self.assertEqual(result, Decimal("90.625000"))

    def test_valor_no_float_drift(self):
        # 0.1 × 0.2 = 0.02 exactly in Decimal (0.020000000... in float).
        item = CBHPMItem.objects.create(
            code="10101012",
            display="Consulta",
            porte=Decimal("0.1000"),
            valor_ch=Decimal("0.200000"),
        )
        self.assertEqual(item.valor(), Decimal("0.02000000"))

    def test_valor_zero_when_unvalued(self):
        item = CBHPMItem.objects.create(code="40901165", display="Sem porte")
        self.assertEqual(item.valor(), Decimal("0"))
