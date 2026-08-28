"""Report — loudly and separately from publication — how much news the borough actually got.

The newsroom health check answers "did this run render the best edition the
available supply allowed?". It deliberately clamps every floor to achievable
supply, so a borough-wide collection famine passes as healthy. This watchdog
answers the other question: "is the supply itself failing?".

It never runs inside the site-writer lane and never blocks a publish. It reads
the published record, compares real daily output against the newsroom target,
and exits non-zero on a shortfall so GitHub's own failure notification carries
the number to the editor. No padding, no fallback tier — a thin day is reported
as a thin day.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_PATH = ROOT / "archive-index.json"
ARTICLES_PATH = ROOT / "articles.json"
REPORT_PATH = ROOT / "supply_report.json"

DAILY_TARGET = int(os.getenv("SUPPLY_DAILY_TARGET", "60"))
DAILY_FLOOR = int(os.getenv("SUPPLY_DAILY_FLOOR", "12"))
ROLLING_DAYS = max(2, int(os.getenv("SUPPLY_ROLLING_DAYS", "7")))
EVENT_CATEGORIES = {"events"}


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def record_published_at(record: Any) -> datetime | None:
    if not isinstance(record, dict):
        return None
    return parse_dt(record.get("first_published_at") or record.get("published_at"))


def is_news_record(record: Any) -> bool:
    """Events are listings, not journalism. They are counted separately."""
    if not isinstance(record, dict):
        return False
    return str(record.get("category") or "").strip().lower() not in EVENT_CATEGORIES


def daily_counts(records: Iterable[Any], *, now: datetime, days: int) -> dict[str, int]:
    """Published-news counts keyed by UTC date, covering every day in the window.

    Days with no output appear as an explicit zero rather than being missing:
    a silent gap is the failure mode this watchdog exists to surface.
    """
    floor = (now - timedelta(days=days - 1)).date()
    counts = {
        (floor + timedelta(days=offset)).isoformat(): 0
        for offset in range(days)
    }
    for record in records:
        if not is_news_record(record):
            continue
        published = record_published_at(record)
        if published is None:
            continue
        key = published.date().isoformat()
        if key in counts:
            counts[key] += 1
    return counts


def count_since(records: Iterable[Any], *, now: datetime, hours: int) -> int:
    cutoff = now - timedelta(hours=hours)
    total = 0
    for record in records:
        if not is_news_record(record):
            continue
        published = record_published_at(record)
        if published is not None and published >= cutoff:
            total += 1
    return total


def evaluate_supply(
    *,
    last_24h: int,
    rolling_mean: float,
    daily_floor: int,
    daily_target: int,
) -> tuple[str, list[str]]:
    """Classify supply and describe the shortfall in the editor's own terms."""
    failures: list[str] = []
    if last_24h < daily_floor:
        failures.append(
            f"only {last_24h} news stories published in the last 24 hours, "
            f"below the floor of {daily_floor} (newsroom target {daily_target}/day)"
        )
    if rolling_mean < daily_floor:
        failures.append(
            f"rolling average is {rolling_mean:.1f} stories/day, "
            f"below the floor of {daily_floor} (newsroom target {daily_target}/day)"
        )
    if failures:
        return "failed", failures
    if last_24h < daily_target:
        return "short", [
            f"{last_24h} stories in the last 24 hours against a target of {daily_target}"
        ]
    return "healthy", []


def main() -> None:
    now = datetime.now(timezone.utc)
    archive = read_json(ARCHIVE_PATH, [])
    feed = read_json(ARTICLES_PATH, [])
    if not isinstance(archive, list):
        archive = []
    if not isinstance(feed, list):
        feed = []

    # The archive is the permanent published record; the live feed only holds a
    # rolling window, so anything published today that is still in the feed but
    # not yet archived is merged in by slug/id to avoid undercounting.
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for record in list(archive) + list(feed):
        if not isinstance(record, dict):
            continue
        key = str(record.get("slug") or record.get("id") or record.get("url") or "")
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        merged.append(record)

    per_day = daily_counts(merged, now=now, days=ROLLING_DAYS)
    rolling_values = list(per_day.values())
    rolling_mean = sum(rolling_values) / len(rolling_values) if rolling_values else 0.0
    last_24h = count_since(merged, now=now, hours=24)
    last_7d = sum(rolling_values)

    status, failures = evaluate_supply(
        last_24h=last_24h,
        rolling_mean=rolling_mean,
        daily_floor=DAILY_FLOOR,
        daily_target=DAILY_TARGET,
    )

    routes = Counter(
        str(record.get("publication_route") or "unknown")
        for record in feed
        if isinstance(record, dict) and is_news_record(record)
    )

    payload = {
        "checked_at": now.isoformat().replace("+00:00", "Z"),
        "daily_target": DAILY_TARGET,
        "daily_floor": DAILY_FLOOR,
        "published_last_24h": last_24h,
        "published_last_%dd" % ROLLING_DAYS: last_7d,
        "rolling_days": ROLLING_DAYS,
        "rolling_mean_per_day": round(rolling_mean, 2),
        "shortfall_against_target_per_day": max(0, DAILY_TARGET - last_24h),
        "published_per_day": per_day,
        "live_feed_records": len(feed),
        "live_feed_routes": dict(routes),
        "status": status,
        "failures": failures,
    }
    REPORT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        lines = [
            "## Rochdale Daily supply",
            "",
            f"- Last 24 hours: **{last_24h}** news stories (floor {DAILY_FLOOR}, target {DAILY_TARGET})",
            f"- Last {ROLLING_DAYS} days: **{last_7d}** ({rolling_mean:.1f}/day)",
            "",
            "| Day | Stories |",
            "| --- | ---: |",
        ]
        lines += [f"| {day} | {count} |" for day, count in sorted(per_day.items())]
        if failures:
            lines += ["", "**Shortfall:**"] + [f"- {item}" for item in failures]
        try:
            with open(summary_path, "a", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")
        except OSError:
            pass

    if status == "failed":
        raise SystemExit("; ".join(failures))


if __name__ == "__main__":
    main()
