"""Orchestrator tests for the stockout-prediction wedge (PR S2).

Mirrors apps.billing.tests.test_glosa_safety: flag-OFF no-op regression guard,
flag-ON persistence, inert guards, single-query dispense-history resolution,
expiry/waste FEFO, override-preservation, and the unique-constraint anti-clobber.

The StockoutService is the orchestrator; the engine (compute_daily_velocity,
StockoutChecker, predict_expiry_waste) is pure and tested separately in
test_stockout_checker. ``now`` is injected so every evaluation is reproducible.

Run: python manage.py test apps.pharmacy.tests.test_stockout_safety
"""

import datetime
from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.core.models import FeatureFlag, User
from apps.pharmacy.models import Drug, Material, StockAlert, StockItem, StockMovement
from apps.pharmacy.services.stockout_safety import StockoutService
from apps.test_utils import TenantTestCase


def _enable_flag(tenant):
    FeatureFlag.objects.update_or_create(
        tenant=tenant, module_key="stockout_safety", defaults={"is_enabled": True}
    )


def _disable_flag(tenant):
    FeatureFlag.objects.update_or_create(
        tenant=tenant, module_key="stockout_safety", defaults={"is_enabled": False}
    )


class StockoutSafetyBaseCase(TenantTestCase):
    def setUp(self):
        # ``now`` is injected into the service. StockMovement.created_at is
        # auto_now_add (set to the real clock when the dispense is recorded during
        # the test body, AFTER setUp). Pin ``now`` one day in the FUTURE so every
        # just-created dispense event falls inside the trailing window AND
        # satisfies ts <= now; the +1 day is negligible against the 30-day window.
        self.now = timezone.now() + datetime.timedelta(days=1)
        self.user = User.objects.create_user(
            email="gestor@test.com",
            full_name="Gestor Suprimentos",
            password="Str0ng!Pass#2024",
        )

    # ── fixtures ────────────────────────────────────────────────────────────────

    def _drug(self, **kwargs):
        defaults = {"name": "Dipirona 500mg", "unit_of_measure": "un"}
        defaults.update(kwargs)
        return Drug.objects.create(**defaults)

    def _material(self, **kwargs):
        defaults = {"name": "Seringa 10ml", "unit_of_measure": "un"}
        defaults.update(kwargs)
        return Material.objects.create(**defaults)

    def _stock_item(self, *, drug=None, material=None, qty="0", lot="L1", expiry=None):
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
        """Record ``n`` dispense movements of magnitude ``qty`` (stored negative)."""
        for _ in range(n):
            StockMovement(stock_item=item, movement_type="dispense", quantity=-Decimal(qty)).save()

    def _svc(self):
        return StockoutService(requesting_user=self.user)


class FlagOffNoOpTests(StockoutSafetyBaseCase):
    def test_evaluate_item_noop_when_flag_off(self):
        _disable_flag(self.__class__.tenant)
        drug = self._drug(lead_time_days=10, reorder_point=Decimal("5"))
        item = self._stock_item(drug=drug, qty="3")
        self._receive(item, "100")
        self._dispense(item, "10", n=5)
        self._svc().evaluate_item(drug, now=self.now)
        self.assertEqual(StockAlert.objects.count(), 0)

    def test_evaluate_all_noop_when_flag_off(self):
        _disable_flag(self.__class__.tenant)
        drug = self._drug(lead_time_days=10)
        item = self._stock_item(drug=drug, qty="3")
        self._receive(item, "100")
        self._dispense(item, "10", n=5)
        self._svc().evaluate_all(now=self.now)
        self.assertEqual(StockAlert.objects.count(), 0)


