from __future__ import annotations

from datetime import datetime, timedelta, timezone

from supply_watchdog import (
    count_since,
    daily_counts,
    evaluate_supply,
    is_news_record,
    record_published_at,
)

NOW = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)


def record(hours_ago: float, category: str = "news", **extra) -> dict:
    stamp = (NOW - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")
    payload = {"published_at": stamp, "category": category, "slug": f"s-{hours_ago}-{category}"}
    payload.update(extra)
    return payload


def test_events_are_not_counted_as_journalism() -> None:
    assert is_news_record(record(1)) is True
    assert is_news_record(record(1, category="events")) is False


def test_first_published_at_wins_over_render_timestamp() -> None:
    item = record(2)
    item["first_published_at"] = "2026-08-20T09:00:00Z"
    assert record_published_at(item) == datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)


def test_quiet_days_appear_as_explicit_zeros() -> None:
    counts = daily_counts([record(1), record(2)], now=NOW, days=7)
    assert len(counts) == 7
    assert counts["2026-08-28"] == 2
    assert counts["2026-08-24"] == 0


def test_count_since_ignores_events_and_older_records() -> None:
    records = [record(1), record(5, category="events"), record(40)]
    assert count_since(records, now=NOW, hours=24) == 1


def test_famine_fails_even_when_the_edition_rendered_correctly() -> None:
    status, failures = evaluate_supply(
        last_24h=4, rolling_mean=6.0, daily_floor=12, daily_target=60
    )
    assert status == "failed"
    assert any("last 24 hours" in item for item in failures)
    assert any("rolling average" in item for item in failures)


def test_short_of_target_is_reported_but_does_not_fail() -> None:
    status, failures = evaluate_supply(
        last_24h=20, rolling_mean=22.0, daily_floor=12, daily_target=60
    )
    assert status == "short"
    assert failures and "target of 60" in failures[0]


def test_meeting_the_target_is_healthy() -> None:
    status, failures = evaluate_supply(
        last_24h=61, rolling_mean=60.0, daily_floor=12, daily_target=60
    )
    assert status == "healthy"
    assert failures == []


def test_a_single_good_day_cannot_hide_a_bad_week() -> None:
    status, failures = evaluate_supply(
        last_24h=30, rolling_mean=5.0, daily_floor=12, daily_target=60
    )
    assert status == "failed"
    assert len(failures) == 1
    assert "rolling average" in failures[0]


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
    print(f"Supply watchdog checks passed ({len(tests)} tests).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
