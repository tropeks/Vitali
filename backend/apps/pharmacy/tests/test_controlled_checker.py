"""Pure-engine tests for the controlled-diversion checker (wedge C1).

PURE ENGINE. No DB. Validates the 3 deterministic signals (refill-too-soon,
multiple-prescribers, quantity-escalation), the inert/no-data paths, the
same-script-split guard, the per-class vs per-drug grouping, and the prior-only
guard.
"""

import datetime
from decimal import Decimal

from apps.pharmacy.services.controlled_checker import (
    SIGNAL_MULTIPLE_PRESCRIBERS,
    SIGNAL_QUANTITY_ESCALATION,
    SIGNAL_REFILL_TOO_SOON,
    DispensationRecord,
    check,
)

_T0 = datetime.datetime(2026, 6, 1, 12, 0, tzinfo=datetime.UTC)


def _rec(*, did, drug="d1", cls="B1", rx="rx1", prescriber="p1", qty="10", days_ago=0):
    return DispensationRecord(
        dispensation_id=did,
        drug_id=drug,
        controlled_class=cls,
        prescription_id=rx,
        prescriber_id=prescriber,
        quantity=Decimal(qty),
        dispensed_at=_T0 - datetime.timedelta(days=days_ago),
    )


def _kinds(signals):
    return {s.kind for s in signals}


class TestRefillTooSoon:
    def test_early_refill_different_prescription_flags(self):
        current = _rec(did="c", rx="rx2", days_ago=0)
        prior = [_rec(did="a", rx="rx1", days_ago=5)]  # 5 days ago, diff Rx
        sig = check(current=current, history=prior, min_refill_interval_days=30)
        assert SIGNAL_REFILL_TOO_SOON in _kinds(sig)

    def test_refill_after_interval_is_ok(self):
        current = _rec(did="c", rx="rx2", days_ago=0)
        prior = [_rec(did="a", rx="rx1", days_ago=40)]
        sig = check(current=current, history=prior, min_refill_interval_days=30)
        assert SIGNAL_REFILL_TOO_SOON not in _kinds(sig)

    def test_same_prescription_split_is_not_a_refill(self):
        current = _rec(did="c", rx="rx1", days_ago=0)
        prior = [_rec(did="a", rx="rx1", days_ago=1)]  # same script, partial fill
        sig = check(current=current, history=prior, min_refill_interval_days=30)
        assert SIGNAL_REFILL_TOO_SOON not in _kinds(sig)

    def test_inert_when_interval_unset(self):
        current = _rec(did="c", rx="rx2", days_ago=0)
        prior = [_rec(did="a", rx="rx1", days_ago=1)]
        sig = check(current=current, history=prior, min_refill_interval_days=None)
        assert SIGNAL_REFILL_TOO_SOON not in _kinds(sig)


class TestMultiplePrescribers:
    def test_three_distinct_prescribers_same_class_flags(self):
        current = _rec(did="c", prescriber="p3", days_ago=0)
        prior = [
            _rec(did="a", prescriber="p1", days_ago=10),
            _rec(did="b", prescriber="p2", days_ago=20),
        ]
        sig = check(current=current, history=prior, min_refill_interval_days=None)
        assert SIGNAL_MULTIPLE_PRESCRIBERS in _kinds(sig)

    def test_two_prescribers_is_ok(self):
        current = _rec(did="c", prescriber="p2", days_ago=0)
        prior = [_rec(did="a", prescriber="p1", days_ago=10)]
        sig = check(current=current, history=prior, min_refill_interval_days=None)
        assert SIGNAL_MULTIPLE_PRESCRIBERS not in _kinds(sig)

    def test_outside_window_not_counted(self):
        current = _rec(did="c", prescriber="p3", days_ago=0)
        prior = [
            _rec(did="a", prescriber="p1", days_ago=10),
            _rec(did="b", prescriber="p2", days_ago=200),  # outside 90d
        ]
        sig = check(current=current, history=prior, min_refill_interval_days=None)
        assert SIGNAL_MULTIPLE_PRESCRIBERS not in _kinds(sig)

    def test_different_class_not_counted(self):
        # Prescribers on a DIFFERENT controlled class don't count toward this class.
        current = _rec(did="c", cls="B1", prescriber="p3", days_ago=0)
        prior = [
            _rec(did="a", cls="A1", prescriber="p1", days_ago=10),
            _rec(did="b", cls="A1", prescriber="p2", days_ago=20),
        ]
        sig = check(current=current, history=prior, min_refill_interval_days=None)
        assert SIGNAL_MULTIPLE_PRESCRIBERS not in _kinds(sig)


