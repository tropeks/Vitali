"""Tests for the learned demand-forecast engine (issue #131).

These are pure-Python unit tests — no DB, no Django — exercising the
Holt-Winters model, MAPE, hold-out evaluation, and the model-selection seam.
"""

from __future__ import annotations

import math
import unittest

from apps.pharmacy_ai.services import learned


def _weekly_series(weeks: int, pattern: list[float], *, trend: float = 0.0) -> list[float]:
    """Repeat a 7-day ``pattern`` for ``weeks`` weeks, with an optional daily trend."""
    out: list[float] = []
    for w in range(weeks):
        for i, base in enumerate(pattern):
            day_index = w * 7 + i
            out.append(max(0.0, base + trend * day_index))
    return out


# A pronounced, realistic weekly pharmacy shape: busy weekdays, quiet weekend.
_PHARMACY_WEEK = [20.0, 22.0, 21.0, 23.0, 25.0, 8.0, 5.0]


class MapeTest(unittest.TestCase):
    def test_perfect_prediction_is_zero(self):
        self.assertEqual(learned.mape([10, 20, 30], [10, 20, 30]), 0.0)

    def test_known_value(self):
        # |(10-8)/10| + |(20-25)/20| = 0.2 + 0.25 = 0.45 → /2 → 0.225 → 22.5%
        self.assertAlmostEqual(learned.mape([10, 20], [8, 25]), 22.5, places=6)

    def test_skips_zero_actuals(self):
        # The zero-actual point is ignored; only the 10→8 point counts (20%).
        self.assertAlmostEqual(learned.mape([0, 10], [5, 8]), 20.0, places=6)

    def test_all_zero_actuals_returns_none(self):
        self.assertIsNone(learned.mape([0, 0, 0], [1, 2, 3]))


class MovingAverageBaselineTest(unittest.TestCase):
    def test_flat_mean_forecast(self):
        self.assertEqual(learned.moving_average_forecast([2, 4, 6], 3), [4.0, 4.0, 4.0])

    def test_empty_history(self):
        self.assertEqual(learned.moving_average_forecast([], 2), [0.0, 0.0])

    def test_zero_horizon(self):
        self.assertEqual(learned.moving_average_forecast([1, 2, 3], 0), [])


class HoltWintersTest(unittest.TestCase):
    def test_returns_none_when_too_short(self):
        # Only one season of data → cannot estimate the weekly season.
        self.assertIsNone(learned.holt_winters_forecast(_PHARMACY_WEEK, horizon=7))

    def test_recovers_weekly_pattern(self):
        history = _weekly_series(8, _PHARMACY_WEEK)
        preds = learned.holt_winters_forecast(history, horizon=7)
        assert preds is not None
        self.assertEqual(len(preds), 7)
        # The model should reproduce the weekly shape closely on a clean signal.
        for predicted, expected in zip(preds, _PHARMACY_WEEK, strict=True):
            self.assertAlmostEqual(predicted, expected, delta=2.0)

    def test_forecasts_are_non_negative(self):
        history = _weekly_series(6, [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], trend=-0.05)
        preds = learned.holt_winters_forecast(history, horizon=7)
        assert preds is not None
        self.assertTrue(all(p >= 0.0 for p in preds))

    def test_trims_leading_zeros(self):
        # 5 weeks of leading zeros (drug introduced mid-window) + 6 real weeks.
        history = [0.0] * 35 + _weekly_series(6, _PHARMACY_WEEK)
        preds = learned.holt_winters_forecast(history, horizon=7)
        assert preds is not None
        for predicted, expected in zip(preds, _PHARMACY_WEEK, strict=True):
            self.assertAlmostEqual(predicted, expected, delta=3.0)


class EvaluateAndSelectTest(unittest.TestCase):
    def test_learned_beats_baseline_on_seasonal_history(self):
        """Acceptance criterion (#131): MAPE(learned) < MAPE(baseline) on hold-out."""
        history = _weekly_series(10, _PHARMACY_WEEK)
        report = learned.evaluate_models(history, holdout_days=7)
        assert report is not None
        self.assertIsNotNone(report.mape_learned)
        self.assertIsNotNone(report.mape_baseline)
        self.assertLess(report.mape_learned, report.mape_baseline)
        self.assertTrue(report.improved)

    def test_forecast_demand_adopts_learned_when_seasonal(self):
        history = _weekly_series(10, _PHARMACY_WEEK)
        result = learned.forecast_demand(history, horizon=14, holdout_days=7)
        self.assertEqual(result.model, learned.MODEL_HOLT_WINTERS)
        self.assertEqual(result.season_length, learned.DEFAULT_SEASON_LENGTH)
        self.assertEqual(len(result.predictions), 14)
        self.assertIsNotNone(result.accuracy)

    def test_forecast_demand_falls_back_when_flat(self):
        # A flat series has no seasonal signal for the learned model to exploit,
        # so the baseline is not beaten and we degrade gracefully.
        history = [10.0] * 70
        result = learned.forecast_demand(history, horizon=14, holdout_days=7)
        self.assertEqual(result.model, learned.MODEL_BASELINE)
        self.assertIsNone(result.season_length)
        self.assertEqual(result.predictions, [10.0] * 14)

    def test_forecast_demand_falls_back_when_too_short(self):
        result = learned.forecast_demand([20.0, 22.0, 21.0], horizon=7, holdout_days=7)
        self.assertEqual(result.model, learned.MODEL_BASELINE)
        self.assertIsNone(result.accuracy)

    def test_evaluate_returns_none_when_too_short(self):
        self.assertIsNone(learned.evaluate_models([1.0, 2.0, 3.0], holdout_days=7))

    def test_learned_improves_with_trend_and_season(self):
        # Weekly season plus a mild upward trend — still a clear learned win.
        history = _weekly_series(12, _PHARMACY_WEEK, trend=0.1)
        report = learned.evaluate_models(history, holdout_days=14)
        assert report is not None
        self.assertLess(report.mape_learned, report.mape_baseline)
        self.assertTrue(math.isfinite(report.mape_learned))


if __name__ == "__main__":
    unittest.main()