class StockoutRiskTests(StockoutSafetyBaseCase):
    def setUp(self):
        super().setUp()
        _enable_flag(self.__class__.tenant)

    def test_predicts_stockout_risk_alert(self):
        # balance 30, velocity ~5/day → ~6 days runway, lead_time 10 → RISK.
        drug = self._drug(lead_time_days=10)
        item = self._stock_item(drug=drug)
        self._receive(item, "180")  # plenty received; 150 dispensed → 30 left
        self._dispense(item, "10", n=15)  # 150 over window, ~5/day
        self._svc().evaluate_item(drug, now=self.now)

        alert = StockAlert.objects.get(drug=drug, kind=StockAlert.Kind.STOCKOUT_RISK)
        self.assertEqual(alert.severity, StockAlert.Severity.ADVISE)
        self.assertEqual(alert.status, StockAlert.Status.OPEN)
        self.assertEqual(alert.source, StockAlert.Source.ENGINE)
        self.assertIsNotNone(alert.predicted_date)
        self.assertIsNotNone(alert.days_to_stockout)
        self.assertEqual(alert.engine_version, "s2")
        self.assertIsNone(alert.material_id)

    def test_sufficient_runway_no_alert(self):
        # Huge balance, modest velocity, generous lead → sufficient → no alert.
        drug = self._drug(lead_time_days=5)
        item = self._stock_item(drug=drug)
        self._receive(item, "10000")
        self._dispense(item, "1", n=5)  # ~0.16/day
        self._svc().evaluate_item(drug, now=self.now)
        self.assertEqual(StockAlert.objects.filter(kind=StockAlert.Kind.STOCKOUT_RISK).count(), 0)

    def test_sufficient_resolves_stale_open_alert(self):
        drug = self._drug(lead_time_days=10)
        # Pre-existing open stockout alert from a prior run.
        StockAlert.objects.create(
            drug=drug,
            kind=StockAlert.Kind.STOCKOUT_RISK,
            severity=StockAlert.Severity.ADVISE,
            status=StockAlert.Status.OPEN,
            message="velho",
        )
        item = self._stock_item(drug=drug)
        self._receive(item, "10000")
        self._dispense(item, "1", n=5)  # now plenty of runway
        self._svc().evaluate_item(drug, now=self.now)
        alert = StockAlert.objects.get(drug=drug, kind=StockAlert.Kind.STOCKOUT_RISK)
        self.assertEqual(alert.status, StockAlert.Status.RESOLVED)

    def test_material_stockout_risk(self):
        material = self._material(lead_time_days=10)
        item = self._stock_item(material=material)
        self._receive(item, "180")
        self._dispense(item, "10", n=15)
        self._svc().evaluate_item(material, now=self.now)
        alert = StockAlert.objects.get(material=material, kind=StockAlert.Kind.STOCKOUT_RISK)
        self.assertIsNone(alert.drug_id)
        self.assertEqual(alert.material_id, material.id)


class InertTests(StockoutSafetyBaseCase):
    def setUp(self):
        super().setUp()
        _enable_flag(self.__class__.tenant)

    def test_no_lead_time_config_inert(self):
        drug = self._drug()  # no lead_time_days
        item = self._stock_item(drug=drug)
        self._receive(item, "180")
        self._dispense(item, "10", n=15)
        self._svc().evaluate_item(drug, now=self.now)
        self.assertEqual(StockAlert.objects.count(), 0)

    def test_fewer_than_3_dispenses_inert(self):
        drug = self._drug(lead_time_days=10)
        item = self._stock_item(drug=drug)
        self._receive(item, "100")
        self._dispense(item, "10", n=2)  # < min_events (3) → velocity None
        self._svc().evaluate_item(drug, now=self.now)
        self.assertEqual(StockAlert.objects.count(), 0)


class SingleQueryTests(StockoutSafetyBaseCase):
    def setUp(self):
        super().setUp()
        _enable_flag(self.__class__.tenant)

    def test_dispense_history_one_query_per_product(self):
        drug = self._drug(lead_time_days=10)
        # Multiple lots + many dispense movements across lots.
        item1 = self._stock_item(drug=drug, lot="A")
        item2 = self._stock_item(drug=drug, lot="B")
        self._receive(item1, "100")
        self._receive(item2, "100")
        self._dispense(item1, "5", n=4)
        self._dispense(item2, "5", n=4)

        svc = self._svc()
        # The dispense-history resolution must hit pharmacy_stockmovement exactly
        # ONCE regardless of how many lots/movements exist (no per-lot N+1).
        # Measure the StockMovement query specifically so the django-tenants
        # `SET search_path` harness overhead isn't miscounted as a data query.
        with CaptureQueriesContext(connection) as ctx:
            svc._dispense_history(drug, is_drug=True, now=self.now)
        mv_queries = [q for q in ctx.captured_queries if "pharmacy_stockmovement" in q["sql"]]
        self.assertEqual(
            len(mv_queries), 1, f"expected 1 StockMovement query, got {len(mv_queries)}"
        )


