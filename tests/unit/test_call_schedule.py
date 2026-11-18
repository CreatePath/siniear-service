from datetime import UTC, datetime, time

from app.modules.calls.service import next_occurrence


def test_seoul_week_rollover_and_exclusive_boundary():
    at = datetime(2026, 11, 16, 1, tzinfo=UTC)  # Monday 10:00 Seoul
    assert next_occurrence(["MON"], time(10), at) == datetime(2026, 11, 23, 1, tzinfo=UTC)
    assert next_occurrence(["MON", "TUE"], time(10), at) == datetime(2026, 11, 17, 1, tzinfo=UTC)
