"""
N2-T2 — aprazamento service (frequency → due-time grid).

A NursingPrescriptionItem's ``frequency_hours`` + ``start_at`` expands into the
grid of due execution times over a window. A "6/6h" order over 24h yields 4 due
times (08:00, 14:00, 20:00, 02:00). The function is a pure, idempotent expansion.
"""

from datetime import UTC, datetime, timedelta

from apps.emr.services.aprazamento import build_schedule, generate_due_times


class TestGenerateDueTimes:
    def test_six_hourly_over_24h_yields_four(self):
        start = datetime(2026, 7, 24, 8, 0, tzinfo=UTC)
        due = generate_due_times(start, interval_hours=6, window_hours=24)
        assert due == [
            start,
            start + timedelta(hours=6),
            start + timedelta(hours=12),
            start + timedelta(hours=18),
        ]
        assert len(due) == 4

    def test_window_end_is_exclusive(self):
        # 8/8h over 24h: 08,16,00 → the 24h boundary (next 08:00) is excluded.
        start = datetime(2026, 7, 24, 8, 0, tzinfo=UTC)
        due = generate_due_times(start, interval_hours=8, window_hours=24)
        assert len(due) == 3

    def test_twelve_hourly_over_48h_yields_four(self):
        start = datetime(2026, 7, 24, 6, 0, tzinfo=UTC)
        due = generate_due_times(start, interval_hours=12, window_hours=48)
        assert len(due) == 4

    def test_idempotent_same_inputs_same_output(self):
        start = datetime(2026, 7, 24, 8, 0, tzinfo=UTC)
        a = generate_due_times(start, interval_hours=6, window_hours=24)
        b = generate_due_times(start, interval_hours=6, window_hours=24)
        assert a == b

    def test_invalid_interval_raises(self):
        start = datetime(2026, 7, 24, 8, 0, tzinfo=UTC)
        for bad in (0, -1):
            try:
                generate_due_times(start, interval_hours=bad, window_hours=24)
                raise AssertionError("expected ValueError")
            except ValueError:
                pass


class TestBuildScheduleFromItem:
    def test_build_schedule_reads_item_frequency_and_start(self):
        start = datetime(2026, 7, 24, 8, 0, tzinfo=UTC)

        class _Item:
            frequency_hours = 6
            start_at = start

        due = build_schedule(_Item(), window_hours=24)
        assert len(due) == 4
        assert due[0] == start

    def test_build_schedule_window_start_override(self):
        anchor = datetime(2026, 7, 24, 8, 0, tzinfo=UTC)
        override = datetime(2026, 7, 24, 20, 0, tzinfo=UTC)

        class _Item:
            frequency_hours = 6
            start_at = anchor

        due = build_schedule(_Item(), window_start=override, window_hours=24)
        assert due[0] == override
        assert len(due) == 4
