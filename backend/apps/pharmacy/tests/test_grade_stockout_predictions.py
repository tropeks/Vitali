"""Flywheel grading tests — stockout-prediction wedge S4.

Exercises the ``grade_stockout_predictions`` management command: it grades every
PAST-DUE ``stockout_risk`` prediction by what actually happened —
``true_positive`` (stocked out), ``intercepted`` (a purchase_order_receiving
landed in the prediction window → the system worked), or ``false_positive``
(stock survived with no receipt). Not-due alerts stay ``pending``; a second run
is idempotent; ``expiry_waste`` alerts are never graded.

``created_at`` on StockAlert is auto_now_add, so tests stamp it explicitly with a
queryset ``.update()`` to position the receipt window precisely.

Run: python manage.py test apps.pharmacy.tests.test_grade_stockout_predictions
"""

import datetime
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.utils import timezone

from apps.core.models import AuditLog, User
from apps.pharmacy.models import Drug, Material, StockAlert, StockItem, StockMovement
from apps.test_utils import TenantTestCase


class GradeStockoutBaseCase(TenantTestCase):
    def setUp(self):
        self.today = timezone.now().date()
        self.user = User.objects.create_user(
            email="gestor@test.com",
            full_name="Gestor Suprimentos",
            password="Str0ng!Pass#2024",
        )

    # ── fixtures ────────────────────────────────────────────────────────────────

    def _drug(self, **kwargs):
        defaults = {"name": "Dipirona 500mg", "lead_time_days": 10}
        defaults.update(kwargs)
        return Drug.objects.create(**defaults)

    def _material(self, **kwargs):
        defaults = {"name": "Seringa 10ml", "lead_time_days": 10}
        defaults.update(kwargs)
        return Material.objects.create(**defaults)

    def _stock_item(self, *, drug=None, material=None, lot="L1"):
        return StockItem.objects.create(
            drug=drug, material=material, lot_number=lot, quantity=Decimal("0")
        )

    def _receive(self, item, qty):
        StockMovement(stock_item=item, movement_type="entry", quantity=Decimal(qty)).save()

    def _dispense(self, item, qty):
        # Dispenses are stored as negative magnitudes on the ledger.
        StockMovement(stock_item=item, movement_type="dispense", quantity=-Decimal(qty)).save()

    def _po_receive(self, item, qty, *, at=None):
        mv = StockMovement(
            stock_item=item, movement_type="purchase_order_receiving", quantity=Decimal(qty)
        )
        mv.save()
        if at is not None:
            StockMovement.objects.filter(pk=mv.pk).update(created_at=at)

    def _alert(
        self,
        *,
        drug=None,
        material=None,
        kind=StockAlert.Kind.STOCKOUT_RISK,
        predicted_date,
        created_at=None,
        outcome=StockAlert.Outcome.PENDING,
    ):
        alert = StockAlert.objects.create(
            drug=drug,
            material=material,
            kind=kind,
            severity=StockAlert.Severity.ADVISE,
            status=StockAlert.Status.OPEN,
            predicted_date=predicted_date,
            outcome=outcome,
            message="risco de ruptura",
        )
        if created_at is not None:
            StockAlert.objects.filter(pk=alert.pk).update(created_at=created_at)
            alert.refresh_from_db()
        return alert

    def _run(self):
        out = StringIO()
        call_command("grade_stockout_predictions", stdout=out)
        return out.getvalue()


class TruePositiveTests(GradeStockoutBaseCase):
    def test_balance_zero_is_true_positive(self):
        drug = self._drug()
        self._stock_item(drug=drug)  # quantity 0, no receipts → balance 0
        alert = self._alert(drug=drug, predicted_date=self.today - datetime.timedelta(days=1))
        self._run()
        alert.refresh_from_db()
        self.assertEqual(alert.outcome, StockAlert.Outcome.TRUE_POSITIVE)
        self.assertIsNotNone(alert.graded_at)

    def test_no_stock_item_at_all_is_true_positive(self):
        # No StockItem rows → balance aggregate is None → treated as 0 → stocked out.
        drug = self._drug()
        alert = self._alert(drug=drug, predicted_date=self.today - datetime.timedelta(days=2))
        self._run()
        alert.refresh_from_db()
        self.assertEqual(alert.outcome, StockAlert.Outcome.TRUE_POSITIVE)


