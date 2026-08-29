from __future__ import annotations

from datetime import datetime, timedelta, timezone

from candidate_autopsy import (
    GATE_ORDER,
    PUBLISHABLE,
    age_hours,
    classify,
    parse_dt,
    survivors_by_age,
)

NOW = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)


def candidate(hours_ago: float, **extra) -> dict:
    stamp = (NOW - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")
    payload = {"source_published_at": stamp, "source_title": "t", "source_name": "n"}
    payload.update(extra)
    return payload


def test_age_is_measured_from_source_publication() -> None:
    assert age_hours(candidate(5), now=NOW) == 5
    assert age_hours({}, now=NOW) is None


def test_missing_timestamps_do_not_crash_the_parser() -> None:
    assert parse_dt(None) is None
    assert parse_dt("not a date") is None


def test_first_blocking_gate_wins_so_counts_do_not_double() -> None:
    gates = {"age": lambda record: True, "not local": lambda record: True}
    assert classify(candidate(100), gates) == "age"


def test_a_candidate_clearing_every_gate_is_publishable() -> None:
    gates = {name: (lambda record: False) for name in GATE_ORDER}
    assert classify(candidate(1), gates) == PUBLISHABLE


def test_a_gate_that_raises_is_reported_not_fatal() -> None:
    def explode(record):
        raise ValueError("boom")

    verdict = classify(candidate(1), {"not local": explode})
    assert verdict == "not local (gate error)"


def test_missing_gates_are_skipped_rather_than_assumed_to_block() -> None:
    """When a module cannot be imported its gate is absent, and absence must not
    silently pass candidates off as publishable through a crash."""
    assert classify(candidate(1), {}) == PUBLISHABLE


def test_age_sensitivity_counts_admitted_candidates_per_width() -> None:
    records = [candidate(1), candidate(20), candidate(60), candidate(200)]
    result = survivors_by_age(records, now=NOW, widths=[6, 24, 72, 168])
    assert result == {"6h": 1, "24h": 2, "72h": 3, "168h": 3}


def test_candidates_without_a_timestamp_are_never_counted_as_fresh() -> None:
    assert survivors_by_age([{}], now=NOW, widths=[168]) == {"168h": 0}


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
    print(f"Candidate autopsy checks passed ({len(tests)} tests).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