class ExpiryWasteTests(StockoutSafetyBaseCase):
    def setUp(self):
        super().setUp()
        _enable_flag(self.__class__.tenant)

    def test_lot_expiring_before_consumption_flags_waste(self):
        drug = self._drug(lead_time_days=10)
        # velocity ~1/day. Lot of 100 un. expiring in 10 days → only ~10 consumed,
        # ~90 wasted.
        soon = (self.now + datetime.timedelta(days=10)).date()
        item = self._stock_item(drug=drug, lot="EXP", expiry=soon)
        self._receive(item, "100")
        self._dispense(item, "1", n=30)  # 30 over 30d → ~1/day
        self._svc().evaluate_item(drug, now=self.now)

        alert = StockAlert.objects.get(kind=StockAlert.Kind.EXPIRY_WASTE)
        self.assertEqual(alert.stock_item_id, item.id)
        self.assertEqual(alert.severity, StockAlert.Severity.ADVISE)
        self.assertIsNotNone(alert.predicted_waste_qty)
        self.assertGreater(alert.predicted_waste_qty, Decimal("0"))
        self.assertEqual(alert.predicted_date, soon)

    def test_lot_consumed_before_expiry_no_waste(self):
        drug = self._drug(lead_time_days=10)
        # Small lot, far expiry, brisk velocity → fully consumed → no waste.
        far = (self.now + datetime.timedelta(days=365)).date()
        item = self._stock_item(drug=drug, lot="OK", expiry=far)
        self._receive(item, "100")
        self._dispense(item, "1", n=30)  # ~1/day; 70 on-hand burns in ~70d ≪ 365
        self._svc().evaluate_item(drug, now=self.now)
        self.assertEqual(StockAlert.objects.filter(kind=StockAlert.Kind.EXPIRY_WASTE).count(), 0)

    def test_no_velocity_no_expiry_alert(self):
        drug = self._drug(lead_time_days=10)
        soon = (self.now + datetime.timedelta(days=5)).date()
        item = self._stock_item(drug=drug, lot="EXP", expiry=soon)
        self._receive(item, "100")
        self._dispense(item, "1", n=2)  # < 3 events → velocity None → inert
        self._svc().evaluate_item(drug, now=self.now)
        self.assertEqual(StockAlert.objects.filter(kind=StockAlert.Kind.EXPIRY_WASTE).count(), 0)


class OverridePreservationTests(StockoutSafetyBaseCase):
    def setUp(self):
        super().setUp()
        _enable_flag(self.__class__.tenant)

    def _make_risk(self, drug):
        item = self._stock_item(drug=drug)
        self._receive(item, "180")
        self._dispense(item, "10", n=15)
        return item

    def test_acknowledged_unchanged_prediction_preserved(self):
        drug = self._drug(lead_time_days=10)
        self._make_risk(drug)
        svc = self._svc()
        svc.evaluate_item(drug, now=self.now)

        alert = StockAlert.objects.get(kind=StockAlert.Kind.STOCKOUT_RISK)
        alert.acknowledge(self.user, note="ja pedi reposicao")
        self.assertEqual(alert.status, StockAlert.Status.ACKNOWLEDGED)

        # Re-eval with the SAME prediction → must NOT reopen.
        svc.evaluate_item(drug, now=self.now)
        alert.refresh_from_db()
        self.assertEqual(alert.status, StockAlert.Status.ACKNOWLEDGED)
        self.assertEqual(alert.note, "ja pedi reposicao")

    def test_changed_prediction_reopens(self):
        drug = self._drug(lead_time_days=10)
        item = self._make_risk(drug)
        svc = self._svc()
        svc.evaluate_item(drug, now=self.now)
        alert = StockAlert.objects.get(kind=StockAlert.Kind.STOCKOUT_RISK)
        alert.acknowledge(self.user, note="ok")

        # Change the prediction: dispense more so the balance/runway shifts and the
        # message (which embeds the numbers) changes.
        self._dispense(item, "5", n=1)
        svc.evaluate_item(drug, now=self.now)
        alert.refresh_from_db()
        self.assertEqual(alert.status, StockAlert.Status.OPEN)
        self.assertIsNone(alert.acknowledged_by_id)


class UniqueConstraintTests(StockoutSafetyBaseCase):
    def setUp(self):
        super().setUp()
        _enable_flag(self.__class__.tenant)

    def test_reeval_updates_in_place_no_duplicate(self):
        drug = self._drug(lead_time_days=10)
        item = self._stock_item(drug=drug)
        self._receive(item, "180")
        self._dispense(item, "10", n=15)
        svc = self._svc()
        svc.evaluate_item(drug, now=self.now)
        svc.evaluate_item(drug, now=self.now)
        svc.evaluate_item(drug, now=self.now)
        # The NULL-stock_item stockout_risk row must not duplicate (nulls_distinct).
        self.assertEqual(
            StockAlert.objects.filter(drug=drug, kind=StockAlert.Kind.STOCKOUT_RISK).count(),
            1,
        )

    def test_null_stock_item_unique_enforced(self):
        # Two stockout_risk rows for the same product (both stock_item NULL) must
        # collide on the nulls_distinct=False unique constraint.
        from django.db import IntegrityError, transaction

        drug = self._drug(lead_time_days=10)
        StockAlert.objects.create(
            drug=drug,
            kind=StockAlert.Kind.STOCKOUT_RISK,
            severity=StockAlert.Severity.ADVISE,
            message="a",
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                StockAlert.objects.create(
                    drug=drug,
                    kind=StockAlert.Kind.STOCKOUT_RISK,
                    severity=StockAlert.Severity.ADVISE,
                    message="b",
                )
