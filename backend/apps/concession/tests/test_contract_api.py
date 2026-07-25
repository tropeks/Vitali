"""Sprint C2 — Gated REST surface for contracts / prices / recipes.

Endpoints are mounted under ``/api/v1/`` (see apps.concession.urls). Every
viewset gates on ``[IsAuthenticated, ConcessionModule]`` and audits writes.
The tier test proves the gate: a tenant WITHOUT the ``diagnostic_concession``
FeatureFlag gets 403.
"""

from datetime import date
from decimal import Decimal

from rest_framework.test import APIClient

from apps.concession.models import (
    ConcessionContract,
    ConcessionService,
    ContractServicePrice,
    ServiceRecipe,
)
from apps.concession.permissions import CONCESSION_MODULE_KEY
from apps.core.models import FeatureFlag, Role, User
from apps.core.permissions import DEFAULT_ROLES
from apps.organization.models import Facility, LegalEntity
from apps.pharmacy.models import Material
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
        le = LegalEntity.objects.create(code="LE-API", name="Rede API")
        self.unit = Facility.objects.create(code="U-API", name="Unidade API", legal_entity=le)
        self.svc = ConcessionService.objects.create(code="SRV-US", name="Ultrassom")
        self.material = Material.objects.create(name="Gel condutor", category="GEL")


class TestConcessionApiEnabled(_ApiBase):
    """Module active → CRUD works (201 / list)."""

    def setUp(self):
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key=CONCESSION_MODULE_KEY,
            defaults={"is_enabled": True},
        )
        self.user = _make_user("op@test.com")
        self._fixtures()

    def test_create_contract_201(self):
        resp = self._client(self.user).post(
            "/api/v1/concession-contracts/",
            {
                "name": "Contrato API",
                "client_name": "Cliente API",
                "start_date": "2026-01-01",
                "units": [str(self.unit.pk)],
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(ConcessionContract.objects.count(), 1)

    def test_list_contracts_200(self):
        c = ConcessionContract.objects.create(
            name="C1", client_name="Cli", start_date=date(2026, 1, 1)
        )
        c.units.add(self.unit)
        resp = self._client(self.user).get("/api/v1/concession-contracts/")
        self.assertEqual(resp.status_code, 200)
        results = resp.data.get("results", resp.data)
        self.assertTrue(len(results) >= 1)

    def test_create_price_201(self):
        contract = ConcessionContract.objects.create(
            name="C2", client_name="Cli", start_date=date(2026, 1, 1)
        )
        resp = self._client(self.user).post(
            "/api/v1/contract-prices/",
            {
                "contract": contract.pk,
                "service": self.svc.pk,
                "price": "45.00",
                "is_billable": True,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(ContractServicePrice.objects.count(), 1)

    def test_list_prices_200(self):
        contract = ConcessionContract.objects.create(
            name="C3", client_name="Cli", start_date=date(2026, 1, 1)
        )
        ContractServicePrice.objects.create(
            contract=contract, service=self.svc, price=Decimal("45.00")
        )
        resp = self._client(self.user).get("/api/v1/contract-prices/")
        self.assertEqual(resp.status_code, 200)
        results = resp.data.get("results", resp.data)
        self.assertTrue(len(results) >= 1)

    def test_create_recipe_201(self):
        resp = self._client(self.user).post(
            "/api/v1/service-recipes/",
            {"service": self.svc.pk, "material": str(self.material.pk), "quantity": "2"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(ServiceRecipe.objects.count(), 1)

    def test_list_recipes_200(self):
        ServiceRecipe.objects.create(
            service=self.svc, material=self.material, quantity=Decimal("2")
        )
        resp = self._client(self.user).get("/api/v1/service-recipes/")
        self.assertEqual(resp.status_code, 200)
        results = resp.data.get("results", resp.data)
        self.assertTrue(len(results) >= 1)


class TestConcessionTierGate(_ApiBase):
    """Module NOT active for the tenant → 403 on every endpoint."""

    def setUp(self):
        # Ensure the flag is explicitly disabled (no diagnostic_concession tier).
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key=CONCESSION_MODULE_KEY,
            defaults={"is_enabled": False},
        )
        self.user = _make_user("nogate@test.com")

    def test_contracts_forbidden_without_module(self):
        resp = self._client(self.user).get("/api/v1/concession-contracts/")
        self.assertEqual(resp.status_code, 403)

    def test_prices_forbidden_without_module(self):
        resp = self._client(self.user).get("/api/v1/contract-prices/")
        self.assertEqual(resp.status_code, 403)

    def test_recipes_forbidden_without_module(self):
        resp = self._client(self.user).get("/api/v1/service-recipes/")
        self.assertEqual(resp.status_code, 403)
