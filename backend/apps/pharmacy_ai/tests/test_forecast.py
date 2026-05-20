"""Tests for the AI Farmácia demand forecast service + REST endpoint."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import FeatureFlag, Role, User
from apps.pharmacy.models import Drug, StockItem, StockMovement
from apps.pharmacy_ai.services.forecast import forecast_for_drug
from apps.test_utils import TenantTestCase

FORECAST_URL = "/api/v1/pharmacy/forecast/"


def _make_user(*, role_name: str, perms: list[str]) -> User:
    role, _ = Role.objects.get_or_create(name=role_name, defaults={"permissions": perms})
    role.permissions = perms
    role.save()
    return User.objects.create_user(
        email=f"{role_name}@test.com", password="pw", role=role, full_name="Test"
    )


class DemandForecastServiceTest(TenantTestCase):
    def setUp(self):
        self.user = _make_user(role_name="phai_user", perms=["pharmacy_ai.read"])
        self.drug = Drug.objects.create(generic_name="Amoxicilina", name="Amoxicilina")
        self.stock = StockItem.objects.create(drug=self.drug, lot_number="L1")
        # Seed initial stock: +100 entry.
        StockMovement.objects.create(
            stock_item=self.stock,
            movement_type="entry",
            quantity=Decimal("100"),
            performed_by=self.user,
        )

    def _dispense(self, qty: float, *, days_ago: int):
        m = StockMovement(
            stock_item=self.stock,
            movement_type="dispense",
            quantity=Decimal(str(-qty)),
            performed_by=self.user,
        )
        m.save()
        # Backdate the immutable created_at; updates on the ledger are
        # rejected by `StockMovement.save()`, so we go around it with an
        # explicit UPDATE on the QuerySet manager.
        new_ts = timezone.now() - timedelta(days=days_ago)
        StockMovement.objects.filter(pk=m.pk).update(created_at=new_ts)

    def test_no_dispense_history_avg_zero_projected_null(self):
        result = forecast_for_drug(self.drug, window_days=30, target_days=60)
        self.assertEqual(result.avg_daily_consumption, 0.0)
        self.assertIsNone(result.projected_days_of_supply)
        self.assertEqual(result.current_stock, 100.0)
        self.assertEqual(result.recommended_reorder_quantity, 0.0)

    def test_uniform_consumption_avg_and_runway(self):
        # 30 dispense events of 2 units each across the past 30 days.
        for d in range(30):
            self._dispense(2, days_ago=d)
        result = forecast_for_drug(self.drug, window_days=30, target_days=60)
        self.assertEqual(result.total_dispensed_in_window, 60.0)
        self.assertAlmostEqual(result.avg_daily_consumption, 2.0, places=4)
        # Current stock = 100 - 60 = 40
        self.assertAlmostEqual(result.current_stock, 40.0, places=4)
        # Days of supply = 40 / 2 = 20
        self.assertAlmostEqual(result.projected_days_of_supply, 20.0, places=4)
        # target 60 days × 2/day = 120 needed; reorder = max(0, 120-40) = 80
        self.assertAlmostEqual(result.recommended_reorder_quantity, 80.0, places=4)

    def test_consumption_outside_window_is_ignored(self):
        # 5 dispenses 60 days ago (outside 30-day window).
        for _ in range(5):
            self._dispense(10, days_ago=60)
        # 1 dispense yesterday — inside window.
        self._dispense(5, days_ago=1)
        result = forecast_for_drug(self.drug, window_days=30, target_days=60)
        self.assertEqual(result.total_dispensed_in_window, 5.0)

    def test_no_reorder_needed_when_stock_exceeds_target(self):
        StockItem.objects.create(drug=self.drug, lot_number="L2", quantity=Decimal("400"))
        self._dispense(3, days_ago=10)
        result = forecast_for_drug(self.drug, window_days=30, target_days=60)
        # current ≥ target → reorder = 0
        self.assertEqual(result.recommended_reorder_quantity, 0.0)

    def test_invalid_window_raises(self):
        with self.assertRaises(ValueError):
            forecast_for_drug(self.drug, window_days=0)
        with self.assertRaises(ValueError):
            forecast_for_drug(self.drug, target_days=-3)


class DemandForecastEndpointTest(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="pharmacy_ai",
            defaults={"is_enabled": True},
        )
        self.user = _make_user(role_name="phai_view", perms=["pharmacy_ai.read"])
        self.client.force_authenticate(user=self.user)
        self.drug = Drug.objects.create(generic_name="Dipirona", name="Dipirona")
        self.stock = StockItem.objects.create(drug=self.drug, lot_number="LX")
        StockMovement.objects.create(
            stock_item=self.stock,
            movement_type="entry",
            quantity=Decimal("50"),
            performed_by=self.user,
        )

    def test_get_returns_forecast_payload(self):
        resp = self.client.get(FORECAST_URL, {"drug": str(self.drug.pk)})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["drug_id"], str(self.drug.pk))
        self.assertEqual(resp.data["window_days"], 30)
        self.assertEqual(resp.data["target_days"], 60)
        self.assertEqual(resp.data["current_stock"], 50.0)
        self.assertEqual(resp.data["avg_daily_consumption"], 0.0)
        self.assertIsNone(resp.data["projected_days_of_supply"])

    def test_get_respects_custom_window_and_target(self):
        resp = self.client.get(
            FORECAST_URL,
            {"drug": str(self.drug.pk), "window_days": "7", "target_days": "14"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["window_days"], 7)
        self.assertEqual(resp.data["target_days"], 14)

    def test_missing_drug_param_returns_400(self):
        resp = self.client.get(FORECAST_URL)
        self.assertEqual(resp.status_code, 400)

    def test_non_integer_window_returns_400(self):
        resp = self.client.get(FORECAST_URL, {"drug": str(self.drug.pk), "window_days": "abc"})
        self.assertEqual(resp.status_code, 400)

    def test_negative_window_returns_400(self):
        resp = self.client.get(FORECAST_URL, {"drug": str(self.drug.pk), "window_days": "0"})
        self.assertEqual(resp.status_code, 400)

    def test_unknown_drug_returns_404(self):
        resp = self.client.get(FORECAST_URL, {"drug": "00000000-0000-4000-8000-000000000000"})
        self.assertEqual(resp.status_code, 404)

    def test_blocked_when_module_disabled(self):
        FeatureFlag.objects.filter(tenant=self.__class__.tenant, module_key="pharmacy_ai").update(
            is_enabled=False
        )
        resp = self.client.get(FORECAST_URL, {"drug": str(self.drug.pk)})
        self.assertEqual(resp.status_code, 403)

    def test_blocked_without_pharmacy_ai_read(self):
        no_perm = _make_user(role_name="phai_noperm", perms=["patients.read"])
        self.client.force_authenticate(user=no_perm)
        resp = self.client.get(FORECAST_URL, {"drug": str(self.drug.pk)})
        self.assertEqual(resp.status_code, 403)

    def test_unauthenticated_returns_401(self):
        self.client.logout()
        resp = self.client.get(FORECAST_URL, {"drug": str(self.drug.pk)})
        self.assertIn(resp.status_code, [401, 403])
