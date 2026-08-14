"""Editor-written articles for Rochdale Daily.

Legacy stories remain in manual_articles.json. New stories can be added safely as
individual JSON files under manual_articles.d/. The loader reads both sources,
normalises them identically and deduplicates by article id.

Manual articles remain editorially authoritative, but they are not duplicate
islands. Before injection, each manual article is compared with non-manual records
already present in articles.json. When the normal story matcher is confident that
a scraped record is the same underlying story, the manual article keeps its
headline, body, category and canonical slug while absorbing the scraped source
attribution and live identity. The final injector can then replace the scraped
record instead of publishing a second article.

An individual entry may set ``allow_scrape_merge`` to true to act as a one-time
editorial seed. Once that exact live record has reached articles.json, subsequent
runs leave it unlocked in the ordinary story-merging pipeline so verified scraped
updates can refresh its details.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from story_identity import same_story

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


def _live_feed_records() -> list[dict[str, Any]]:
    return _read_payload(ARTICLES_FEED_PATH)


def _unique_strings(*values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        items = value if isinstance(value, list) else [value]
        for item in items:
            text = _clean(item)
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
    return result


def _absorb_scraped_match(
    manual: dict[str, Any], scraped: dict[str, Any]
) -> dict[str, Any]:
    """Keep editorial copy canonical while absorbing a same-story scrape.

    The scraped id is deliberately adopted because frontpage_pipeline's final
    manual injection removes existing records by id/slug/source URL. Adopting
    the scrape id therefore turns what used to be two records into one without
    sacrificing the editor-selected canonical slug.
    """
    merged = dict(manual)
    canonical_manual_id = _clean(manual.get("id"))
    scraped_id = _clean(scraped.get("id"))
    if scraped_id:
        merged["manual_canonical_id"] = canonical_manual_id
        merged["id"] = scraped_id

    merged["source_names"] = _unique_strings(
        manual.get("source_names"),
        manual.get("source_name"),
        scraped.get("source_names"),
        scraped.get("source_name"),
    )
    merged["source_urls"] = _unique_strings(
        manual.get("source_urls"),
        manual.get("source_url"),
        scraped.get("source_urls"),
        scraped.get("source_url"),
    )
    merged["source_count"] = len(merged["source_urls"])

    update_candidates = [
        _parse_dt(manual.get("last_updated_at")),
        _parse_dt(scraped.get("last_updated_at")),
        _parse_dt(scraped.get("scraped_at")),
        _parse_dt(scraped.get("published_at")),
    ]
    updates = [value for value in update_candidates if value is not None]
    if updates:
        merged["last_updated_at"] = _iso(max(updates))

    if merged["source_count"] > 1 or scraped.get("is_ongoing"):
        merged["is_ongoing"] = True
        merged["ongoing_label"] = "ONGOING"
        merged["update_count"] = max(
            merged["source_count"],
            int(scraped.get("update_count") or 1),
        )

    merged["merged_scrape_duplicate"] = True
    return merged


def load_manual_article_records(now: datetime | None = None) -> list[dict[str, Any]]:
    """Return manual records, folded into matching scraped stories when found."""
    reference = now or datetime.now(timezone.utc)
    entries: list[dict[str, Any]] = []

    if MANUAL_ARTICLES_PATH.exists():
        entries.extend(_read_payload(MANUAL_ARTICLES_PATH))

    if MANUAL_ARTICLES_DIR.exists():
        for path in sorted(MANUAL_ARTICLES_DIR.rglob("*.json")):
            entries.extend(_read_payload(path))

    live = _live_feed_records()
    live_ids = {_clean(item.get("id")) for item in live if _clean(item.get("id"))}
    live_slugs = {_slugify(item.get("slug") or "") for item in live if item.get("slug")}

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for entry in entries:
        record = _normalise(entry, reference)
        if record is None:
            continue

        # A live-seed article stops being re-injected only when its own exact
        # canonical identity has already reached articles.json. A different
        # scraped version of the same story must still be folded into it below.
        if record.get("allow_scrape_merge") and (
            record["id"] in live_ids or record["slug"] in live_slugs
        ):
            continue

        # Exclude already-injected manual/editorial records from matching. We
        # only want an independent scrape to trigger the fold-in behaviour.
        scraped_matches = [
            item for item in live
            if not item.get("manual_article")
            and str(item.get("source_kind") or "").lower() != "editorial"
            and same_story(record, item)
        ]

        if scraped_matches:
            # Automatic records have already been deduplicated before manual
            # injection, so normally there is one. If more survive, absorb the
            # most recently updated first; adopting its id is enough for the
            # final injector to remove that canonical scraped record.
            scraped_matches.sort(
                key=lambda item: (
                    _parse_dt(item.get("last_updated_at"))
                    or _parse_dt(item.get("scraped_at"))
                    or _parse_dt(item.get("published_at"))
                    or datetime.min.replace(tzinfo=timezone.utc)
                ),
                reverse=True,
            )
            record = _absorb_scraped_match(record, scraped_matches[0])
            for extra in scraped_matches[1:]:
                # Extra sources are retained for attribution even though only
                # one scraped identity is needed to collapse the live record.
                record["source_names"] = _unique_strings(
                    record.get("source_names"), extra.get("source_names"), extra.get("source_name")
                )
                record["source_urls"] = _unique_strings(
                    record.get("source_urls"), extra.get("source_urls"), extra.get("source_url")
                )
                record["source_count"] = len(record["source_urls"])

        if record["id"] in seen_ids:
            continue
        seen_ids.add(record["id"])
        records.append(record)
    return records
