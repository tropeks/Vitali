"""API tests for the stockout-prediction surface (wedge S3).

Covers ``StockRiskView`` (the proactive predictive risk list) and
``AcknowledgeStockAlertView`` (the advise-only ack), plus the
``evaluate_stockout`` management command smoke.

Mirrors apps.pharmacy.tests.test_purchase_orders (APIClient + tenant + Role
permission gating) and the FastTenantTestCase patterns.

Run: python manage.py test apps.pharmacy.tests.test_stock_risk_view
"""

import datetime
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import FeatureFlag, Role, User
from apps.pharmacy.models import Drug, Material, StockAlert, StockItem, StockMovement
from apps.test_utils import TenantTestCase


def _enable_pharmacy(tenant):
    FeatureFlag.objects.update_or_create(
        tenant=tenant, module_key="pharmacy", defaults={"is_enabled": True}
    )


def _set_stockout_flag(tenant, on):
    FeatureFlag.objects.update_or_create(
        tenant=tenant, module_key="stockout_safety", defaults={"is_enabled": on}
    )


class StockRiskBaseCase(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        _enable_pharmacy(self.__class__.tenant)
        _set_stockout_flag(self.__class__.tenant, True)

        self.role = Role.objects.create(
            name="gestor_suprimentos",
            permissions=["pharmacy.read"],
        )
        self.user = User.objects.create_user(
            email="gestor@test.com",
            password="Str0ng!Pass#2024",
            full_name="Gestor Suprimentos",
            role=self.role,
        )
        self.client.force_authenticate(user=self.user)

        # ``now`` injected to the service; pin one day ahead so just-created
        # dispense events fall inside the trailing window (mirror S2 tests).
        self.now = timezone.now() + datetime.timedelta(days=1)

    # ── fixtures ────────────────────────────────────────────────────────────────

    def _stock_item(self, *, drug=None, material=None, lot="L1", expiry=None):
        return StockItem.objects.create(
            drug=drug,
            material=material,
            lot_number=lot,
            expiry_date=expiry,
            quantity=Decimal("0"),
        )

    def _receive(self, item, qty):
        StockMovement(stock_item=item, movement_type="entry", quantity=Decimal(qty)).save()

    def _dispense(self, item, qty, *, n=1):
        for _ in range(n):
            StockMovement(stock_item=item, movement_type="dispense", quantity=-Decimal(qty)).save()

    def _make_stockout_risk_drug(self):
        """A configured drug with history that the engine flags as stockout_risk."""
        from apps.pharmacy.services.stockout_safety import StockoutService

        drug = Drug.objects.create(name="Dipirona 500mg", lead_time_days=10)
        item = self._stock_item(drug=drug)
        self._receive(item, "180")
        self._dispense(item, "10", n=15)  # ~5/day, balance 30 → ~6 days runway < 10
        StockoutService(requesting_user=self.user).evaluate_item(drug, now=self.now)
        return drug


class StockRiskViewTests(StockRiskBaseCase):
    def test_lists_open_alerts_when_flag_on(self):
        self._make_stockout_risk_drug()
        resp = self.client.get("/api/v1/pharmacy/stock/risk/")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["stockout_safety_enabled"])
        self.assertEqual(len(resp.data["alerts"]), 1)
        alert = resp.data["alerts"][0]
        self.assertEqual(alert["kind"], "stockout_risk")
        self.assertEqual(alert["product_name"], "Dipirona 500mg")
        self.assertEqual(alert["status"], "open")
        self.assertIsNotNone(alert["predicted_date"])

    def test_empty_when_flag_off(self):
        # Build a risk alert WHILE the flag is on, then turn it OFF: the surface
        # must return an empty list (engine "didn't run" from the gestor's view).
        self._make_stockout_risk_drug()
        self.assertEqual(StockAlert.objects.count(), 1)  # row exists in DB
        _set_stockout_flag(self.__class__.tenant, False)

        resp = self.client.get("/api/v1/pharmacy/stock/risk/")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["stockout_safety_enabled"])
        self.assertEqual(resp.data["alerts"], [])

    def test_reorder_suggestion_present_and_correct(self):
        self._make_stockout_risk_drug()
        resp = self.client.get("/api/v1/pharmacy/stock/risk/?kind=stockout_risk")
        alert = resp.data["alerts"][0]
        # velocity ~5/day, lead 10 + coverage 30 = 40 days horizon; balance 30.
        # ceil(5*40 - 30) = ceil(170) = 170. Assert it matches the stored compute.
        self.assertIsNotNone(alert["suggested_reorder_qty"])
        self.assertEqual(Decimal(alert["suggested_reorder_qty"]), Decimal("170"))

    def test_kind_filter(self):
        self._make_stockout_risk_drug()
        # expiry_waste lot on a separate configured product.
        from apps.pharmacy.services.stockout_safety import StockoutService

        drug2 = Drug.objects.create(name="Soro 500ml", lead_time_days=10)
        soon = (self.now + datetime.timedelta(days=10)).date()
        item = self._stock_item(drug=drug2, lot="EXP", expiry=soon)
        self._receive(item, "100")
        self._dispense(item, "1", n=30)  # ~1/day → big waste
        StockoutService(requesting_user=self.user).evaluate_item(drug2, now=self.now)

        resp = self.client.get("/api/v1/pharmacy/stock/risk/?kind=expiry_waste")
        kinds = {a["kind"] for a in resp.data["alerts"]}
        self.assertEqual(kinds, {"expiry_waste"})

    def test_permission_gated_without_pharmacy_read(self):
        role = Role.objects.create(name="sem_perm", permissions=[])
        user = User.objects.create_user(
            email="noperm@test.com", password="Str0ng!Pass#2024", full_name="No Perm", role=role
        )
        client = APIClient()
        client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        client.force_authenticate(user=user)
        resp = client.get("/api/v1/pharmacy/stock/risk/")
        self.assertEqual(resp.status_code, 403)

    def test_module_off_blocks(self):
        FeatureFlag.objects.filter(tenant=self.__class__.tenant, module_key="pharmacy").delete()
        resp = self.client.get("/api/v1/pharmacy/stock/risk/")
        self.assertEqual(resp.status_code, 403)


