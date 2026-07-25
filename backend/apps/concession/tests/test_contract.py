"""Sprint C2 — Contract + ContractServicePrice + ServiceRecipe (model layer).

TDD for the economic core of the concession P&L:
- price resolution (unit-level overrides contract-level),
- ``is_billable=False`` → billable revenue 0 but the row still resolves
  (exam volume still counts), exact Decimal arithmetic,
- service consumption recipe (service consumes N of a pharmacy.Material).
"""

from datetime import date
from decimal import Decimal

from django.db import IntegrityError, transaction

from apps.concession.models import (
    ConcessionContract,
    ConcessionService,
    ContractServicePrice,
    ServiceRecipe,
    consumption_for,
)
from apps.organization.models import Facility, LegalEntity
from apps.pharmacy.models import Material
from apps.test_utils import TenantTestCase


class _Fixtures(TenantTestCase):
    """Shared fixtures: a legal entity, two units (Facilities), a couple of
    services and a contract spanning both units."""

    def setUp(self):
        self.legal_entity = LegalEntity.objects.create(code="LE-1", name="Rede Diagnóstica")
        self.unit_a = Facility.objects.create(
            code="UNIT-A", name="Unidade A", legal_entity=self.legal_entity
        )
        self.unit_b = Facility.objects.create(
            code="UNIT-B", name="Unidade B", legal_entity=self.legal_entity
        )
        self.xray = ConcessionService.objects.create(code="SRV-XRAY", name="Raio-X Tórax")
        self.ct = ConcessionService.objects.create(code="SRV-CT", name="Tomografia")
        self.contract = ConcessionContract.objects.create(
            name="Contrato Mestre",
            client_name="Hospital Santa Maria",
            monthly_value=Decimal("10000.00"),
            start_date=date(2026, 1, 1),
        )
        self.contract.units.add(self.unit_a, self.unit_b)


class TestConcessionContract(_Fixtures):
    def test_contract_defaults_and_units(self):
        self.assertEqual(self.contract.status, ConcessionContract.Status.ACTIVE)
        self.assertEqual(self.contract.monthly_value, Decimal("10000.00"))
        self.assertIsNone(self.contract.end_date)
        self.assertEqual(self.contract.units.count(), 2)
        self.assertIn(self.unit_a, self.contract.units.all())

    def test_monthly_value_optional(self):
        c = ConcessionContract.objects.create(
            name="Sem valor fixo", client_name="Cliente X", start_date=date(2026, 2, 1)
        )
        self.assertIsNone(c.monthly_value)

    def test_status_choices(self):
        self.contract.status = ConcessionContract.Status.TERMINATED
        self.contract.save()
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.status, "TERMINATED")


class TestContractServicePriceResolution(_Fixtures):
    def test_unit_price_overrides_contract_price(self):
        # contract-level tariff for the X-ray
        ContractServicePrice.objects.create(
            contract=self.contract, service=self.xray, price=Decimal("50.00")
        )
        # unit A negotiates a cheaper price
        ContractServicePrice.objects.create(
            unit=self.unit_a, service=self.xray, price=Decimal("30.00")
        )

        resolved_a = self.contract.resolve_price(self.xray, self.unit_a)
        resolved_b = self.contract.resolve_price(self.xray, self.unit_b)

        # unit A → unit-level override (exact Decimal)
        self.assertIsNotNone(resolved_a)
        self.assertEqual(resolved_a.price, Decimal("30.00"))
        # unit B has no override → falls back to the contract-level price
        self.assertIsNotNone(resolved_b)
        self.assertEqual(resolved_b.price, Decimal("50.00"))

    def test_resolve_without_unit_returns_contract_price(self):
        ContractServicePrice.objects.create(
            contract=self.contract, service=self.xray, price=Decimal("50.00")
        )
        resolved = self.contract.resolve_price(self.xray, None)
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.price, Decimal("50.00"))

    def test_resolve_returns_none_when_no_price(self):
        self.assertIsNone(self.contract.resolve_price(self.ct, self.unit_a))

    def test_is_billable_false_resolves_but_revenue_zero(self):
        # An included exam: no direct revenue, but volume still counts.
        price = ContractServicePrice.objects.create(
            contract=self.contract,
            service=self.ct,
            price=Decimal("40.00"),
            is_billable=False,
        )
        resolved = self.contract.resolve_price(self.ct, self.unit_a)
        # the row STILL resolves (volume counts)
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.pk, price.pk)
        # tariff is preserved…
        self.assertEqual(resolved.price, Decimal("40.00"))
        # …but billable revenue is exactly zero
        self.assertEqual(resolved.billable_revenue, Decimal("0"))

    def test_is_billable_true_revenue_equals_price(self):
        price = ContractServicePrice.objects.create(
            contract=self.contract, service=self.xray, price=Decimal("75.50")
        )
        self.assertTrue(price.is_billable)
        self.assertEqual(price.billable_revenue, Decimal("75.50"))

    def test_unique_contract_service(self):
        ContractServicePrice.objects.create(
            contract=self.contract, service=self.xray, price=Decimal("50.00")
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ContractServicePrice.objects.create(
                    contract=self.contract, service=self.xray, price=Decimal("60.00")
                )

    def test_unique_unit_service(self):
        ContractServicePrice.objects.create(
            unit=self.unit_a, service=self.xray, price=Decimal("30.00")
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ContractServicePrice.objects.create(
                    unit=self.unit_a, service=self.xray, price=Decimal("35.00")
                )


class TestServiceRecipe(_Fixtures):
    def setUp(self):
        super().setUp()
        self.film = Material.objects.create(name="Filme 35x43", category="FILME")
        self.contrast = Material.objects.create(name="Contraste iodado", category="CONTRASTE")

    def test_service_consumes_one_material(self):
        ServiceRecipe.objects.create(service=self.xray, material=self.film, quantity=Decimal("2"))
        consumption = consumption_for(self.xray)
        self.assertEqual(consumption, {self.film: Decimal("2")})

    def test_multiple_materials_per_service(self):
        ServiceRecipe.objects.create(service=self.ct, material=self.film, quantity=Decimal("1"))
        ServiceRecipe.objects.create(
            service=self.ct, material=self.contrast, quantity=Decimal("0.5")
        )
        consumption = consumption_for(self.ct)
        self.assertEqual(consumption, {self.film: Decimal("1"), self.contrast: Decimal("0.5")})

    def test_quantity_math_scales_with_exam_volume(self):
        ServiceRecipe.objects.create(
            service=self.ct, material=self.contrast, quantity=Decimal("0.5")
        )
        qty_per_exam = consumption_for(self.ct)[self.contrast]
        # 12 exams consume exactly 6.0 units of contrast (exact Decimal)
        self.assertEqual(qty_per_exam * 12, Decimal("6.0"))

    def test_unique_service_material(self):
        ServiceRecipe.objects.create(service=self.xray, material=self.film, quantity=Decimal("1"))
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ServiceRecipe.objects.create(
                    service=self.xray, material=self.film, quantity=Decimal("3")
                )
