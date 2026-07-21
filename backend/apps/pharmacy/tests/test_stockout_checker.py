"""Unit tests for the deterministic stockout engine (wedge PR S1).

The engine and the velocity helper are PURE (no DB, no clock — ``now`` is
injected), so these are plain ``unittest.TestCase`` tests with NO tenant DB
setup. They assert ONLY on the returned values.

ILLUSTRATIVE numbers — they exercise the math, they are not operational truth.
"""

import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from apps.pharmacy.services.stockout_checker import (
    KIND_NOT_APPLICABLE,
    KIND_STOCKOUT_RISK,
    KIND_SUFFICIENT,
    SEVERITY_ADVISE,
    StockoutChecker,
    compute_daily_velocity,
)

NOW = datetime(2026, 6, 3, 12, 0, 0, tzinfo=UTC)


def _ev(days_ago: float, qty: str) -> tuple[datetime, Decimal]:
    return (NOW - timedelta(days=days_ago), Decimal(qty))


class TestComputeDailyVelocity(unittest.TestCase):
    def test_five_events_in_window_simple_moving_average(self):
        # 5 events totalling 60 units over a 30-day window → 60/30 = 2.0/day.
        events = [
            _ev(1, "10"),
            _ev(5, "10"),
            _ev(10, "10"),
            _ev(20, "20"),
            _ev(29, "10"),
        ]
        v = compute_daily_velocity(events, now=NOW, window_days=30)
        self.assertEqual(v, Decimal("2.0000"))

    def test_fewer_than_min_events_returns_none(self):
        # Only 2 events (< min_events default 3) → INERT.
        events = [_ev(1, "10"), _ev(2, "10")]
        self.assertIsNone(compute_daily_velocity(events, now=NOW, window_days=30))

    def test_all_events_outside_window_returns_none(self):
        # 4 events but all older than the 30-day window → none in window → INERT.
        events = [_ev(31, "10"), _ev(40, "10"), _ev(60, "10"), _ev(90, "10")]
        self.assertIsNone(compute_daily_velocity(events, now=NOW, window_days=30))

    def test_zero_total_returns_none(self):
        # Enough events but all zero quantity → total 0 → INERT (no div-by-zero).
        events = [_ev(1, "0"), _ev(2, "0"), _ev(3, "0")]
        self.assertIsNone(compute_daily_velocity(events, now=NOW, window_days=30))

    def test_only_in_window_events_counted(self):
        # 3 in-window (total 30) + 2 out-of-window are ignored → 30/30 = 1.0/day.
        events = [
            _ev(1, "10"),
            _ev(10, "10"),
            _ev(29, "10"),
            _ev(40, "999"),
            _ev(50, "999"),
        ]
        v = compute_daily_velocity(events, now=NOW, window_days=30)
        self.assertEqual(v, Decimal("1.0000"))

    def test_quantities_treated_as_magnitude(self):
        # dispense quantities may be stored signed; magnitude is used.
        events = [_ev(1, "-10"), _ev(2, "-10"), _ev(3, "-10")]
        v = compute_daily_velocity(events, now=NOW, window_days=30)
        self.assertEqual(v, Decimal("1.0000"))


class TestStockoutCheckerInert(unittest.TestCase):
    def test_velocity_none_is_not_applicable(self):
        v = StockoutChecker.check(
            current_balance=Decimal("100"),
            daily_velocity=None,
            lead_time_days=7,
            safety_stock=None,
            reorder_point=None,
            now=NOW,
        )
        self.assertEqual(v.kind, KIND_NOT_APPLICABLE)
        self.assertIsNone(v.severity)
        self.assertIsNone(v.days_to_stockout)
        self.assertIsNone(v.predicted_date)

    def test_lead_time_none_is_not_applicable(self):
        v = StockoutChecker.check(
            current_balance=Decimal("100"),
            daily_velocity=Decimal("5"),
            lead_time_days=None,
            safety_stock=None,
            reorder_point=None,
            now=NOW,
        )
        self.assertEqual(v.kind, KIND_NOT_APPLICABLE)
        self.assertIsNone(v.severity)


class TestStockoutCheckerSufficient(unittest.TestCase):
    def test_high_balance_low_velocity_is_sufficient(self):
        # 1000 units / 1 per day = 1000 days runway, lead time 7 → plenty.
        v = StockoutChecker.check(
            current_balance=Decimal("1000"),
            daily_velocity=Decimal("1"),
            lead_time_days=7,
            safety_stock=None,
            reorder_point=None,
            now=NOW,
        )
        self.assertEqual(v.kind, KIND_SUFFICIENT)
        self.assertIsNone(v.severity)
        self.assertEqual(v.days_to_stockout, Decimal("1000.0"))
        self.assertIsNotNone(v.predicted_date)


