#!/usr/bin/env python3
"""Fail publication if an enabled manual article has silently disappeared.

This is a release invariant, not a style test. Every enabled manual source record
must exist in the canonical article feed. Every fresh manual news record must also
be present in the frontpage feed, have a generated article page and resolve to a
real canonical cards image. A broken manual publish therefore stops before Pages
can deploy an incomplete newsroom snapshot.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

MANUAL_JSON = Path("manual_articles.json")
MANUAL_DIR = Path("manual_articles.d")
ARTICLES = Path("articles.json")
FRONTPAGE = Path("articles/frontpage.json")
CARDS_PREFIX = "assets/img/cards/"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
FRESH_HOURS = int(os.getenv("FRONTPAGE_FRESH_HOURS", "14"))


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def slugify(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")[:80]


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


def source_entries() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    payload = read_json(MANUAL_JSON, [])
    if isinstance(payload, dict):
        rows.append(payload)
    elif isinstance(payload, list):
        rows.extend(item for item in payload if isinstance(item, dict))

    if MANUAL_DIR.is_dir():
        for path in sorted(MANUAL_DIR.rglob("*.json")):
            payload = read_json(path, None)
            if isinstance(payload, dict):
                rows.append(payload)
            elif isinstance(payload, list):
                rows.extend(item for item in payload if isinstance(item, dict))
    return [row for row in rows if not row.get("draft") and row.get("enabled") is not False]


def canonical_source_slug(entry: dict[str, Any]) -> str:
    return slugify(entry.get("slug") or entry.get("title"))


def article_slug(article: dict[str, Any]) -> str:
    return slugify(article.get("slug") or article.get("title"))


def first_published(article: dict[str, Any]) -> datetime | None:
    return parse_dt(article.get("first_published_at") or article.get("published_at"))


def is_fresh_manual(article: dict[str, Any], cutoff: datetime, now: datetime) -> bool:
    if str(article.get("status") or "published").lower() != "published":
        return False
    if not (article.get("manual_article") is True or str(article.get("source_kind") or "").lower() == "editorial"):
        return False
    if article.get("exclude_from_frontpage") is True:
        return False
    if str(article.get("source_kind") or "").lower() == "event" or str(article.get("category") or "").lower() == "events":
        return False
    published = first_published(article)
    if published and published >= cutoff:
        return True
    if article.get("featured") is True:
        until = parse_dt(article.get("frontpage_until"))
        return bool(until and until >= now)
    return False


def valid_cards_image(article: dict[str, Any]) -> bool:
    value = str(article.get("image_url") or article.get("img") or "").strip().replace("\\", "/").lstrip("/")
    if not value.startswith(CARDS_PREFIX):
        return False
    path = Path(value)
    try:
        return path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES and path.stat().st_size > 4096
    except OSError:
        return False


def main() -> int:
    source = source_entries()
    articles = read_json(ARTICLES, [])
    frontpage_payload = read_json(FRONTPAGE, {})
    frontpage = frontpage_payload.get("articles") if isinstance(frontpage_payload, dict) else None

    if not isinstance(articles, list):
        raise SystemExit("articles.json must contain a JSON list")
    if not isinstance(frontpage, list):
        raise SystemExit("frontpage articles array missing")

    feed_by_slug = {
        article_slug(row): row
        for row in articles
        if isinstance(row, dict) and article_slug(row)
    }
    source_slugs = {canonical_source_slug(row) for row in source if canonical_source_slug(row)}
    missing_feed = sorted(slug for slug in source_slugs if slug not in feed_by_slug)

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=FRESH_HOURS)
    fresh = [row for row in articles if isinstance(row, dict) and is_fresh_manual(row, cutoff, now)]
    frontpage_slugs = {
        article_slug(row)
        for row in frontpage
        if isinstance(row, dict) and article_slug(row)
    }

    missing_frontpage: list[str] = []
    missing_page: list[str] = []
    bad_image: list[str] = []
    for article in fresh:
        slug = article_slug(article)
        if slug not in frontpage_slugs:
            missing_frontpage.append(slug)
        if not (Path("articles") / f"{slug}.html").is_file():
            missing_page.append(slug)
        if not valid_cards_image(article):
            bad_image.append(slug)

    errors: list[str] = []
    if missing_feed:
        errors.append("enabled manual source missing from articles.json: " + ", ".join(missing_feed))
    if missing_frontpage:
        errors.append("fresh manual article missing from frontpage: " + ", ".join(sorted(set(missing_frontpage))))
    if missing_page:
        errors.append("fresh manual article page missing: " + ", ".join(sorted(set(missing_page))))
    if bad_image:
        errors.append("fresh manual article lacks valid canonical card image: " + ", ".join(sorted(set(bad_image))))

    if errors:
        print("Manual publication invariant FAILED:")
        for error in errors:
            print("- " + error)
        return 1

    print(
        f"Manual publication invariant passed: {len(source_slugs)} enabled source record(s); "
        f"{len(fresh)} fresh manual frontpage record(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
