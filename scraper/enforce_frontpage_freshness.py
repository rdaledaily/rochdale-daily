#!/usr/bin/env python3
"""Keep the Rochdale Daily homepage genuinely fresh without deleting archive material.

Frontpage selection deliberately retains a wider fallback window so the homepage is
not empty during quiet periods. The fallback must never outrank genuinely fresh
news, however, and an editor's active ``featured``/``frontpage_until`` pin must be
honoured even when category balancing has rearranged the selected set.

This post-selection guard is intentionally narrow: it does not change publication,
legal, image, word-count, source or category eligibility. It only orders records
that the existing frontpage pipeline has already approved.
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

# Routine service endpoints are useful elsewhere on the site, but should not become
# the homepage lead merely because they were scraped more recently than journalism.
# Manual/editorial records are exempt because an editor may legitimately write a
# news story about a service change that uses the same words.
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
    return until is None or until >= now


def is_utility_not_lead(article: dict[str, Any]) -> bool:
    """Identify machine-discovered service pages that should not lead the paper."""
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
    """Keep genuinely active live/breaking coverage visible even if first published earlier."""
    active = bool(
        article.get("live_story") is True
        or article.get("breaking_news") is True
        or article.get("is_ongoing") is True
    )
    return active and latest_update(article) >= cutoff and not is_utility_not_lead(article)


def main() -> None:
    payload = json.loads(FRONTPAGE.read_text(encoding="utf-8"))
    articles = payload.get("articles")
    if not isinstance(articles, list):
        raise SystemExit("frontpage articles array missing")

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=FRESH_HOURS)

    # Stable buckets preserve the existing editorial/category arrangement inside
    # each freshness class. Active editor pins are sorted by most recent update so
    # multiple simultaneous pins have deterministic behaviour.
    pins = [a for a in articles if isinstance(a, dict) and active_pin(a, now)]
    pin_ids = {str(a.get("id") or a.get("slug") or id(a)) for a in pins}

    remaining = [
        a for a in articles
        if isinstance(a, dict)
        and str(a.get("id") or a.get("slug") or id(a)) not in pin_ids
    ]
    fresh = [a for a in remaining if (first_published(a) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff]
    fresh_substantive = [a for a in fresh if not is_utility_not_lead(a)]
    fresh_utility = [a for a in fresh if is_utility_not_lead(a)]

    fresh_ids = {str(a.get("id") or a.get("slug") or id(a)) for a in fresh}
    older = [a for a in remaining if str(a.get("id") or a.get("slug") or id(a)) not in fresh_ids]
    recent_live = [a for a in older if is_recent_live_update(a, cutoff)]
    live_ids = {str(a.get("id") or a.get("slug") or id(a)) for a in recent_live}
    old = [a for a in older if str(a.get("id") or a.get("slug") or id(a)) not in live_ids]

    pins.sort(key=latest_update, reverse=True)
    recent_live.sort(key=latest_update, reverse=True)
    ordered = pins + fresh_substantive + recent_live + fresh_utility + old

    for index, article in enumerate(ordered):
        article["frontpage_rank"] = index
        article["frontpage_priority"] = max(1, 1000 - index)
        article["slot"] = "lead" if index == 0 else "secondary-1" if index == 1 else "secondary-2" if index == 2 else ""

    payload["articles"] = ordered
    payload["freshness_guard"] = {
        "fresh_hours": FRESH_HOURS,
        "active_editor_pins": len(pins),
        "fresh_articles": len(fresh),
        "fresh_substantive_articles": len(fresh_substantive),
        "recent_live_updates": len(recent_live),
        "fresh_utility_articles": len(fresh_utility),
        "fallback_articles": len(old),
        "enforced_at": now.isoformat().replace("+00:00", "Z"),
    }
    FRONTPAGE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lead = ordered[0].get("title") if ordered else "(none)"
    print(
        f"Frontpage freshness enforced: {len(pins)} active pin(s), "
        f"{len(fresh_substantive)} substantive <= {FRESH_HOURS}h, "
        f"{len(recent_live)} active live update(s), {len(fresh_utility)} utility, "
        f"{len(old)} fallback. Lead: {lead}"
    )


if __name__ == "__main__":
    main()
