"""Pure-engine tests for the no-show risk scorer (no-show wedge N1).

PURE ENGINE. No DB. Validates the locked multiplicative-odds model: the Beta(2,8)
smoothed base rate, each odds modifier, the band cutoffs, score bounds, the
min-sample inert rule, and the no-confirm-only-after-reminder guard.
"""

from decimal import Decimal

import pytest

from apps.emr.services.no_show_checker import (
    BAND_HIGH,
    BAND_LOW,
    BAND_MEDIUM,
    DEFAULT_MIN_SAMPLE,
    ENGINE_VERSION,
    score_no_show,
)


def _score(**kw):
    return score_no_show(**{"no_shows": 0, "terminal": 10, **kw})


class TestInert:
    @pytest.mark.parametrize("terminal", [0, 1, 4])
    def test_below_min_sample_is_inert(self, terminal):
        assert score_no_show(no_shows=0, terminal=terminal) is None

    def test_at_min_sample_scores(self):
        v = score_no_show(no_shows=0, terminal=DEFAULT_MIN_SAMPLE)
        assert v is not None
        assert v.engine_version == ENGINE_VERSION


class TestBaseRate:
    def test_zero_no_shows_uses_prior(self):
        # 0/10 → base = (0+2)/(10+10) = 0.10 → odds 0.111 → score 0.10 → low.
        v = _score(no_shows=0, terminal=10)
        assert v.band == BAND_LOW
        assert v.score == Decimal("0.1000")
        assert v.suggested_action == "none"

    def test_high_historical_rate(self):
        # 8/10 → base = (8+2)/(10+10) = 0.50 → odds 1.0 → score 0.50 → high.
        v = _score(no_shows=8, terminal=10)
        assert v.band == BAND_HIGH
        assert v.score == Decimal("0.5000")
        assert v.suggested_action == "confirm_active"

    def test_no_shows_clamped_to_terminal(self):
        # Dirty data: no_shows > terminal must not exceed terminal.
        v = _score(no_shows=20, terminal=10)
        assert Decimal("0") < v.score < Decimal("1")

    def test_score_bounded_unit_interval(self):
        v = score_no_show(
            no_shows=10,
            terminal=10,
            consecutive_no_shows=5,
            whatsapp_reminder_sent=True,
            whatsapp_confirmed=False,
            lead_time_days=60,
            source="web",
            appointment_type="return",
        )
        assert Decimal("0") < v.score < Decimal("1")
        assert v.band == BAND_HIGH


class TestModifiers:
    def test_no_confirm_only_fires_after_reminder(self):
        base = _score(no_shows=2, terminal=10)
        # Reminder NOT sent → no modifier even if unconfirmed.
        not_sent = _score(
            no_shows=2, terminal=10, whatsapp_reminder_sent=False, whatsapp_confirmed=False
        )
        assert not_sent.score == base.score
        # Reminder sent + unconfirmed → risk rises.
        sent = _score(
            no_shows=2, terminal=10, whatsapp_reminder_sent=True, whatsapp_confirmed=False
        )
        assert sent.score > base.score
        # Reminder sent + confirmed → no bump.
        confirmed = _score(
            no_shows=2, terminal=10, whatsapp_reminder_sent=True, whatsapp_confirmed=True
        )
        assert confirmed.score == base.score

    def test_long_lead_time_raises(self):
        base = _score(no_shows=2, terminal=10, lead_time_days=5)
        far = _score(no_shows=2, terminal=10, lead_time_days=30)
        assert far.score > base.score

    def test_consecutive_no_shows_raises(self):
        base = _score(no_shows=2, terminal=10, consecutive_no_shows=1)
        run = _score(no_shows=2, terminal=10, consecutive_no_shows=2)
        assert run.score > base.score

    def test_self_serve_channel_raises(self):
        base = _score(no_shows=2, terminal=10, source="receptionist")
        web = _score(no_shows=2, terminal=10, source="web")
        assert web.score > base.score

    def test_return_type_raises(self):
        base = _score(no_shows=2, terminal=10, appointment_type="consultation")
        ret = _score(no_shows=2, terminal=10, appointment_type="return")
        assert ret.score > base.score

    def test_breakdown_records_each_fired_modifier(self):
        v = _score(
            no_shows=2,
            terminal=10,
            whatsapp_reminder_sent=True,
            whatsapp_confirmed=False,
            lead_time_days=40,
        )
        features = {row["feature"] for row in v.breakdown}
        assert "base_rate" in features
        assert "no_confirmation" in features
        assert "long_lead_time" in features
        # Un-fired modifiers are absent.
        assert "consecutive_no_shows" not in features


class TestBands:
    def test_modifiers_push_low_history_into_higher_band(self):
        # 1/10 base = 3/20 = 0.15 (low). Stack modifiers → crosses into medium/high.
        low = _score(no_shows=1, terminal=10)
        assert low.band == BAND_LOW
        stacked = _score(
            no_shows=1,
            terminal=10,
            whatsapp_reminder_sent=True,
            whatsapp_confirmed=False,
            consecutive_no_shows=2,
        )
        assert stacked.band in (BAND_MEDIUM, BAND_HIGH)
        assert stacked.score > low.score

    def test_lead_time_clamped_non_negative(self):
        # Negative lead (clock skew) must not crash nor fire the long-lead modifier.
        v = _score(no_shows=2, terminal=10, lead_time_days=-5)
        assert v is not None
        assert "long_lead_time" not in {row["feature"] for row in v.breakdown}
