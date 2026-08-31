#!/usr/bin/env python3
"""Guarantee fresh editor-written stories are present on the homepage feed.

Manual articles are an explicit newsroom decision. They must not disappear merely
because automated category/source balancing filled the frontpage first. This guard
runs after the normal freshness/source/live passes and only restores *fresh* manual
news records that are otherwise eligible for the homepage.

The existing lead story is preserved unless the frontpage is empty. If adding the
manual records would exceed the configured target, lower-ranked automated records
are removed first. Manual stories are never dropped to satisfy the numeric target.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

FRONTPAGE = Path(os.getenv("FRONTPAGE_JSON", "articles/frontpage.json"))
ARTICLES = Path(os.getenv("ARTICLES_JSON", "articles.json"))
FRESH_HOURS = int(os.getenv("FRONTPAGE_FRESH_HOURS", "14"))
TARGET = int(os.getenv("FRONTPAGE_TARGET_ARTICLES", "30"))


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


def first_published(article: dict[str, Any]) -> datetime | None:
    return parse_dt(article.get("first_published_at") or article.get("published_at"))


def latest_update(article: dict[str, Any]) -> datetime:
    return (
        parse_dt(article.get("last_updated_at"))
        or parse_dt(article.get("published_at"))
        or parse_dt(article.get("scraped_at"))
        or datetime.min.replace(tzinfo=timezone.utc)
    )


def identity(article: dict[str, Any]) -> str:
    slug = str(article.get("slug") or "").strip().lower()
    if slug:
        return "slug:" + slug
    article_id = str(article.get("id") or "").strip()
    return "id:" + article_id if article_id else ""


def is_manual(article: dict[str, Any]) -> bool:
    return bool(
        article.get("manual_article") is True
        or str(article.get("source_kind") or "").strip().lower() == "editorial"
    )


def active_pin(article: dict[str, Any], now: datetime) -> bool:
    if article.get("featured") is not True:
        return False
    until = parse_dt(article.get("frontpage_until"))
    return bool(until and until >= now)


def eligible_manual(article: Any, now: datetime, cutoff: datetime) -> bool:
    if not isinstance(article, dict) or not is_manual(article):
        return False
    if str(article.get("status") or "published").lower() != "published":
        return False
    if article.get("exclude_from_frontpage") is True:
        return False
    if str(article.get("source_kind") or "").lower() == "event":
        return False
    if str(article.get("category") or "").lower() == "events":
        return False
    published = first_published(article)
    return bool((published and published >= cutoff) or active_pin(article, now))


def main() -> int:
    payload = read_json(FRONTPAGE, {})
    rows = payload.get("articles") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise SystemExit("frontpage articles array missing")

    reservoir = read_json(ARTICLES, [])
    if not isinstance(reservoir, list):
        raise SystemExit("articles.json must contain a JSON list")

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=FRESH_HOURS)
    candidates = [row for row in reservoir if eligible_manual(row, now, cutoff)]
    candidates.sort(key=lambda row: (active_pin(row, now), latest_update(row)), reverse=True)

    existing = [row for row in rows if isinstance(row, dict)]
    existing_ids = {identity(row) for row in existing if identity(row)}
    missing = [row for row in candidates if identity(row) and identity(row) not in existing_ids]

    if existing:
        lead = existing[0]
        lead_id = identity(lead)
        ordered = [lead]
        inserted = {lead_id} if lead_id else set()
    else:
        ordered = []
        inserted: set[str] = set()

    # Put restored manual stories high enough on the page to be genuinely
    # discoverable, while leaving the already-selected lead untouched.
    for row in missing:
        key = identity(row)
        if key and key not in inserted:
            ordered.append(row)
            inserted.add(key)

    for row in existing:
        key = identity(row)
        if key and key in inserted:
            continue
        ordered.append(row)
        if key:
            inserted.add(key)

    protected = {identity(row) for row in candidates if identity(row)}
    if existing and identity(existing[0]):
        protected.add(identity(existing[0]))

    # Prefer the configured size, but never solve an overflow by deleting an
    # editor-written fresh story. If protected rows alone exceed the target,
    # allow the frontpage to be larger rather than silently dropping editorial.
    if TARGET > 0 and len(ordered) > TARGET:
        index = len(ordered) - 1
        while len(ordered) > TARGET and index >= 0:
            if identity(ordered[index]) not in protected:
                ordered.pop(index)
            index -= 1

    for index, article in enumerate(ordered):
        article["frontpage_rank"] = index
        article["frontpage_priority"] = max(1, 1000 - index)
        article["slot"] = "lead" if index == 0 else "secondary-1" if index == 1 else "secondary-2" if index == 2 else ""

    payload["articles"] = ordered
    payload["count"] = len(ordered)
    payload["manual_frontpage_guard"] = {
        "fresh_hours": FRESH_HOURS,
        "eligible_manual": len(candidates),
        "restored_manual": len(missing),
        "protected_manual": len(protected),
        "enforced_at": now.isoformat().replace("+00:00", "Z"),
    }
    FRONTPAGE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"Manual frontpage guard: {len(candidates)} eligible; "
        f"{len(missing)} restored; {len(ordered)} final homepage stories."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
