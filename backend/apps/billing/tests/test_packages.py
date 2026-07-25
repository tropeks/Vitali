"""
Sprint M1-S4 · S4-T1 — Contractual packages (Package/PackageItem) + pricing helper.

A Package bundles N procedures (TUSS and/or CBHPM) for a fixed negotiated price,
scoped to an InsuranceProvider / PriceTable. The pricing helper resolves a
package price, using core.CBHPMItem.valor() (porte × valor_ch) when a line
references CBHPM.

Run: python manage.py test apps.billing.tests.test_packages
"""

from decimal import Decimal

from apps.billing.models import InsuranceProvider, PriceTable
from apps.billing.revenue_models import Package, PackageItem, resolve_package_price
from apps.core.models import CBHPMItem, TUSSCode
from apps.test_utils import TenantTestCase


class PackageTestCase(TenantTestCase):
    def setUp(self):
        self.provider = InsuranceProvider.objects.create(name="Unimed Pkg", ans_code="770001")
        self.table = PriceTable.objects.create(
            provider=self.provider, name="Tabela Pkg", valid_from="2026-01-01"
        )
        self.tuss = TUSSCode.objects.create(
            code="10101012", description="Consulta", group="consultas"
        )
        # CBHPM row: valor() == porte × valor_ch == 10 × 2 == 20.00
        self.cbhpm = CBHPMItem.objects.create(
            code="30101018",
            display="Procedimento porte",
            porte=Decimal("10.0000"),
            valor_ch=Decimal("2.000000"),
        )

    def test_package_bundles_items(self):
        pkg = Package.objects.create(
            name="Pacote Cirúrgico", provider=self.provider, price_table=self.table
        )
        PackageItem.objects.create(
            package=pkg, tuss_code=self.tuss, description="Consulta", unit_value=Decimal("50.00")
        )
        PackageItem.objects.create(
            package=pkg, cbhpm=self.cbhpm, description="Procedimento", quantity=Decimal("2")
        )
        self.assertEqual(pkg.items.count(), 2)
        self.assertEqual(pkg.provider_id, self.provider.id)
        self.assertEqual(pkg.price_table_id, self.table.id)

    def test_fixed_price_resolves(self):
        """A package with a fixed negotiated bundle price returns exactly it."""
        pkg = Package.objects.create(
            name="Pacote Fechado",
            provider=self.provider,
            fixed_price=Decimal("1500.00"),
        )
        PackageItem.objects.create(
            package=pkg, cbhpm=self.cbhpm, description="X", quantity=Decimal("3")
        )
        self.assertEqual(resolve_package_price(pkg), Decimal("1500.00"))

    def test_cbhpm_porte_valuation_flows_through(self):
        """With no fixed price, the CBHPM line is valued via CBHPMItem.valor()
        (porte × valor_ch) × quantity, plus taxas/diárias/filme."""
        pkg = Package.objects.create(
            name="Pacote Aberto",
            provider=self.provider,
            taxa_value=Decimal("30.00"),
            diaria_value=Decimal("100.00"),
            filme_value=Decimal("5.00"),
        )
        # CBHPM line: valor() 20.00 × qty 2 = 40.00
        PackageItem.objects.create(
            package=pkg, cbhpm=self.cbhpm, description="Proc", quantity=Decimal("2")
        )
        # TUSS line with explicit unit value: 50 × 1 = 50.00
        PackageItem.objects.create(
            package=pkg, tuss_code=self.tuss, description="Consulta", unit_value=Decimal("50.00")
        )
        # 40 + 50 + 30 (taxa) + 100 (diária) + 5 (filme) = 225.00
        self.assertEqual(resolve_package_price(pkg), Decimal("225.00"))

    def test_package_line_value_uses_cbhpm_when_no_override(self):
        pkg = Package.objects.create(name="P", provider=self.provider)
        line = PackageItem.objects.create(
            package=pkg, cbhpm=self.cbhpm, description="Proc", quantity=Decimal("2")
        )
        self.assertEqual(line.line_value(), Decimal("40.0000"))
