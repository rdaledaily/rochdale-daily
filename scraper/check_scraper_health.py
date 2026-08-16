"""Fail loudly when discovery succeeds but the public homepage is stale or starved."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATUS_PATH = ROOT / "scraper_status.json"
ARTICLES_PATH = ROOT / "articles.json"
FRONTPAGE_PATH = ROOT / "articles" / "frontpage.json"
HEALTH_PATH = ROOT / "scraper_health.json"
MIN_LIVE_STORIES = int(os.getenv("MIN_LIVE_STORIES", "40"))
MIN_FRESH_FRONTPAGE_STORIES = int(os.getenv("MIN_FRESH_FRONTPAGE_STORIES", "0"))
FRONTPAGE_MIN_ARTICLES = int(os.getenv("FRONTPAGE_MIN_ARTICLES", "12"))
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


def is_eligible_news_article(article: Any) -> bool:
    if not isinstance(article, dict):
        return False
    if str(article.get("status") or "published").lower() != "published":
        return False
    if article.get("requires_approval"):
        return False
    if article.get("exclude_from_frontpage") is True:
        return False
    if str(article.get("source_kind") or "").lower() == "event":
        return False
    if str(article.get("category") or "").lower() == "events":
        return False
    return True


def main() -> None:
    status = read_json(STATUS_PATH, {})
    frontpage = read_json(FRONTPAGE_PATH, {})
    public_feed = read_json(ARTICLES_PATH, [])
    articles = frontpage.get("articles", []) if isinstance(frontpage, dict) else []
    if not isinstance(articles, list):
        articles = []
    if not isinstance(public_feed, list):
        public_feed = []

    now = datetime.now(timezone.utc)
    fresh_cutoff = now - timedelta(hours=MAX_FRESH_AGE_HOURS)
    top_fresh_cutoff = now - timedelta(hours=TOP_STORY_FRESH_HOURS)

    valid_articles = [article for article in articles if isinstance(article, dict)]
    eligible_news_feed = [article for article in public_feed if is_eligible_news_article(article)]
    eligible_fresh_feed = [
        article
        for article in eligible_news_feed
        if (published_at(article) or datetime.min.replace(tzinfo=timezone.utc)) >= fresh_cutoff
    ]
    fresh = [
        article
        for article in valid_articles
        if (published_at(article) or datetime.min.replace(tzinfo=timezone.utc)) >= fresh_cutoff
    ]
    top_three = valid_articles[:3]
    top_three_fresh = [
        article
        for article in top_three
        if (published_at(article) or datetime.min.replace(tzinfo=timezone.utc)) >= top_fresh_cutoff
    ]
    lead_published = published_at(valid_articles[0]) if valid_articles else None
    eligible_top_fresh = [
        article
        for article in eligible_news_feed
        if (published_at(article) or datetime.min.replace(tzinfo=timezone.utc)) >= top_fresh_cutoff
    ]

    raw_candidates = int(status.get("raw_candidates") or 0)
    new_articles = int(status.get("new_articles") or 0)
    live_articles = int(status.get("live_articles") or 0)
    collector_errors = status.get("collector_errors") or {}

    required_fresh_frontpage = min(
        MIN_FRESH_FRONTPAGE_STORIES,
        len(eligible_fresh_feed),
    ) if MIN_FRESH_FRONTPAGE_STORIES > 0 else 0

    failures: list[str] = []
    if live_articles < MIN_LIVE_STORIES:
        failures.append(
            f"live article count {live_articles} is below required minimum {MIN_LIVE_STORIES}"
        )
    if raw_candidates > 0 and len(fresh) < required_fresh_frontpage:
        failures.append(
            f"fresh homepage count {len(fresh)} is below achievable minimum "
            f"{required_fresh_frontpage} within {MAX_FRESH_AGE_HOURS} hours "
            f"({len(eligible_fresh_feed)} eligible fresh reservoir stories available)"
        )
    if raw_candidates > 0 and new_articles > 0 and not fresh:
        failures.append(
            "discovery produced new articles but the homepage contains no story first published in the last "
            f"{MAX_FRESH_AGE_HOURS} hours"
        )
    if raw_candidates > 0 and new_articles > 0 and eligible_top_fresh and not top_three_fresh:
        failures.append(
            "the public feed contains eligible news first published in the last "
            f"{TOP_STORY_FRESH_HOURS} hours but none appears in the top three homepage stories"
        )
    if raw_candidates > 0 and new_articles > 0 and valid_articles and (
        lead_published is None or lead_published < fresh_cutoff
    ):
        failures.append(
            "discovery produced new articles but the homepage lead is older than the allowed freshness window"
        )

    if (
        FRONTPAGE_MIN_ARTICLES > 0
        and len(eligible_fresh_feed) >= FRONTPAGE_MIN_ARTICLES
        and len(valid_articles) < FRONTPAGE_MIN_ARTICLES
    ):
        failures.append(
            f"homepage has {len(valid_articles)} stories despite "
            f"{len(eligible_fresh_feed)} eligible fresh reservoir stories; "
            f"configured minimum is {FRONTPAGE_MIN_ARTICLES}"
        )

    collapse_floor = min(3, len(eligible_fresh_feed))
    if len(valid_articles) < collapse_floor:
        failures.append(
            f"homepage collapsed to {len(valid_articles)} stories despite "
            f"{len(eligible_fresh_feed)} eligible stories inside the "
            f"{MAX_FRESH_AGE_HOURS}-hour freshness window"
        )

    payload = {
        "checked_at": now.isoformat().replace("+00:00", "Z"),
        "raw_candidates": raw_candidates,
        "new_articles": new_articles,
        "live_articles": live_articles,
        "eligible_published_news_records": len(eligible_news_feed),
        "eligible_fresh_news_records": len(eligible_fresh_feed),
        "frontpage_articles": len(valid_articles),
        "fresh_frontpage_articles": len(fresh),
        "fresh_top_three_articles": len(top_three_fresh),
        "eligible_top_fresh_feed_articles": len(eligible_top_fresh),
        "minimum_live_articles": MIN_LIVE_STORIES,
        "configured_minimum_frontpage_articles": FRONTPAGE_MIN_ARTICLES,
        "configured_minimum_fresh_frontpage_articles": MIN_FRESH_FRONTPAGE_STORIES,
        "required_fresh_frontpage_articles_this_run": required_fresh_frontpage,
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
