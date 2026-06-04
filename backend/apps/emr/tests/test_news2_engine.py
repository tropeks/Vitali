"""NEWS2 pure-engine tests (deterioration wedge, D1).

PURE ENGINE. No DB, no clock, no orchestration. Validates the RCP-2017 scoring
table boundary-by-boundary, the two SpO2 scales, the aggregate-band logic
(including the single-parameter-3 "red score"), and the strict
missing-parameter inert rule.

Reference: Royal College of Physicians, NEWS2, 2017.
"""

from decimal import Decimal

import pytest

from apps.emr.services.news2 import (
    BAND_HIGH,
    BAND_LOW,
    BAND_LOW_MEDIUM,
    BAND_MEDIUM,
    ENGINE_VERSION,
    compute_news2,
)

# A fully-normal vitals set → score 0. Used as the base for single-axis sweeps.
NORMAL = {
    "respiratory_rate": 16,  # 12–20 → 0
    "spo2": 98,  # >=96 → 0 (scale 1)
    "on_supplemental_oxygen": False,  # air → 0
    "systolic_bp": 120,  # 111–219 → 0
    "heart_rate": 70,  # 51–90 → 0
    "temperature": Decimal("36.8"),  # 36.1–38.0 → 0
    "consciousness": "A",  # Alert → 0
}


def _score(**overrides):
    return compute_news2(**{**NORMAL, **overrides})


class TestNormalAndCompleteness:
    def test_all_normal_is_zero_low(self):
        r = _score()
        assert r is not None
        assert r.score == 0
        assert r.band == BAND_LOW
        assert r.any_param_three is False
        assert r.spo2_scale == 1
        assert r.engine_version == ENGINE_VERSION
        assert sum(r.breakdown.values()) == 0

    @pytest.mark.parametrize(
        "missing",
        [
            "respiratory_rate",
            "spo2",
            "on_supplemental_oxygen",
            "systolic_bp",
            "heart_rate",
            "temperature",
            "consciousness",
        ],
    )
    def test_any_missing_param_is_inert_none(self, missing):
        # Strict: a single missing parameter → inert (no imputation).
        assert _score(**{missing: None}) is None

    def test_on_air_false_is_a_valid_reading_not_missing(self):
        # on_supplemental_oxygen=False ("on air") must NOT be treated as missing.
        r = _score(on_supplemental_oxygen=False)
        assert r is not None
        assert r.breakdown["supplemental_oxygen"] == 0


class TestRespiratoryRate:
    @pytest.mark.parametrize(
        "rr,pts",
        [
            (5, 3),
            (8, 3),
            (9, 1),
            (11, 1),
            (12, 0),
            (16, 0),
            (20, 0),
            (21, 2),
            (24, 2),
            (25, 3),
            (40, 3),
        ],
    )
    def test_boundaries(self, rr, pts):
        assert _score(respiratory_rate=rr).breakdown["respiratory_rate"] == pts


class TestSpO2Scale1:
    @pytest.mark.parametrize(
        "spo2,pts",
        [(85, 3), (91, 3), (92, 2), (93, 2), (94, 1), (95, 1), (96, 0), (100, 0)],
    )
    def test_boundaries(self, spo2, pts):
        r = _score(spo2=spo2)
        assert r.spo2_scale == 1
        assert r.breakdown["spo2"] == pts


class TestSpO2Scale2:
    @pytest.mark.parametrize(
        "spo2,on_o2,pts",
        [
            (80, False, 3),
            (83, False, 3),
            (84, False, 2),
            (85, False, 2),
            (86, False, 1),
            (87, False, 1),
            (88, False, 0),
            (92, False, 0),
            # On air, anything >=93 is target-met → 0.
            (93, False, 0),
            (96, False, 0),
            (99, False, 0),
            # On oxygen, supranormal saturation is itself a warning.
            (93, True, 1),
            (94, True, 1),
            (95, True, 2),
            (96, True, 2),
            (97, True, 3),
            (100, True, 3),
            # 88–92 stays 0 regardless of O2.
            (90, True, 0),
        ],
    )
    def test_boundaries(self, spo2, on_o2, pts):
        r = _score(spo2=spo2, on_supplemental_oxygen=on_o2, use_spo2_scale_2=True)
        assert r.spo2_scale == 2
        assert r.breakdown["spo2"] == pts


class TestSupplementalOxygen:
    def test_air_is_zero(self):
        assert _score(on_supplemental_oxygen=False).breakdown["supplemental_oxygen"] == 0

    def test_oxygen_is_two(self):
        # The supplemental-O2 axis scores 2 independently of the SpO2 reading.
        r = _score(on_supplemental_oxygen=True)
        assert r.breakdown["supplemental_oxygen"] == 2
        assert r.score == 2


