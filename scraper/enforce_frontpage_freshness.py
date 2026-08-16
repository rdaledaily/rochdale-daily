#!/usr/bin/env python3
"""Keep the Rochdale Daily homepage genuinely fresh without starving it.

Page generation reconstructs a much larger published article reservoir than the
small live scrape snapshot. This final pass therefore refills the homepage from
that reconstructed reservoir, but only with genuinely eligible stories inside
the configured freshness window. Old archive copy is never used merely to hit a
numeric target.

Editor pins and genuinely active live/breaking coverage retain their existing
special handling.
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

FRONTPAGE = Path(os.getenv("FRONTPAGE_JSON", "articles/frontpage.json"))
ARTICLES = Path(os.getenv("ARTICLES_JSON", "articles.json"))
FRESH_HOURS = int(os.getenv("FRONTPAGE_FRESH_HOURS", "14"))
FRONTPAGE_MIN = int(os.getenv("FRONTPAGE_MIN_ARTICLES", "12"))
FRONTPAGE_TARGET = int(os.getenv("FRONTPAGE_TARGET_ARTICLES", "30"))
SPORT_PREVIEW_MAX_HOURS = int(os.getenv("SPORT_PREVIEW_MAX_HOURS", "8"))
LOCAL_TZ = ZoneInfo("Europe/London")

UTILITY_TITLE_PATTERNS = (
    re.compile(r"\blive (?:bus|tram|train) departures?\b", re.I),
    re.compile(r"\bcontact (?:details|information)\b", re.I),
)
UTILITY_URL_PATTERNS = (
    re.compile(r"/live-departures/", re.I),
    re.compile(r"/contact-us/[^?#]*(?:contact|details)", re.I),
)
THIN_UTILITY_TITLE_PATTERNS = (
    re.compile(r"\bupdates? contact (?:details|information)\b", re.I),
    re.compile(r"\bcontact (?:details|information) (?:for|of)\b", re.I),
)
THIN_UTILITY_URL_PATTERNS = (
    re.compile(r"/contact-us/[^?#]*(?:contact|details)", re.I),
    re.compile(r"/noindex/[^?#]*(?:contact|details)", re.I),
)
SPORT_PREVIEW_PATTERN = re.compile(
    r"\b(?:today|this afternoon|this evening|kick[ -]?off|fixture|faces?|match preview)\b",
    re.I,
)
TODAY_DEADLINE_PATTERN = re.compile(
    r"\b(?:until|by|before)\s+(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ampm>am|pm)\s+today\b",
    re.I,
)


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
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def first_published(article: dict[str, Any]) -> datetime | None:
    return parse_dt(article.get("first_published_at") or article.get("published_at"))


def latest_update(article: dict[str, Any]) -> datetime:
    return (
        parse_dt(article.get("last_updated_at"))
        or parse_dt(article.get("scraped_at"))
        or first_published(article)
        or datetime.min.replace(tzinfo=timezone.utc)
    )


def _is_active_live(article: dict[str, Any]) -> bool:
    return bool(
        article.get("live_story") is True
        or article.get("breaking_news") is True
        or article.get("is_ongoing") is True
    )


def _is_editorial(article: dict[str, Any]) -> bool:
    return bool(
        article.get("manual_article") is True
        or str(article.get("source_kind") or "").lower() == "editorial"
    )


def latest_verified_update(article: dict[str, Any]) -> datetime:
    active = _is_active_live(article)
    editorial = _is_editorial(article)
    if not active or editorial:
        return latest_update(article)

    candidates: list[datetime] = []
    raw_updates = article.get("live_updates") or []
    if isinstance(raw_updates, list):
        for update in raw_updates:
            if not isinstance(update, dict):
                continue
            parsed = parse_dt(
                update.get("timestamp")
                or update.get("updated_at")
                or update.get("published_at")
            )
            if parsed is not None:
                candidates.append(parsed)
    if candidates:
        return max(candidates)
    return first_published(article) or datetime.min.replace(tzinfo=timezone.utc)


def active_pin(article: dict[str, Any], now: datetime) -> bool:
    if article.get("featured") is not True:
        return False
    until = parse_dt(article.get("frontpage_until"))
    return until is not None and until >= now


def _article_urls(article: dict[str, Any]) -> list[str]:
    urls = [str(article.get("source_url") or "")]
    raw_urls = article.get("source_urls") or []
    if isinstance(raw_urls, list):
        urls.extend(str(url) for url in raw_urls)
    return urls


def is_utility_not_lead(article: dict[str, Any]) -> bool:
    if _is_editorial(article):
        return False
    title = str(article.get("title") or "")
    urls = _article_urls(article)
    return any(pattern.search(title) for pattern in UTILITY_TITLE_PATTERNS) or any(
        pattern.search(url) for url in urls for pattern in UTILITY_URL_PATTERNS
    )


def is_thin_utility_not_frontpage(article: dict[str, Any]) -> bool:
    if _is_editorial(article):
        return False
    title = str(article.get("title") or "")
    urls = _article_urls(article)
    return any(pattern.search(title) for pattern in THIN_UTILITY_TITLE_PATTERNS) or any(
        pattern.search(url) for url in urls for pattern in THIN_UTILITY_URL_PATTERNS
    )


def is_expired_today_deadline(article: dict[str, Any], now: datetime) -> bool:
    if _is_editorial(article):
        return False
    text = " ".join(str(article.get(key) or "") for key in ("title", "excerpt", "summary"))
    match = TODAY_DEADLINE_PATTERN.search(text)
    if not match:
        return False
    hour = int(match.group("hour"))
    minute = int(match.group("minute") or 0)
    if not 1 <= hour <= 12 or not 0 <= minute <= 59:
        return False
    if match.group("ampm").lower() == "pm" and hour != 12:
        hour += 12
    elif match.group("ampm").lower() == "am" and hour == 12:
        hour = 0
    local_now = now.astimezone(LOCAL_TZ)
    published = first_published(article)
    anchor = published.astimezone(LOCAL_TZ) if published is not None else local_now
    deadline = anchor.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return local_now > deadline


def is_expired_time_sensitive_preview(article: dict[str, Any], now: datetime) -> bool:
    if _is_editorial(article):
        return False
    if str(article.get("category") or "").strip().lower() not in {"sport", "sports"}:
        return False

    text = " ".join(str(article.get(key) or "") for key in ("title", "excerpt", "summary"))
    if not SPORT_PREVIEW_PATTERN.search(text):
        return False

    event_start = parse_dt(article.get("event_start_at"))
    if event_start is not None:
        return now >= event_start + timedelta(hours=3)

    published = first_published(article)
    if published is None:
        return False
    return now >= published + timedelta(hours=SPORT_PREVIEW_MAX_HOURS)


def is_recent_live_update(article: dict[str, Any], cutoff: datetime) -> bool:
    return (
        _is_active_live(article)
        and latest_verified_update(article) >= cutoff
        and not is_utility_not_lead(article)
    )


def _identity(article: dict[str, Any]) -> str:
    return str(
        article.get("id")
        or article.get("slug")
        or article.get("story_key")
        or article.get("source_url")
        or id(article)
    )


def _eligible_reservoir_article(article: Any, now: datetime, cutoff: datetime) -> bool:
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
    if is_thin_utility_not_frontpage(article):
        return False
    if is_expired_today_deadline(article, now):
        return False
    if is_expired_time_sensitive_preview(article, now):
        return False

    published = first_published(article)
    return bool(
        (published is not None and published >= cutoff)
        or active_pin(article, now)
        or is_recent_live_update(article, cutoff)
    )


def _category(article: dict[str, Any]) -> str:
    value = str(article.get("category") or "news").strip().lower()
    return value or "news"


def _area(article: dict[str, Any]) -> str:
    value = str(article.get("area") or article.get("ward") or "borough-wide").strip().lower()
    return value or "borough-wide"


def _balanced_refill(
    candidates: list[dict[str, Any]],
    existing: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    """Choose newest refill stories while spreading them across categories/areas."""
    remaining = sorted(candidates, key=latest_update, reverse=True)
    selected: list[dict[str, Any]] = []
    category_counts = Counter(_category(item) for item in existing)
    area_counts = Counter(_area(item) for item in existing)

    while remaining and len(selected) < limit:
        best_index = max(
            range(len(remaining)),
            key=lambda index: (
                -category_counts[_category(remaining[index])],
                -area_counts[_area(remaining[index])],
                latest_update(remaining[index]),
            ),
        )
        item = remaining.pop(best_index)
        selected.append(item)
        category_counts[_category(item)] += 1
        area_counts[_area(item)] += 1

    return selected


def main() -> None:
    payload = read_json(FRONTPAGE, {})
    articles = payload.get("articles") if isinstance(payload, dict) else None
    if not isinstance(articles, list):
        raise SystemExit("frontpage articles array missing")

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=FRESH_HOURS)
    valid = [a for a in articles if isinstance(a, dict)]

    thin_utility = [a for a in valid if is_thin_utility_not_frontpage(a)]
    thin_utility_ids = {_identity(a) for a in thin_utility}
    valid = [a for a in valid if _identity(a) not in thin_utility_ids]

    expired_deadlines = [a for a in valid if is_expired_today_deadline(a, now)]
    expired_deadline_ids = {_identity(a) for a in expired_deadlines}
    valid = [a for a in valid if _identity(a) not in expired_deadline_ids]

    expired_previews = [a for a in valid if is_expired_time_sensitive_preview(a, now)]
    expired_preview_ids = {_identity(a) for a in expired_previews}
    valid = [a for a in valid if _identity(a) not in expired_preview_ids]

    reservoir = read_json(ARTICLES, [])
    if not isinstance(reservoir, list):
        reservoir = []

    existing_ids = {_identity(a) for a in valid}
    reservoir_candidates = [
        a for a in reservoir
        if _eligible_reservoir_article(a, now, cutoff)
        and _identity(a) not in existing_ids
    ]
    refill_limit = max(0, FRONTPAGE_TARGET - len(valid))
    refilled = _balanced_refill(reservoir_candidates, valid, refill_limit)
    if refilled:
        valid.extend(refilled)

    fresh = [
        a for a in valid
        if (first_published(a) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff
    ]
    fresh_ids = {_identity(a) for a in fresh}
    older = [a for a in valid if _identity(a) not in fresh_ids]

    fresh_pins = [a for a in fresh if active_pin(a, now)]
    fresh_pin_ids = {_identity(a) for a in fresh_pins}
    fresh_remaining = [a for a in fresh if _identity(a) not in fresh_pin_ids]
    fresh_substantive = [a for a in fresh_remaining if not is_utility_not_lead(a)]
    fresh_utility = [a for a in fresh_remaining if is_utility_not_lead(a)]

    recent_live = [a for a in older if is_recent_live_update(a, cutoff)]
    recent_live_ids = {_identity(a) for a in recent_live}
    older_remaining = [a for a in older if _identity(a) not in recent_live_ids]
    stale_pins = [a for a in older_remaining if active_pin(a, now)]
    stale_pin_ids = {_identity(a) for a in stale_pins}
    dropped_stale = [a for a in older_remaining if _identity(a) not in stale_pin_ids]

    fresh_pins.sort(key=latest_verified_update, reverse=True)
    original_ids = {_identity(a) for a in articles if isinstance(a, dict)}
    original_fresh = [a for a in fresh_substantive if _identity(a) in original_ids]
    refill_fresh = [a for a in fresh_substantive if _identity(a) not in original_ids]
    original_fresh.sort(key=latest_update, reverse=True)
    refill_fresh = _balanced_refill(refill_fresh, original_fresh, len(refill_fresh))
    fresh_substantive = original_fresh + refill_fresh

    recent_live.sort(key=latest_verified_update, reverse=True)
    fresh_utility.sort(key=latest_update, reverse=True)
    stale_pins.sort(key=latest_verified_update, reverse=True)

    ordered = fresh_pins + fresh_substantive + recent_live + fresh_utility + stale_pins
    ordered = ordered[:FRONTPAGE_TARGET]

    for index, article in enumerate(ordered):
        article["frontpage_rank"] = index
        article["frontpage_priority"] = max(1, 1000 - index)
        article["slot"] = "lead" if index == 0 else "secondary-1" if index == 1 else "secondary-2" if index == 2 else ""

    payload["articles"] = ordered
    payload["count"] = len(ordered)
    coverage = payload.get("coverage")
    if not isinstance(coverage, dict):
        coverage = {}
    coverage["frontpage_minimum_met"] = len(ordered) >= FRONTPAGE_MIN
    coverage["reservoir_fresh_candidates"] = len(reservoir_candidates)
    coverage["reservoir_refilled"] = len(refilled)
    payload["coverage"] = coverage
    payload["freshness_guard"] = {
        "fresh_hours": FRESH_HOURS,
        "frontpage_minimum": FRONTPAGE_MIN,
        "frontpage_target": FRONTPAGE_TARGET,
        "reservoir_records": len(reservoir),
        "reservoir_fresh_candidates": len(reservoir_candidates),
        "reservoir_refilled": len(refilled),
        "fresh_editor_pins": len(fresh_pins),
        "stale_editor_pins_retained": len(stale_pins),
        "fresh_articles": len(fresh),
        "fresh_substantive_articles": len(fresh_substantive) + len(fresh_pins),
        "recent_live_updates": len(recent_live),
        "fresh_utility_articles": len(fresh_utility),
        "thin_utility_frontpage_dropped": len(thin_utility),
        "expired_same_day_deadlines_dropped": len(expired_deadlines),
        "expired_sports_previews_dropped": len(expired_previews),
        "stale_fallback_dropped": len(dropped_stale),
        "enforced_at": now.isoformat().replace("+00:00", "Z"),
    }
    FRONTPAGE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lead = ordered[0].get("title") if ordered else "(none)"
    print(
        f"Frontpage freshness enforced: {len(ordered)} final story/stories; "
        f"{len(refilled)} refilled from {len(reservoir_candidates)} eligible <= {FRESH_HOURS}h reservoir candidate(s); "
        f"{len(fresh_pins)} fresh pin(s), {len(fresh_substantive)} substantive fresh story/stories, "
        f"{len(recent_live)} active live update(s), {len(fresh_utility)} utility, "
        f"{len(thin_utility)} thin directory/contact rewrite(s) dropped, "
        f"{len(expired_deadlines)} expired deadline story/stories dropped, "
        f"{len(expired_previews)} expired sports preview(s) dropped, "
        f"{len(stale_pins)} explicit stale pin(s), {len(dropped_stale)} stale fallback story/stories dropped. "
        f"Lead: {lead}"
    )


if __name__ == "__main__":
    main()
