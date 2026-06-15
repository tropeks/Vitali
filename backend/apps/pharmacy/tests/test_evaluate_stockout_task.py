"""S30-02: evaluate_stockout Celery task + beat registration tests.

Tests:
  - task runs evaluate_all per tenant (flag ON/OFF behaviour tested via service)
  - graceful degradation: product without lead_time_days → no StockAlert (engine inert)
  - product with lead_time_days + velocity → StockAlert(kind=stockout_risk)
  - PeriodicTask "pharmacy.evaluate_stockout" registered after migration

Run: docker compose exec -T django pytest apps/pharmacy/tests/test_evaluate_stockout_task.py -v
"""

import datetime
from decimal import Decimal

from django.utils import timezone

from apps.core.models import FeatureFlag
from apps.pharmacy.models import Drug, Material, StockAlert, StockItem, StockMovement
from apps.pharmacy.services.stockout_safety import StockoutService
from apps.test_utils import TenantTestCase


def _enable_flag(tenant):
    FeatureFlag.objects.update_or_create(
        tenant=tenant, module_key="stockout_safety", defaults={"is_enabled": True}
    )


class EvaluateStockoutTaskTests(TenantTestCase):
    """Graceful-degradation and alert-creation tests for StockoutService.evaluate_all,
    which is what the pharmacy.evaluate_stockout task calls via the management command."""

    def setUp(self):
        self.now = timezone.now() + datetime.timedelta(days=1)

    def _drug(self, **kwargs):
        defaults = {"name": "Dipirona 500mg", "unit_of_measure": "un"}
        defaults.update(kwargs)
        return Drug.objects.create(**defaults)

    def _dispense(self, item, qty, *, n=1):
        for _ in range(n):
            StockMovement.objects.create(
                stock_item=item, movement_type="dispense", quantity=-Decimal(qty)
            )

    def _receive(self, item, qty):
        StockMovement.objects.create(
            stock_item=item, movement_type="entry", quantity=Decimal(qty)
        )

    def test_evaluate_all_without_lead_time_is_graceful(self):
        """Drug with no lead_time_days → engine inert → no StockAlert, no exception."""
        _enable_flag(self.tenant)
        drug = self._drug(lead_time_days=None)
        item = StockItem.objects.create(drug=drug, lot_number="L1", quantity=Decimal("0"))
        self._receive(item, "1000")
        self._dispense(item, "5", n=10)

        svc = StockoutService()
        svc.evaluate_all(now=self.now)

        self.assertEqual(
            StockAlert.objects.filter(kind="stockout_risk").count(),
            0,
            "No stockout_risk alert should be created when lead_time_days is None",
        )

    def test_evaluate_all_with_lead_time_creates_alert(self):
        """Drug with lead_time_days + dispense velocity → StockAlert(stockout_risk)."""
        _enable_flag(self.tenant)
        drug = self._drug(lead_time_days=10)
        item = StockItem.objects.create(drug=drug, lot_number="L1", quantity=Decimal("0"))
        # receive enough stock then dispense rapidly → velocity triggers stockout alert
        self._receive(item, "180")
        self._dispense(item, "5", n=30)  # 150 units in 30 moves → ~5 units/day

        svc = StockoutService()
        svc.evaluate_all(now=self.now)

        alert = StockAlert.objects.filter(kind="stockout_risk").first()
        self.assertIsNotNone(alert, "A stockout_risk alert should be created")
        self.assertIsNotNone(alert.suggested_reorder_qty)

    def test_evaluate_all_flag_off_is_noop(self):
        """Flag OFF → evaluate_all is a no-op, zero alerts."""
        FeatureFlag.objects.update_or_create(
            tenant=self.tenant, module_key="stockout_safety", defaults={"is_enabled": False}
        )
        drug = self._drug(lead_time_days=10)
        item = StockItem.objects.create(drug=drug, lot_number="L1", quantity=Decimal("0"))
        self._receive(item, "180")
        self._dispense(item, "5", n=30)

        svc = StockoutService()
        svc.evaluate_all(now=self.now)

        self.assertEqual(StockAlert.objects.filter(kind="stockout_risk").count(), 0)


class EvaluateStockoutBeatRegistrationTests(TenantTestCase):
    """Assert that the pharmacy.evaluate_stockout PeriodicTask exists in the DB."""

    def test_evaluate_stockout_periodic_task_registered(self):
        """Migration 0020 must register a PeriodicTask named pharmacy.evaluate_stockout."""
        try:
            from django_celery_beat.models import PeriodicTask
        except ImportError:
            self.skipTest("django_celery_beat not installed")

        task = PeriodicTask.objects.filter(name="pharmacy.evaluate_stockout").first()
        self.assertIsNotNone(
            task,
            "pharmacy.evaluate_stockout PeriodicTask must be registered by migration 0020",
        )
        self.assertTrue(task.enabled, "pharmacy.evaluate_stockout must be enabled")
        # Must run BEFORE the grade job (02:30 < 03:00)
        self.assertEqual(task.crontab.hour, "2")
        self.assertEqual(task.crontab.minute, "30")
