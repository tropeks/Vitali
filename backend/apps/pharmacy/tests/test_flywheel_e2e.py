"""End-to-end flywheel cycle tests for the stockout wedge.

Sprint S30-05: proves the full alert → override → outcome → signal cycle for
the stockout (S-wedge). Walks the happy-path end-to-end: flag on → drug with
velocity → evaluate_all → StockAlert(open) → acknowledge → drive balance to 0
→ grade → true_positive + AuditLog.
"""

import datetime
from decimal import Decimal

from django.utils import timezone

from apps.core.models import AuditLog, FeatureFlag, User
from apps.pharmacy.models import Drug, StockAlert, StockItem, StockMovement
from apps.pharmacy.services.stockout_safety import StockoutService
from apps.test_utils import TenantTestCase


class TestStockoutFlywheelFullCycle(TenantTestCase):
    """Full alert → acknowledge → true_positive grading cycle for the stockout wedge."""

    def setUp(self):
        self.tenant = self.__class__.tenant
        FeatureFlag.objects.update_or_create(
            tenant=self.tenant,
            module_key="stockout_safety",
            defaults={"is_enabled": True},
        )
        self.now = timezone.now()
        self.today = self.now.date()
        self.user = User.objects.create_user(
            email="gestor_flywheel@test.com",
            full_name="Gestor Flywheel",
            password="Str0ng!Pass#2024",
        )

    def _drug(self, **kwargs):
        defaults = {"name": "Amoxicilina 500mg", "lead_time_days": 7}
        defaults.update(kwargs)
        return Drug.objects.create(**defaults)

    def _stock_item(self, *, drug, lot="FW-L1"):
        return StockItem.objects.create(drug=drug, lot_number=lot, quantity=Decimal("0"))

    def _receive(self, item, qty):
        StockMovement(
            stock_item=item, movement_type="entry", quantity=Decimal(qty)
        ).save()

    def _dispense(self, item, qty):
        StockMovement(
            stock_item=item, movement_type="dispense", quantity=-Decimal(qty)
        ).save()

    def test_stockout_flywheel_full_cycle(self):
        """flag ON → drug with lead_time + velocity → evaluate_all → StockAlert(open,
        stockout_risk) → acknowledge → drive balance to 0 by predicted_date →
        grade_predictions → true_positive + AuditLog(action='stockout_prediction_graded').
        """
        # ── Step 1: drug with lead_time configured ───────────────────────────────
        drug = self._drug(lead_time_days=7)
        item = self._stock_item(drug=drug)

        # Build dispense velocity ≈ 1/day over past 30 days, but keep balance LOW
        # so days_to_stockout (balance/velocity) ≤ lead_time_days triggers the alert.
        # Receive 15 units to start; dispense 10 (3 events × Decimal("3.33..") ≈ 10).
        # Balance after: 15 - 10 = 5. velocity ≈ 10/30 = 0.33/day.
        # days_to_stockout ≈ 5/0.33 ≈ 15 days > lead_time=7 — still sufficient.
        #
        # Better: receive 5 units, dispense 3×1 = 3 over 30 days → velocity=0.1/day;
        # days_to_stockout = 5/0.1 = 50 still sufficient.
        #
        # Easiest: big velocity + small balance.
        # Receive 10, dispense 3×3=9 quickly → balance=1, velocity=9/30=0.3/day,
        # days_to_stockout=1/0.3=3.3 days < lead_time=7 → RISK.
        self._receive(item, "10")
        for i in range(3):
            mv = StockMovement(
                stock_item=item,
                movement_type="dispense",
                quantity=Decimal("-3"),
            )
            mv.save()
            # Spread dispenses within the 30-day window (days 1, 10, 20 ago)
            ts = self.now - datetime.timedelta(days=1 + i * 9)
            StockMovement.objects.filter(pk=mv.pk).update(created_at=ts)

        # Balance: 10 - 9 = 1 unit. Velocity ≈ 9/30 = 0.3/day.
        # days_to_stockout ≈ 1/0.3 ≈ 3.3 days ≤ lead_time=7 → STOCKOUT_RISK.
        item.refresh_from_db()

        # ── Step 2: evaluate_all → StockAlert(open, stockout_risk) ─────────────
        svc = StockoutService(requesting_user=self.user)
        svc.evaluate_all(now=self.now)

        alert = StockAlert.objects.filter(
            drug=drug, kind=StockAlert.Kind.STOCKOUT_RISK
        ).first()
        assert alert is not None, "evaluate_all must create a stockout_risk alert"
        assert alert.status == StockAlert.Status.OPEN
        assert alert.outcome == StockAlert.Outcome.PENDING
        assert alert.predicted_date is not None

        # ── Step 3: acknowledge → override preserved ─────────────────────────────
        alert.acknowledge(self.user, note="pedido de compra já foi enviado")
        alert.refresh_from_db()
        assert alert.status == StockAlert.Status.ACKNOWLEDGED
        assert alert.acknowledged_by == self.user

        # ── Step 4: drive balance to 0 by the predicted_date ────────────────────
        # Dispense all remaining stock → balance hits 0 → true_positive condition
        item.refresh_from_db()
        current_balance = item.quantity
        if current_balance > 0:
            self._dispense(item, str(current_balance))
        item.refresh_from_db()
        assert item.quantity == Decimal("0"), "balance must be zero for true_positive"

        # ── Step 5: set alert's predicted_date to yesterday so grading fires ─────
        past_date = self.today - datetime.timedelta(days=1)
        StockAlert.objects.filter(pk=alert.pk).update(predicted_date=past_date)
        # Also reset outcome back to PENDING so grade_predictions picks it up
        StockAlert.objects.filter(pk=alert.pk).update(outcome=StockAlert.Outcome.PENDING)
        alert.refresh_from_db()
        assert alert.predicted_date == past_date
        assert alert.outcome == StockAlert.Outcome.PENDING

        # ── Step 6: grade_predictions → true_positive ────────────────────────────
        svc2 = StockoutService(requesting_user=self.user)
        counts = svc2.grade_predictions(now=self.now)

        alert.refresh_from_db()
        assert alert.outcome == StockAlert.Outcome.TRUE_POSITIVE, (
            f"expected true_positive, got {alert.outcome}"
        )
        assert alert.graded_at is not None
        assert counts.get(StockAlert.Outcome.TRUE_POSITIVE, 0) >= 1

        # ── Step 7: AuditLog carries outcome ────────────────────────────────────
        log = AuditLog.objects.filter(
            action="stockout_prediction_graded",
            resource_id=str(alert.id),
        ).first()
        assert log is not None, "AuditLog must be written after grading"
        assert log.new_data["outcome"] == StockAlert.Outcome.TRUE_POSITIVE