class TestStockoutCheckerRisk(unittest.TestCase):
    def test_low_balance_high_velocity_is_risk_advise(self):
        # 20 units / 4 per day = 5 days runway <= lead time 7 → RISK.
        v = StockoutChecker.check(
            current_balance=Decimal("20"),
            daily_velocity=Decimal("4"),
            lead_time_days=7,
            safety_stock=None,
            reorder_point=None,
            now=NOW,
        )
        self.assertEqual(v.kind, KIND_STOCKOUT_RISK)
        self.assertEqual(v.severity, SEVERITY_ADVISE)
        self.assertEqual(v.days_to_stockout, Decimal("5.0"))
        # now.date() + 5 days
        self.assertEqual(v.predicted_date.isoformat(), "2026-06-08")
        self.assertIn("Risco de ruptura", v.reason)

    def test_reorder_point_breach_is_risk(self):
        # Runway 100 days (> lead time 7) but balance 50 <= reorder_point 60 → RISK.
        v = StockoutChecker.check(
            current_balance=Decimal("50"),
            daily_velocity=Decimal("0.5"),
            lead_time_days=7,
            safety_stock=None,
            reorder_point=Decimal("60"),
            now=NOW,
        )
        self.assertEqual(v.kind, KIND_STOCKOUT_RISK)
        self.assertEqual(v.severity, SEVERITY_ADVISE)
        self.assertIn("ponto de reposição", v.reason)

    def test_safety_stock_breach_is_risk(self):
        # Runway 40 days (> lead 7), reorder unset, but projected balance at lead
        # = 200 - 5*7 = 165... choose so it dips below safety. balance 50, vel 5,
        # lead 7 → runway 10 (> 7 so no runway breach), projected = 50-35 = 15 <
        # safety 30 → RISK.
        v = StockoutChecker.check(
            current_balance=Decimal("50"),
            daily_velocity=Decimal("5"),
            lead_time_days=7,
            safety_stock=Decimal("30"),
            reorder_point=None,
            now=NOW,
        )
        self.assertEqual(v.kind, KIND_STOCKOUT_RISK)
        self.assertEqual(v.severity, SEVERITY_ADVISE)
        self.assertIn("estoque de segurança", v.reason)

    def test_never_block_no_block_severity_anywhere(self):
        # Exhaustive: severity is only ever None or "advise" — never "block".
        scenarios = [
            {"current_balance": Decimal("20"), "daily_velocity": Decimal("4"), "lead_time_days": 7},
            {
                "current_balance": Decimal("1000"),
                "daily_velocity": Decimal("1"),
                "lead_time_days": 7,
            },
            {"current_balance": Decimal("100"), "daily_velocity": None, "lead_time_days": 7},
        ]
        for kw in scenarios:
            v = StockoutChecker.check(safety_stock=None, reorder_point=None, now=NOW, **kw)
            self.assertIn(v.severity, (None, SEVERITY_ADVISE))
            self.assertNotEqual(v.severity, "block")

    def test_no_division_by_zero_on_inert_path(self):
        # velocity None never reaches a division; assert it returns cleanly.
        v = StockoutChecker.check(
            current_balance=Decimal("0"),
            daily_velocity=None,
            lead_time_days=7,
            safety_stock=Decimal("10"),
            reorder_point=Decimal("10"),
            now=NOW,
        )
        self.assertEqual(v.kind, KIND_NOT_APPLICABLE)


class TestS2904SupplyConfigConfirmation(unittest.TestCase):
    """S29-04 confirmation tests: absent/present supply config safe-degradation.

    These assert the behaviour already documented in the module docstring and
    exercised indirectly by existing tests, but are named explicitly so the
    S29-04 audit trail is unambiguous.

    Already-covered paths this class intentionally duplicates for clarity:
      - velocity=None → not_applicable  (TestStockoutCheckerInert)
      - lead_time_days=None → not_applicable  (TestStockoutCheckerInert)
    New assertions not present elsewhere:
      - combined absent config (lead_time=None, safety_stock=None,
        reorder_point=None, with a real velocity) → not_applicable, no block,
        no fabricated number in days_to_stockout / predicted_date.
      - lead_time_days present (non-None) → verdict reflects configured value.
    """

    def test_absent_lead_time_degrades_to_advise_only_never_blocks(self):
        """With lead_time_days=None (all other config also absent), the engine
        must return not_applicable — no block severity, no fabricated lead-time
        number, no days_to_stockout, no predicted_date."""
        v = StockoutChecker.check(
            current_balance=Decimal("50"),
            daily_velocity=Decimal("5"),  # real velocity — inert guard is lead_time
            lead_time_days=None,
            safety_stock=None,
            reorder_point=None,
            now=NOW,
        )
        self.assertEqual(v.kind, KIND_NOT_APPLICABLE)
        self.assertIsNone(v.severity)  # no advise, no block
        self.assertNotEqual(v.severity, "block")  # explicit never-block guard
        self.assertIsNone(v.days_to_stockout)  # no fabricated number
        self.assertIsNone(v.predicted_date)  # no fabricated date

    def test_lead_time_config_present_is_used(self):
        """With lead_time_days=7 and a balance that runs out in 5 days, the
        engine must detect a breach (5 <= 7) and return stockout_risk with
        severity=advise — confirming the configured value is consumed, not
        hard-coded or ignored."""
        configured_lead = 7
        v = StockoutChecker.check(
            current_balance=Decimal("20"),
            daily_velocity=Decimal("4"),  # 20/4 = 5 days runway < lead 7 → risk
            lead_time_days=configured_lead,
            safety_stock=None,
            reorder_point=None,
            now=NOW,
        )
        self.assertEqual(v.kind, KIND_STOCKOUT_RISK)
        self.assertEqual(v.severity, SEVERITY_ADVISE)  # advise, never block
        self.assertNotEqual(v.severity, "block")
        # The configured lead time appears in the reason — it was consumed.
        self.assertIn(str(configured_lead), v.reason)
        self.assertIsNotNone(v.days_to_stockout)
        self.assertIsNotNone(v.predicted_date)


if __name__ == "__main__":
    unittest.main()
