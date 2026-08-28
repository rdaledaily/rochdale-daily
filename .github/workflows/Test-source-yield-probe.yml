from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from source_yield_probe import (
    SOURCES,
    count_recent,
    discover_feeds,
    json_dates,
    parse_dt,
    per_day,
)

NOW = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)


def test_iso_stamps_parse() -> None:
    assert parse_dt("2026-08-27T09:30:00Z") == datetime(2026, 8, 27, 9, 30, tzinfo=timezone.utc)
    assert parse_dt("2026-08-27") == datetime(2026, 8, 27, 0, 0, tzinfo=timezone.utc)


def test_year_month_extracts_parse() -> None:
    """data.police.uk publishes monthly, as YYYY-MM."""
    assert parse_dt("2026-06") == datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)


def test_posix_seconds_parse() -> None:
    """Reddit stamps posts as created_utc floats."""
    epoch = 1787913000.0
    assert parse_dt(epoch) == datetime.fromtimestamp(epoch, tz=timezone.utc)
    assert parse_dt(str(epoch)) == datetime.fromtimestamp(epoch, tz=timezone.utc)


def test_junk_values_are_not_dates() -> None:
    for value in (None, "", "not a date", [], {}):
        assert parse_dt(value) is None


def test_nested_json_lists_are_read() -> None:
    body = json.dumps(
        {"data": {"children": [{"created_utc": 1787913000.0}, {"created_utc": 1787826600.0}]}}
    )
    dates = json_dates(body, list_path=["data", "children"], date_keys=["created_utc"])
    assert len(dates) == 2
    assert all(item is not None for item in dates)


def test_top_level_json_lists_are_read() -> None:
    body = json.dumps([{"month": "2026-07"}, {"month": "2026-06"}])
    dates = json_dates(body, list_path=[], date_keys=["month"])
    assert len(dates) == 2


def test_malformed_json_yields_nothing_rather_than_raising() -> None:
    assert json_dates("<html>nope</html>", list_path=["data"], date_keys=["x"]) == []


def test_recent_window_excludes_older_items() -> None:
    dates = [NOW - timedelta(days=1), NOW - timedelta(days=13), NOW - timedelta(days=40), None]
    assert count_recent(dates, days=14, reference=NOW) == 2


def test_per_day_is_the_measured_rate() -> None:
    assert per_day(28, 14) == 2.0
    assert per_day(0, 14) == 0.0


def test_nested_date_keys_are_followed() -> None:
    """Reddit nests the stamp under data, Parliament under value."""
    body = json.dumps({"data": {"children": [{"data": {"created_utc": 1787913000.0}}]}})
    dates = json_dates(body, list_path=["data", "children"], date_keys=["data.created_utc"])
    assert len(dates) == 1 and dates[0] is not None


def test_declared_feed_links_are_discovered() -> None:
    html = (
        '<html><head><link rel="alternate" type="application/rss+xml" '
        'href="/news/feed.xml"></head></html>'
    )
    assert discover_feeds(html, "https://example.gov.uk/news/") == [
        "https://example.gov.uk/news/feed.xml"
    ]


def test_reversed_link_attribute_order_is_discovered() -> None:
    html = '<link href="https://example.gov.uk/rss" type="application/atom+xml">'
    assert discover_feeds(html, "https://example.gov.uk/") == ["https://example.gov.uk/rss"]


def test_pages_without_feeds_discover_nothing() -> None:
    assert discover_feeds("<html><body>no feed here</body></html>", "https://x.test/") == []


def test_every_source_declares_its_licence_and_story_shape() -> None:
    for source in SOURCES:
        assert source["name"]
        assert source["licence"], source["name"]
        assert source["story_shape"], source["name"]
        assert callable(source["probe"]), source["name"]


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
    print(f"Source yield probe checks passed ({len(tests)} tests).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