class InterceptedTests(GradeStockoutBaseCase):
    def test_receipt_in_window_with_balance_is_intercepted_not_false_positive(self):
        drug = self._drug()
        item = self._stock_item(drug=drug)
        # Alert raised 8 days ago, predicted stockout yesterday.
        created = timezone.now() - datetime.timedelta(days=8)
        predicted = self.today - datetime.timedelta(days=1)
        alert = self._alert(drug=drug, predicted_date=predicted, created_at=created)
        # A PO receipt landed 3 days ago (inside created..predicted), leaving balance > 0.
        self._po_receive(item, "50", at=timezone.now() - datetime.timedelta(days=3))
        self._run()
        alert.refresh_from_db()
        self.assertEqual(alert.outcome, StockAlert.Outcome.INTERCEPTED)
        self.assertIsNotNone(alert.graded_at)

    def test_receipt_before_alert_created_is_not_intercepted(self):
        # A receipt that predates the alert is NOT evidence the warning was acted
        # on → with balance > 0 and no in-window receipt → false_positive.
        drug = self._drug()
        item = self._stock_item(drug=drug)
        created = timezone.now() - datetime.timedelta(days=5)
        predicted = self.today - datetime.timedelta(days=1)
        alert = self._alert(drug=drug, predicted_date=predicted, created_at=created)
        self._receive(item, "50")  # leaves balance > 0
        self._po_receive(item, "10", at=timezone.now() - datetime.timedelta(days=20))  # pre-alert
        self._run()
        alert.refresh_from_db()
        self.assertEqual(alert.outcome, StockAlert.Outcome.FALSE_POSITIVE)


class OrderTests(GradeStockoutBaseCase):
    def test_zero_stock_wins_over_intercepted_even_with_po_receipt(self):
        # LOCKED order: TRUE_POSITIVE checked before INTERCEPTED. A product that
        # received a PO in-window but STILL hit zero is a true stockout (the
        # receipt wasn't enough) — zero-stock wins.
        drug = self._drug()
        item = self._stock_item(drug=drug)  # quantity 0 → balance 0
        created = timezone.now() - datetime.timedelta(days=8)
        predicted = self.today - datetime.timedelta(days=1)
        alert = self._alert(drug=drug, predicted_date=predicted, created_at=created)
        # A PO receipt landed in-window (+50), but it was all consumed → current
        # balance back to 0. Zero-stock must win over the in-window receipt.
        self._po_receive(item, "50", at=timezone.now() - datetime.timedelta(days=3))
        self._dispense(item, "50")
        item.refresh_from_db()
        self.assertEqual(item.quantity, Decimal("0"))
        self._run()
        alert.refresh_from_db()
        self.assertEqual(alert.outcome, StockAlert.Outcome.TRUE_POSITIVE)


class FalsePositiveTests(GradeStockoutBaseCase):
    def test_balance_positive_no_receipt_is_false_positive(self):
        drug = self._drug()
        item = self._stock_item(drug=drug)
        self._receive(item, "40")  # balance > 0, no PO receipt
        alert = self._alert(drug=drug, predicted_date=self.today - datetime.timedelta(days=1))
        self._run()
        alert.refresh_from_db()
        self.assertEqual(alert.outcome, StockAlert.Outcome.FALSE_POSITIVE)
        self.assertIsNotNone(alert.graded_at)


class NotDueTests(GradeStockoutBaseCase):
    def test_future_prediction_stays_pending(self):
        drug = self._drug()
        self._stock_item(drug=drug)  # balance 0, but not due
        alert = self._alert(drug=drug, predicted_date=self.today + datetime.timedelta(days=5))
        self._run()
        alert.refresh_from_db()
        self.assertEqual(alert.outcome, StockAlert.Outcome.PENDING)
        self.assertIsNone(alert.graded_at)