class AcknowledgeStockAlertViewTests(StockRiskBaseCase):
    def test_acknowledge_flips_status_and_leaves_open_list(self):
        self._make_stockout_risk_drug()
        alert = StockAlert.objects.get(kind=StockAlert.Kind.STOCKOUT_RISK)

        resp = self.client.post(
            f"/api/v1/pharmacy/stock-alerts/{alert.id}/acknowledge/",
            {"note": "ja pedi reposicao"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "acknowledged")

        alert.refresh_from_db()
        self.assertEqual(alert.status, StockAlert.Status.ACKNOWLEDGED)
        self.assertEqual(alert.acknowledged_by_id, self.user.id)
        self.assertIsNotNone(alert.acknowledged_at)
        self.assertEqual(alert.note, "ja pedi reposicao")

        # The acknowledged alert is gone from the OPEN risk list.
        listed = self.client.get("/api/v1/pharmacy/stock/risk/")
        self.assertEqual(listed.data["alerts"], [])

    def test_acknowledge_without_note_ok(self):
        self._make_stockout_risk_drug()
        alert = StockAlert.objects.get(kind=StockAlert.Kind.STOCKOUT_RISK)
        resp = self.client.post(
            f"/api/v1/pharmacy/stock-alerts/{alert.id}/acknowledge/", {}, format="json"
        )
        self.assertEqual(resp.status_code, 200)
        alert.refresh_from_db()
        self.assertEqual(alert.status, StockAlert.Status.ACKNOWLEDGED)

    def test_acknowledge_404_for_unknown(self):
        import uuid

        resp = self.client.post(
            f"/api/v1/pharmacy/stock-alerts/{uuid.uuid4()}/acknowledge/", {}, format="json"
        )
        self.assertEqual(resp.status_code, 404)

    def test_acknowledge_permission_gated(self):
        self._make_stockout_risk_drug()
        alert = StockAlert.objects.get(kind=StockAlert.Kind.STOCKOUT_RISK)
        role = Role.objects.create(name="sem_perm_ack", permissions=[])
        user = User.objects.create_user(
            email="noperm-ack@test.com",
            password="Str0ng!Pass#2024",
            full_name="No Perm",
            role=role,
        )
        client = APIClient()
        client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        client.force_authenticate(user=user)
        resp = client.post(
            f"/api/v1/pharmacy/stock-alerts/{alert.id}/acknowledge/", {}, format="json"
        )
        self.assertEqual(resp.status_code, 403)


class EvaluateStockoutCommandTests(StockRiskBaseCase):
    def test_command_creates_alerts_for_configured_product(self):
        drug = Drug.objects.create(name="Amoxicilina 500mg", lead_time_days=10)
        item = self._stock_item(drug=drug)
        self._receive(item, "180")
        self._dispense(item, "10", n=15)

        out = StringIO()
        call_command("evaluate_stockout", schema=self.__class__.tenant.schema_name, stdout=out)
        self.assertTrue(
            StockAlert.objects.filter(
                drug=drug, kind=StockAlert.Kind.STOCKOUT_RISK, status=StockAlert.Status.OPEN
            ).exists()
        )

    def test_command_noop_when_flag_off(self):
        _set_stockout_flag(self.__class__.tenant, False)
        drug = Drug.objects.create(name="Cefalexina 500mg", lead_time_days=10)
        item = self._stock_item(drug=drug)
        self._receive(item, "180")
        self._dispense(item, "10", n=15)

        out = StringIO()
        call_command("evaluate_stockout", schema=self.__class__.tenant.schema_name, stdout=out)
        self.assertEqual(StockAlert.objects.count(), 0)

    def test_command_idempotent(self):
        drug = Drug.objects.create(name="Ranitidina", lead_time_days=10)
        item = self._stock_item(drug=drug)
        self._receive(item, "180")
        self._dispense(item, "10", n=15)
        schema = self.__class__.tenant.schema_name
        out = StringIO()
        call_command("evaluate_stockout", schema=schema, stdout=out)
        call_command("evaluate_stockout", schema=schema, stdout=out)
        self.assertEqual(
            StockAlert.objects.filter(drug=drug, kind=StockAlert.Kind.STOCKOUT_RISK).count(),
            1,
        )


class MaterialStockRiskTests(StockRiskBaseCase):
    def test_material_alert_serialized_with_material_id(self):
        from apps.pharmacy.services.stockout_safety import StockoutService

        material = Material.objects.create(name="Seringa 10ml", lead_time_days=10)
        item = self._stock_item(material=material)
        self._receive(item, "180")
        self._dispense(item, "10", n=15)
        StockoutService(requesting_user=self.user).evaluate_item(material, now=self.now)

        resp = self.client.get("/api/v1/pharmacy/stock/risk/")
        alert = resp.data["alerts"][0]
        self.assertIsNotNone(alert["material"])
        self.assertIsNone(alert["drug"])
        self.assertEqual(alert["product_name"], "Seringa 10ml")
