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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

FRONTPAGE = Path(os.getenv("FRONTPAGE_JSON", "articles/frontpage.json"))
FRESH_HOURS = int(os.getenv("FRONTPAGE_FRESH_HOURS", "14"))


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
    old = [a for a in remaining if a not in fresh]

    pins.sort(key=latest_update, reverse=True)
    ordered = pins + fresh + old

    for index, article in enumerate(ordered):
        article["frontpage_rank"] = index
        article["frontpage_priority"] = max(1, 1000 - index)
        article["slot"] = "lead" if index == 0 else "secondary-1" if index == 1 else "secondary-2" if index == 2 else ""

    payload["articles"] = ordered
    payload["freshness_guard"] = {
        "fresh_hours": FRESH_HOURS,
        "active_editor_pins": len(pins),
        "fresh_articles": len(fresh),
        "fallback_articles": len(old),
        "enforced_at": now.isoformat().replace("+00:00", "Z"),
    }
    FRONTPAGE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lead = ordered[0].get("title") if ordered else "(none)"
    print(
        f"Frontpage freshness enforced: {len(pins)} active pin(s), "
        f"{len(fresh)} <= {FRESH_HOURS}h, {len(old)} fallback. Lead: {lead}"
    )


if __name__ == "__main__":
    main()