class IdempotencyTests(GradeStockoutBaseCase):
    def test_second_run_does_not_regrade(self):
        drug = self._drug()
        self._stock_item(drug=drug)  # balance 0 → true_positive
        alert = self._alert(drug=drug, predicted_date=self.today - datetime.timedelta(days=1))
        self._run()
        alert.refresh_from_db()
        self.assertEqual(alert.outcome, StockAlert.Outcome.TRUE_POSITIVE)
        first_graded_at = alert.graded_at
        audit_count_after_first = AuditLog.objects.filter(
            action="stockout_prediction_graded"
        ).count()

        # Second run: nothing pending+past-due remains → no change, no new audit.
        self._run()
        alert.refresh_from_db()
        self.assertEqual(alert.outcome, StockAlert.Outcome.TRUE_POSITIVE)
        self.assertEqual(alert.graded_at, first_graded_at)
        self.assertEqual(
            AuditLog.objects.filter(action="stockout_prediction_graded").count(),
            audit_count_after_first,
        )

    def test_one_audit_log_per_grading(self):
        drug = self._drug()
        self._stock_item(drug=drug)
        alert = self._alert(drug=drug, predicted_date=self.today - datetime.timedelta(days=1))
        self._run()
        logs = AuditLog.objects.filter(
            action="stockout_prediction_graded", resource_id=str(alert.id)
        )
        self.assertEqual(logs.count(), 1)
        self.assertEqual(logs.first().new_data["outcome"], StockAlert.Outcome.TRUE_POSITIVE)


class ExpiryWasteNotGradedTests(GradeStockoutBaseCase):
    def test_expiry_waste_alert_is_never_graded(self):
        drug = self._drug()
        item = self._stock_item(drug=drug)
        expiry_alert = StockAlert.objects.create(
            drug=drug,
            stock_item=item,
            kind=StockAlert.Kind.EXPIRY_WASTE,
            severity=StockAlert.Severity.ADVISE,
            status=StockAlert.Status.OPEN,
            predicted_date=self.today - datetime.timedelta(days=1),
            predicted_waste_qty=Decimal("10"),
            message="desperdício",
        )
        self._run()
        expiry_alert.refresh_from_db()
        self.assertEqual(expiry_alert.outcome, StockAlert.Outcome.PENDING)
        self.assertIsNone(expiry_alert.graded_at)


class MaterialAndSummaryTests(GradeStockoutBaseCase):
    def test_material_alert_graded_and_summary_counts(self):
        # One true_positive (material, balance 0), one false_positive (drug, balance>0).
        material = self._material()
        self._stock_item(material=material)  # balance 0
        self._alert(material=material, predicted_date=self.today - datetime.timedelta(days=1))

        drug = self._drug(name="Outro")
        item = self._stock_item(drug=drug)
        self._receive(item, "30")
        self._alert(drug=drug, predicted_date=self.today - datetime.timedelta(days=1))

        output = self._run()
        self.assertIn("2 predição", output)
        self.assertEqual(
            StockAlert.objects.filter(outcome=StockAlert.Outcome.TRUE_POSITIVE).count(), 1
        )
        self.assertEqual(
            StockAlert.objects.filter(outcome=StockAlert.Outcome.FALSE_POSITIVE).count(), 1
        )


class ServiceGradePredictionsTests(GradeStockoutBaseCase):
    """grade_predictions lives on StockoutService; ``now`` is injected so the
    past-due cutoff is reproducible (mirrors evaluate_all's injected now)."""

    def test_injected_now_controls_past_due_cutoff_and_returns_counts(self):
        from apps.pharmacy.services.stockout_safety import StockoutService

        drug = self._drug()
        self._stock_item(drug=drug)  # balance 0
        predicted = self.today + datetime.timedelta(days=3)
        alert = self._alert(drug=drug, predicted_date=predicted)

        # With now = real today, the alert is in the FUTURE → not graded.
        counts = StockoutService().grade_predictions(now=timezone.now())
        alert.refresh_from_db()
        self.assertEqual(alert.outcome, StockAlert.Outcome.PENDING)
        self.assertEqual(sum(counts.values()), 0)

        # Advance now past the predicted date → it becomes past-due → graded.
        future_now = timezone.now() + datetime.timedelta(days=5)
        counts = StockoutService().grade_predictions(now=future_now)
        alert.refresh_from_db()
        self.assertEqual(alert.outcome, StockAlert.Outcome.TRUE_POSITIVE)
        self.assertEqual(alert.graded_at, future_now)
        self.assertEqual(counts[StockAlert.Outcome.TRUE_POSITIVE], 1)
