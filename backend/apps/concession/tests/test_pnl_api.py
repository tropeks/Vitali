"""Sprint C4-T2 — gated P&L read endpoint.

``GET /api/v1/concession/contracts/<id>/pnl/?start=&end=`` returns the contract
P&L when the tenant has the ``diagnostic_concession`` module; a tenant WITHOUT
the FeatureFlag gets 403 (the tier gate).
"""

from datetime import date
from decimal import Decimal

from rest_framework.test import APIClient

from apps.concession.models import (
    ConcessionContract,
    ConcessionService,
    ContractServicePrice,
    MaterialUnitCost,
    ServiceRecipe,
)
from apps.concession.permissions import CONCESSION_MODULE_KEY
from apps.concession.services_pnl import record_exam_consumption
from apps.core.models import FeatureFlag, Role, User
from apps.core.permissions import DEFAULT_ROLES
from apps.organization.models import Facility, LegalEntity
from apps.pharmacy.models import Material, StockItem, StockMovement, Warehouse
from apps.test_utils import TenantTestCase


def _make_user(email):
    role = Role.objects.create(name=f"role-{email}", permissions=DEFAULT_ROLES["admin"])
    return User.objects.create_user(email=email, password="pw", role=role)


class _ApiBase(TenantTestCase):
    def _client(self, user):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user=user)
        return c

    def _fixtures(self):
        le = LegalEntity.objects.create(code="LE-PNL", name="Rede PNL")
        self.unit = Facility.objects.create(code="U-PNL", name="Unidade PNL", legal_entity=le)
        self.wh = Warehouse.objects.create(code="WH-PNL", name="Central PNL")
        self.gel = Material.objects.create(name="Gel PNL")
        MaterialUnitCost.objects.create(material=self.gel, unit_cost=Decimal("1.50"))
        item = StockItem.objects.create(material=self.gel, warehouse=self.wh, lot_number="G")
        StockMovement.objects.create(stock_item=item, movement_type="entry", quantity=Decimal("50"))
        self.svc = ConcessionService.objects.create(code="SRV-US", name="Ultrassom")
        ServiceRecipe.objects.create(service=self.svc, material=self.gel, quantity=Decimal("2"))
        self.contract = ConcessionContract.objects.create(
            name="Contrato PNL", client_name="Cli", start_date=date(2026, 1, 1)
        )
        self.contract.units.add(self.unit)
        ContractServicePrice.objects.create(
            contract=self.contract, service=self.svc, price=Decimal("100.00"), is_billable=True
        )
        record_exam_consumption(self.svc, self.unit, "EX-1", warehouse=self.wh)


class TestPnlEndpointEnabled(_ApiBase):
    def setUp(self):
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key=CONCESSION_MODULE_KEY,
            defaults={"is_enabled": True},
        )
        self.user = _make_user("pnl@test.com")
        self._fixtures()

    def test_pnl_returns_math(self):
        resp = self._client(self.user).get(
            f"/api/v1/concession/contracts/{self.contract.pk}/pnl/",
            {"start": "2026-01-01", "end": "2026-12-31"},
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        # revenue 100, consumption 3.00, no freight/maintenance → result 97.00
        self.assertEqual(resp.data["revenue"], Decimal("100.00"))
        self.assertEqual(resp.data["cost"], Decimal("3.00"))
        self.assertEqual(resp.data["result"], Decimal("97.00"))
        self.assertEqual(resp.data["exam_volume"], 1)


class TestPnlTierGate(_ApiBase):
    def setUp(self):
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key=CONCESSION_MODULE_KEY,
            defaults={"is_enabled": False},
        )
        self.user = _make_user("nogate-pnl@test.com")
        self._fixtures()

    def test_pnl_forbidden_without_module(self):
        resp = self._client(self.user).get(f"/api/v1/concession/contracts/{self.contract.pk}/pnl/")
        self.assertEqual(resp.status_code, 403)
