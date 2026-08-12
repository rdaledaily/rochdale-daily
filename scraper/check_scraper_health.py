"""Fail loudly when discovery succeeds but the public homepage is stale."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATUS_PATH = ROOT / "scraper_status.json"
FRONTPAGE_PATH = ROOT / "articles" / "frontpage.json"
HEALTH_PATH = ROOT / "scraper_health.json"
MIN_LIVE_STORIES = int(os.getenv("MIN_LIVE_STORIES", "40"))
MAX_FRESH_AGE_HOURS = int(os.getenv("SCRAPER_HEALTH_FRESH_HOURS", "24"))
TOP_STORY_FRESH_HOURS = int(os.getenv("SCRAPER_HEALTH_TOP_FRESH_HOURS", "6"))


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def published_at(article: dict[str, Any]) -> datetime | None:
    return parse_dt(article.get("first_published_at") or article.get("published_at"))


def main() -> None:
    status = read_json(STATUS_PATH, {})
    frontpage = read_json(FRONTPAGE_PATH, {})
    articles = frontpage.get("articles", []) if isinstance(frontpage, dict) else []
    if not isinstance(articles, list):
        articles = []

    now = datetime.now(timezone.utc)
    fresh_cutoff = now - timedelta(hours=MAX_FRESH_AGE_HOURS)
    top_fresh_cutoff = now - timedelta(hours=TOP_STORY_FRESH_HOURS)

    valid_articles = [article for article in articles if isinstance(article, dict)]
    fresh = [article for article in valid_articles if (published_at(article) or datetime.min.replace(tzinfo=timezone.utc)) >= fresh_cutoff]
    top_three = valid_articles[:3]
    top_three_fresh = [article for article in top_three if (published_at(article) or datetime.min.replace(tzinfo=timezone.utc)) >= top_fresh_cutoff]
    lead_published = published_at(valid_articles[0]) if valid_articles else None

    raw_candidates = int(status.get("raw_candidates") or 0)
    new_articles = int(status.get("new_articles") or 0)
    live_articles = int(status.get("live_articles") or 0)
    collector_errors = status.get("collector_errors") or {}

    failures: list[str] = []
    if live_articles < MIN_LIVE_STORIES:
        failures.append(
            f"live article count {live_articles} is below required minimum {MIN_LIVE_STORIES}"
        )
    if raw_candidates > 0 and new_articles > 0 and not fresh:
        failures.append(
            "discovery produced new articles but the homepage contains no story first published in the last "
            f"{MAX_FRESH_AGE_HOURS} hours"
        )
    if raw_candidates > 0 and new_articles > 0 and not top_three_fresh:
        failures.append(
            "discovery produced new articles but none of the top three homepage stories was first published in the last "
            f"{TOP_STORY_FRESH_HOURS} hours"
        )
    if raw_candidates > 0 and new_articles > 0 and valid_articles and (
        lead_published is None or lead_published < fresh_cutoff
    ):
        failures.append(
            "discovery produced new articles but the homepage lead is older than the allowed freshness window"
        )
    if len(valid_articles) < 3 and raw_candidates >= 10:
        failures.append(
            f"homepage collapsed to {len(valid_articles)} stories despite {raw_candidates} eligible discovery candidates"
        )

    payload = {
        "checked_at": now.isoformat().replace("+00:00", "Z"),
        "raw_candidates": raw_candidates,
        "new_articles": new_articles,
        "live_articles": live_articles,
        "frontpage_articles": len(valid_articles),
        "fresh_frontpage_articles": len(fresh),
        "fresh_top_three_articles": len(top_three_fresh),
        "freshness_window_hours": MAX_FRESH_AGE_HOURS,
        "top_story_freshness_hours": TOP_STORY_FRESH_HOURS,
        "lead_first_published_at": lead_published.isoformat().replace("+00:00", "Z") if lead_published else None,
        "collector_errors": collector_errors,
        "status": "failed" if failures else "healthy",
        "failures": failures,
    }
    HEALTH_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if failures:
        raise SystemExit("; ".join(failures))


if __name__ == "__main__":
    main()
