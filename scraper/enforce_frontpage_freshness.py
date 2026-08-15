#!/usr/bin/env python3
"""Keep the Rochdale Daily homepage genuinely fresh without deleting archive material.

The homepage is a live news surface, not an archive. Routine fallback stories older
than the configured freshness window are therefore removed from frontpage.json
rather than merely pushed lower down. Archive/category/area pages keep the full
historical record.

An editor may explicitly keep an older story visible with ``featured`` and a live
``frontpage_until`` value. Genuinely active live/breaking coverage may also remain
when it has received a verified update inside the freshness window.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

FRONTPAGE = Path(os.getenv("FRONTPAGE_JSON", "articles/frontpage.json"))
FRESH_HOURS = int(os.getenv("FRONTPAGE_FRESH_HOURS", "14"))
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
SPORT_PREVIEW_PATTERN = re.compile(
    r"\b(?:today|this afternoon|this evening|kick[ -]?off|fixture|faces?|match preview)\b",
    re.I,
)
TODAY_DEADLINE_PATTERN = re.compile(
    r"\b(?:until|by|before)\s+(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ampm>am|pm)\s+today\b",
    re.I,
)


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


def active_pin(article: dict[str, Any], now: datetime) -> bool:
    if article.get("featured") is not True:
        return False
    until = parse_dt(article.get("frontpage_until"))
    return until is not None and until >= now


def is_utility_not_lead(article: dict[str, Any]) -> bool:
    if article.get("manual_article") is True or str(article.get("source_kind") or "").lower() == "editorial":
        return False
    title = str(article.get("title") or "")
    urls = [str(article.get("source_url") or "")]
    raw_urls = article.get("source_urls") or []
    if isinstance(raw_urls, list):
        urls.extend(str(url) for url in raw_urls)
    return any(pattern.search(title) for pattern in UTILITY_TITLE_PATTERNS) or any(
        pattern.search(url) for url in urls for pattern in UTILITY_URL_PATTERNS
    )


def is_expired_today_deadline(article: dict[str, Any], now: datetime) -> bool:
    """Expire automated same-day offers/notices once their stated local deadline passes."""
    if article.get("manual_article") is True or str(article.get("source_kind") or "").lower() == "editorial":
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
    deadline = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return local_now > deadline


def is_expired_time_sensitive_preview(article: dict[str, Any], now: datetime) -> bool:
    """Expire machine-generated pre-match sports copy once it has stopped being useful."""
    if article.get("manual_article") is True or str(article.get("source_kind") or "").lower() == "editorial":
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
    active = bool(
        article.get("live_story") is True
        or article.get("breaking_news") is True
        or article.get("is_ongoing") is True
    )
    return active and latest_update(article) >= cutoff and not is_utility_not_lead(article)


def _identity(article: dict[str, Any]) -> str:
    return str(article.get("id") or article.get("slug") or id(article))


def main() -> None:
    payload = json.loads(FRONTPAGE.read_text(encoding="utf-8"))
    articles = payload.get("articles")
    if not isinstance(articles, list):
        raise SystemExit("frontpage articles array missing")

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=FRESH_HOURS)
    valid = [a for a in articles if isinstance(a, dict)]

    expired_deadlines = [a for a in valid if is_expired_today_deadline(a, now)]
    expired_deadline_ids = {_identity(a) for a in expired_deadlines}
    valid = [a for a in valid if _identity(a) not in expired_deadline_ids]

    expired_previews = [a for a in valid if is_expired_time_sensitive_preview(a, now)]
    expired_preview_ids = {_identity(a) for a in expired_previews}
    valid = [a for a in valid if _identity(a) not in expired_preview_ids]

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

    fresh_pins.sort(key=latest_update, reverse=True)
    fresh_substantive.sort(key=latest_update, reverse=True)
    recent_live.sort(key=latest_update, reverse=True)
    fresh_utility.sort(key=latest_update, reverse=True)
    stale_pins.sort(key=latest_update, reverse=True)

    ordered = fresh_pins + fresh_substantive + recent_live + fresh_utility + stale_pins

    for index, article in enumerate(ordered):
        article["frontpage_rank"] = index
        article["frontpage_priority"] = max(1, 1000 - index)
        article["slot"] = "lead" if index == 0 else "secondary-1" if index == 1 else "secondary-2" if index == 2 else ""

    payload["articles"] = ordered
    payload["count"] = len(ordered)
    payload["freshness_guard"] = {
        "fresh_hours": FRESH_HOURS,
        "fresh_editor_pins": len(fresh_pins),
        "stale_editor_pins_retained": len(stale_pins),
        "fresh_articles": len(fresh),
        "fresh_substantive_articles": len(fresh_substantive) + len(fresh_pins),
        "recent_live_updates": len(recent_live),
        "fresh_utility_articles": len(fresh_utility),
        "expired_same_day_deadlines_dropped": len(expired_deadlines),
        "expired_sports_previews_dropped": len(expired_previews),
        "stale_fallback_dropped": len(dropped_stale),
        "enforced_at": now.isoformat().replace("+00:00", "Z"),
    }
    FRONTPAGE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lead = ordered[0].get("title") if ordered else "(none)"
    print(
        f"Frontpage freshness enforced: {len(fresh_pins)} fresh pin(s), "
        f"{len(fresh_substantive)} other substantive <= {FRESH_HOURS}h, "
        f"{len(recent_live)} active live update(s), {len(fresh_utility)} utility, "
        f"{len(expired_deadlines)} expired same-day deadline story/stories dropped, "
        f"{len(expired_previews)} expired sports preview(s) dropped, "
        f"{len(stale_pins)} explicit stale pin(s), {len(dropped_stale)} stale fallback story/stories dropped. "
        f"Lead: {lead}"
    )


if __name__ == "__main__":
    main()
