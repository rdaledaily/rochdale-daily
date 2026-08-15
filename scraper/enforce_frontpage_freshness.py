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

FRONTPAGE = Path(os.getenv("FRONTPAGE_JSON", "articles/frontpage.json"))
FRESH_HOURS = int(os.getenv("FRONTPAGE_FRESH_HOURS", "14"))

UTILITY_TITLE_PATTERNS = (
    re.compile(r"\blive (?:bus|tram|train) departures?\b", re.I),
    re.compile(r"\bcontact (?:details|information)\b", re.I),
)
UTILITY_URL_PATTERNS = (
    re.compile(r"/live-departures/", re.I),
    re.compile(r"/contact-us/[^?#]*(?:contact|details)", re.I),
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
    # Old permanent pins are not allowed. Older stories must have an explicit,
    # still-active expiry to remain on the live homepage.
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

    # No generic stale fallback. If the newsroom has only six genuinely current
    # stories, the live homepage shows six current stories rather than pretending
    # that last week's reporting is today's news.
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
        "stale_fallback_dropped": len(dropped_stale),
        "enforced_at": now.isoformat().replace("+00:00", "Z"),
    }
    FRONTPAGE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lead = ordered[0].get("title") if ordered else "(none)"
    print(
        f"Frontpage freshness enforced: {len(fresh_pins)} fresh pin(s), "
        f"{len(fresh_substantive)} other substantive <= {FRESH_HOURS}h, "
        f"{len(recent_live)} active live update(s), {len(fresh_utility)} utility, "
        f"{len(stale_pins)} explicit stale pin(s), {len(dropped_stale)} stale fallback story/stories dropped. "
        f"Lead: {lead}"
    )


if __name__ == "__main__":
    main()
