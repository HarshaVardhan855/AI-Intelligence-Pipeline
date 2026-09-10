from datetime import datetime, timezone

from ai_pipeline.utils.dates import is_fresh, parse_date


def test_relative_date_is_utc_and_fresh():
    now = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)
    parsed = parse_date("2 hours ago", now)
    assert parsed == datetime(2026, 9, 10, 10, tzinfo=timezone.utc)
    assert is_fresh("2 hours ago", now)


def test_stale_and_undated_values_are_rejected():
    now = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)
    assert not is_fresh(datetime(2026, 9, 9, 10, tzinfo=timezone.utc), now)
    assert not is_fresh(None, now)


def test_unix_timestamp_is_supported():
    now = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)
    assert is_fresh(1789034400, now)
