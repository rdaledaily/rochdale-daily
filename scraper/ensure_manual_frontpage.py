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
SPONSORED_FLOOR = 9
# A restored story older than this is no longer breaking: it is put back on the
# page below the top three, not above fresher news. Matches the newsroom health
# check, which fails a run when fresh news exists but none is in the top three.
TOP_STORY_FRESH_HOURS = int(os.getenv("SCRAPER_HEALTH_TOP_FRESH_HOURS", "6"))
TOP_STORY_SLOTS = 3


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


def demote_sponsored(rows: list[dict[str, Any]], floor: int = SPONSORED_FLOOR) -> list[dict[str, Any]]:
    """Hold paid-for advertisement features below the top-story positions.

    The homepage builds its lead, top stories and latest panel from the first
    nine entries. A sponsored piece is an editor-published manual article, so
    without this it is restored directly under the lead. It stays in the feed,
    in its original order, from position ten onwards. The same rule is applied
    at request time in functions/articles/frontpage.json.js, which is the
    order readers actually receive.
    """
    top: list[dict[str, Any]] = []
    held: list[dict[str, Any]] = []
    rest: list[dict[str, Any]] = []
    for row in rows:
        if len(top) < floor:
            (held if row.get("sponsored") is True else top).append(row)
        else:
            rest.append(row)
    return top + held + rest


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
    # discoverable, while leaving the already-selected lead untouched. Only a
    # story first published in the last few hours goes directly under the lead.
    # An older one that was crowded off the page is restored below the top
    # three, so it cannot push fresh news out of the top-story positions.
    top_cutoff = now - timedelta(hours=TOP_STORY_FRESH_HOURS)
    restored_new: list[dict[str, Any]] = []
    restored_older: list[dict[str, Any]] = []
    for row in missing:
        key = identity(row)
        if not key or key in inserted:
            continue
        published = first_published(row)
        is_new = bool(published and published >= top_cutoff) or active_pin(row, now)
        (restored_new if is_new else restored_older).append(row)
        inserted.add(key)

    ordered.extend(restored_new)
    remaining = []
    for row in existing:
        key = identity(row)
        if key and key in inserted:
            continue
        remaining.append(row)
        if key:
            inserted.add(key)
    keep_top = max(0, TOP_STORY_SLOTS - len([r for r in ordered if r.get("sponsored") is not True]))
    ordered.extend(remaining[:keep_top])
    ordered.extend(restored_older)
    ordered.extend(remaining[keep_top:])

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

    ordered = demote_sponsored(ordered)

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
