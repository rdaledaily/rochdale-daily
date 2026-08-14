"""Editor-written articles for Rochdale Daily.

Legacy stories remain in manual_articles.json. New stories can be added safely as
individual JSON files under manual_articles.d/. The loader reads both sources,
normalises them identically and deduplicates by article id.

Manual articles are editorially locked by default. An individual entry may set
``allow_scrape_merge`` to true to act as a one-time editorial seed: it is injected
until it has reached articles.json, then subsequent runs leave the live, unlocked
record in the normal story-merging pipeline so verified scraped updates can enrich
or replace its details. If the live record disappears, the seed is injected again.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MANUAL_ARTICLES_PATH = Path("manual_articles.json")
MANUAL_ARTICLES_DIR = Path("manual_articles.d")
ARTICLES_FEED_PATH = Path("articles.json")

VALID_CATEGORIES = {
    "news", "crime", "politics", "traffic", "transport", "sport", "business",
    "health", "education", "environment", "community", "events",
}


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")[:80]


def _stable_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:18]


def _parse_dt(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _content_html(entry: dict[str, Any]) -> str:
    body = str(entry.get("body") or entry.get("content") or entry.get("description") or "")
    paragraphs = [
        html.escape(re.sub(r"\s+", " ", part).strip())
        for part in re.split(r"\n\s*\n", body)
        if part.strip()
    ]
    return "".join(f"<p>{part}</p>" for part in paragraphs)


def _excerpt(entry: dict[str, Any]) -> str:
    explicit = _clean(entry.get("excerpt") or entry.get("summary"))
    if explicit:
        return explicit[:360]
    body = str(entry.get("body") or entry.get("content") or entry.get("description") or "")
    first = next((part.strip() for part in re.split(r"\n\s*\n", body) if part.strip()), "")
    return _clean(first)[:360]


def _normalise(entry: dict[str, Any], now: datetime) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    if entry.get("draft") or entry.get("enabled") is False:
        return None

    title = _clean(entry.get("title"))
    content_html = _content_html(entry)
    if not title or not content_html:
        return None

    slug = _slugify(entry.get("slug") or title)
    source_url = _clean(entry.get("source_url") or entry.get("url"))
    published_at = _parse_dt(entry.get("published_at")) or now

    category = _clean(entry.get("category")).lower() or "news"
    if category not in VALID_CATEGORIES:
        category = "news"

    source_name = _clean(entry.get("source_name")) or "Rochdale Daily"
    image_url = _clean(entry.get("image_url") or entry.get("img"))
    allow_scrape_merge = entry.get("allow_scrape_merge") is True

    record: dict[str, Any] = {
        "id": _clean(entry.get("id")) or _stable_id(slug or source_url),
        "slug": slug,
        "story_key": f"manual-article:{slug}",
        "title": title,
        "excerpt": _excerpt(entry),
        "content_html": content_html,
        "area": _clean(entry.get("area")).lower() or "rochdale",
        "category": category,
        "types": [category],
        "source_kind": "editorial",
        "status": "published",
        "published_at": _iso(published_at),
        "first_published_at": _iso(published_at),
        "last_updated_at": _iso(_parse_dt(entry.get("last_updated_at")) or published_at),
        "scraped_at": _iso(now),
        "source_name": source_name,
        "source_url": source_url,
        "source_names": [source_name],
        "source_urls": [source_url] if source_url else [],
        "image_url": image_url,
        "image_credit": _clean(entry.get("image_credit")) or "Rochdale Daily",
        "image_credit_url": _clean(entry.get("image_credit_url")),
        "byline": _clean(entry.get("byline")) or "Rochdale Daily Newsdesk",
        "manual_article": True,
        "editorial_lock": not allow_scrape_merge,
        "allow_scrape_merge": allow_scrape_merge,
        "publication_route": "editorial-live-seed" if allow_scrape_merge else "editorial",
        "rewrite_quality_checked": True,
    }

    if category == "crime":
        record["police_matter"] = True
        record["legal_disclaimer"] = _clean(entry.get("legal_disclaimer")) or (
            "No finding of guilt should be inferred from an arrest, allegation or charge. "
            "Anyone accused is presumed innocent unless and until convicted."
        )
    if entry.get("legal_disclaimer"):
        record["legal_disclaimer"] = _clean(entry.get("legal_disclaimer"))
    if entry.get("right_to_reply"):
        record["right_to_reply"] = _clean(entry.get("right_to_reply"))

    raw_corrections = entry.get("corrections")
    if isinstance(raw_corrections, list):
        cleaned: list[dict[str, str]] = []
        for item in raw_corrections:
            if isinstance(item, str):
                text = _clean(item)
                if text:
                    cleaned.append({"date": "", "note": text})
            elif isinstance(item, dict):
                text = _clean(item.get("note") or item.get("text"))
                if text:
                    cleaned.append({"date": _clean(item.get("date")), "note": text})
        if cleaned:
            record["corrections"] = cleaned

    if entry.get("featured") is True:
        record["featured"] = True
    if entry.get("frontpage_until"):
        record["frontpage_until"] = _clean(entry.get("frontpage_until"))
    if entry.get("exclude_from_frontpage") is True:
        record["exclude_from_frontpage"] = True

    return record


def _read_payload(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list):
        return [entry for entry in payload if isinstance(entry, dict)]
    return []


def _live_feed_identity() -> tuple[set[str], set[str]]:
    """Return ids/slugs already present in the generated live article feed."""
    ids: set[str] = set()
    slugs: set[str] = set()
    for item in _read_payload(ARTICLES_FEED_PATH):
        item_id = _clean(item.get("id"))
        slug = _slugify(item.get("slug") or "")
        if item_id:
            ids.add(item_id)
        if slug:
            slugs.add(slug)
    return ids, slugs


def load_manual_article_records(now: datetime | None = None) -> list[dict[str, Any]]:
    """Return normalised editor-written article records from legacy + per-story files."""
    reference = now or datetime.now(timezone.utc)
    entries: list[dict[str, Any]] = []

    if MANUAL_ARTICLES_PATH.exists():
        entries.extend(_read_payload(MANUAL_ARTICLES_PATH))

    if MANUAL_ARTICLES_DIR.exists():
        for path in sorted(MANUAL_ARTICLES_DIR.rglob("*.json")):
            entries.extend(_read_payload(path))

    live_ids, live_slugs = _live_feed_identity()
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for entry in entries:
        record = _normalise(entry, reference)
        if record is None or record["id"] in seen_ids:
            continue
        if record.get("allow_scrape_merge") and (
            record["id"] in live_ids or record["slug"] in live_slugs
        ):
            # The editorial seed has already reached articles.json. Do not
            # re-inject the pristine manual copy: the unlocked live record now
            # belongs to the ordinary scraper/dedupe pipeline and can absorb
            # verified updates while retaining its canonical id/slug.
            continue
        seen_ids.add(record["id"])
        records.append(record)
    return records