class TestSystolicBP:
    @pytest.mark.parametrize(
        "sbp,pts",
        [
            (80, 3),
            (90, 3),
            (91, 2),
            (100, 2),
            (101, 1),
            (110, 1),
            (111, 0),
            (180, 0),
            (219, 0),
            (220, 3),
            (250, 3),
        ],
    )
    def test_boundaries(self, sbp, pts):
        assert _score(systolic_bp=sbp).breakdown["systolic_bp"] == pts


class TestHeartRate:
    @pytest.mark.parametrize(
        "hr,pts",
        [
            (30, 3),
            (40, 3),
            (41, 1),
            (50, 1),
            (51, 0),
            (70, 0),
            (90, 0),
            (91, 1),
            (110, 1),
            (111, 2),
            (130, 2),
            (131, 3),
            (180, 3),
        ],
    )
    def test_boundaries(self, hr, pts):
        assert _score(heart_rate=hr).breakdown["heart_rate"] == pts


class TestTemperature:
    @pytest.mark.parametrize(
        "temp,pts",
        [
            ("34.0", 3),
            ("35.0", 3),
            ("35.1", 1),
            ("36.0", 1),
            ("36.1", 0),
            ("37.0", 0),
            ("38.0", 0),
            ("38.1", 1),
            ("39.0", 1),
            ("39.1", 2),
            ("41.0", 2),
        ],
    )
    def test_boundaries(self, temp, pts):
        assert _score(temperature=Decimal(temp)).breakdown["temperature"] == pts

    def test_accepts_float_and_int(self):
        assert _score(temperature=36.8).breakdown["temperature"] == 0
        assert _score(temperature=40).breakdown["temperature"] == 2


class TestConsciousness:
    def test_alert_is_zero(self):
        assert _score(consciousness="A").breakdown["consciousness"] == 0

    @pytest.mark.parametrize("acvpu", ["C", "V", "P", "U"])
    def test_non_alert_is_three(self, acvpu):
        assert _score(consciousness=acvpu).breakdown["consciousness"] == 3

    @pytest.mark.parametrize("bad", ["", " ", "a", "X", "alert", "Z"])
    def test_empty_or_invalid_consciousness_is_inert_not_phantom_three(self, bad):
        # An empty string / invalid letter must be treated as MISSING (→ None),
        # never scored as +3 — otherwise a fixture/import write would fabricate risk.
        assert _score(consciousness=bad) is None


class TestAggregateBands:
    def test_zero_is_low(self):
        assert _score().band == BAND_LOW

    def test_low_aggregate_no_red(self):
        # HR 91 (1) + SpO2 94 (1) = total 2, no single param == 3 → low.
        r = _score(heart_rate=91, spo2=94)
        assert r.score == 2
        assert r.any_param_three is False
        assert r.band == BAND_LOW

    def test_single_param_three_is_low_medium(self):
        # RR 26 alone scores 3 → total 3 but a "red score" → low-medium.
        r = _score(respiratory_rate=26)
        assert r.score == 3
        assert r.any_param_three is True
        assert r.band == BAND_LOW_MEDIUM

    def test_total_five_is_medium(self):
        # RR 22 (2) + HR 125 (2) + SpO2 94 (1) = 5 → medium (no single 3).
        r = _score(respiratory_rate=22, heart_rate=125, spo2=94)
        assert r.score == 5
        assert r.any_param_three is False
        assert r.band == BAND_MEDIUM

    def test_total_six_is_medium(self):
        r = _score(respiratory_rate=22, heart_rate=125, spo2=92)
        assert r.score == 6
        assert r.band == BAND_MEDIUM

    def test_medium_dominates_single_three(self):
        # total 5 from a single-3 (RR 26 = 3) + HR 91 (1) + SpO2 94 (1) → medium,
        # not low-medium; the aggregate threshold wins.
        r = _score(respiratory_rate=26, heart_rate=91, spo2=94)
        assert r.score == 5
        assert r.any_param_three is True
        assert r.band == BAND_MEDIUM

    def test_total_seven_is_high(self):
        # RR 26 (3) + HR 125 (2) + temp 39.5 (2) = 7 → high.
        r = _score(respiratory_rate=26, heart_rate=125, temperature=Decimal("39.5"))
        assert r.score == 7
        assert r.band == BAND_HIGH

    def test_septic_shock_picture_is_high(self):
        # A classic deterioration picture: tachypnoea, hypoxia on O2, hypotension,
        # tachycardia, fever, new confusion.
        r = compute_news2(
            respiratory_rate=28,  # 3
            spo2=90,  # scale 1 <=91 → 3
            on_supplemental_oxygen=True,  # 2
            systolic_bp=88,  # 3
            heart_rate=124,  # 2
            temperature=Decimal("39.4"),  # 2
            consciousness="V",  # 3
        )
        assert r.score == 18
        assert r.band == BAND_HIGH