class TestQuantityEscalation:
    def test_three_strictly_increasing_flags(self):
        current = _rec(did="c", qty="30", days_ago=0)
        prior = [
            _rec(did="a", qty="10", days_ago=20),
            _rec(did="b", qty="20", days_ago=10),
        ]
        sig = check(current=current, history=prior, min_refill_interval_days=None)
        assert SIGNAL_QUANTITY_ESCALATION in _kinds(sig)

    def test_not_increasing_is_ok(self):
        current = _rec(did="c", qty="20", days_ago=0)
        prior = [
            _rec(did="a", qty="10", days_ago=20),
            _rec(did="b", qty="20", days_ago=10),  # equal, not strictly increasing
        ]
        sig = check(current=current, history=prior, min_refill_interval_days=None)
        assert SIGNAL_QUANTITY_ESCALATION not in _kinds(sig)

    def test_too_few_fills_is_ok(self):
        current = _rec(did="c", qty="30", days_ago=0)
        prior = [_rec(did="a", qty="10", days_ago=20)]  # only 2 fills total
        sig = check(current=current, history=prior, min_refill_interval_days=None)
        assert SIGNAL_QUANTITY_ESCALATION not in _kinds(sig)

    def test_other_drug_fills_not_mixed(self):
        current = _rec(did="c", drug="d1", qty="30", days_ago=0)
        prior = [
            _rec(did="a", drug="d1", qty="10", days_ago=20),
            _rec(did="b", drug="d2", qty="20", days_ago=10),  # different drug
        ]
        sig = check(current=current, history=prior, min_refill_interval_days=None)
        # Only 2 fills of d1 → no escalation.
        assert SIGNAL_QUANTITY_ESCALATION not in _kinds(sig)


class TestS2904ControlledConfigConfirmation:
    """S29-04 confirmation tests: absent/present min_refill_interval_days
    safe-degradation for the controlled-diversion engine.

    Already-covered paths:
      - min_refill_interval_days=None → refill_too_soon absent
        (TestRefillTooSoon.test_inert_when_interval_unset)
      - min_refill_interval_days=30 with early refill → signal fires
        (TestRefillTooSoon.test_early_refill_different_prescription_flags)
    New assertions:
      - absent interval with a very recent same-drug/diff-Rx refill → the
        signal is absent AND no interval number is fabricated in signal detail.
      - present interval (30d) with a refill 5 days later → signal fires and
        the configured value appears in the detail (confirming it's consumed).
    """

    def test_absent_min_refill_interval_degrades_to_advise_only(self):
        """min_refill_interval_days=None → refill_too_soon never fires, even
        when the refill gap is only 1 day. No invented interval in any signal
        detail; the signals list contains no refill_too_soon entry."""
        current = _rec(did="c", rx="rx2", days_ago=0)
        prior = [_rec(did="a", rx="rx1", days_ago=1)]  # 1 day gap — very early
        signals = check(current=current, history=prior, min_refill_interval_days=None)
        kinds = _kinds(signals)
        assert SIGNAL_REFILL_TOO_SOON not in kinds
        # Confirm no signal carries a fabricated min_refill_interval_days value.
        for s in signals:
            assert "min_refill_interval_days" not in s.detail

    def test_min_refill_interval_present_is_used(self):
        """min_refill_interval_days=30 with a 5-day gap → refill_too_soon fires
        and the configured interval (30) appears in the signal detail, confirming
        the value is consumed rather than hard-coded or ignored."""
        configured_interval = 30
        current = _rec(did="c", rx="rx2", days_ago=0)
        prior = [_rec(did="a", rx="rx1", days_ago=5)]  # 5-day gap < 30 → too soon
        signals = check(
            current=current, history=prior, min_refill_interval_days=configured_interval
        )
        assert SIGNAL_REFILL_TOO_SOON in _kinds(signals)
        refill_signal = next(s for s in signals if s.kind == SIGNAL_REFILL_TOO_SOON)
        # The configured interval is embedded in detail — it was used, not invented.
        assert refill_signal.detail["min_refill_interval_days"] == configured_interval
        assert refill_signal.detail["gap_days"] == 5


class TestCombinedAndGuards:
    def test_no_history_no_signals(self):
        assert check(current=_rec(did="c"), history=[], min_refill_interval_days=30) == []

    def test_future_history_ignored(self):
        # A record dated AFTER current must not be treated as prior.
        current = _rec(did="c", rx="rx2", days_ago=10)
        future = [_rec(did="a", rx="rx1", days_ago=0)]  # 10 days AFTER current
        sig = check(current=current, history=future, min_refill_interval_days=30)
        assert sig == []

    def test_multiple_signals_coexist(self):
        # Early refill + escalation on the same dispensation.
        current = _rec(did="c", rx="rx2", qty="30", days_ago=0)
        prior = [
            _rec(did="a", rx="rx1", qty="10", days_ago=20),
            _rec(did="b", rx="rx1", qty="20", days_ago=3),
        ]
        sig = check(current=current, history=prior, min_refill_interval_days=30)
        assert SIGNAL_REFILL_TOO_SOON in _kinds(sig)
        assert SIGNAL_QUANTITY_ESCALATION in _kinds(sig)
