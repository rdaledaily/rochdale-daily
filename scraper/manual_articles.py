"""Editor-written articles, read from manual_articles.json at the repo root.

This is the one route into the paper that does not depend on a source existing:
an editorial, a follow-up, a correction, a piece written from a phone call or
from being in the room. Nothing here is scraped, rewritten or categorised by
machine - what is written is what publishes.

    [
      {
        "title": "Why the Touchstones delay matters",
        "body": "First paragraph.\\n\\nSecond paragraph.",
        "category": "politics",
        "area": "rochdale"
      }
    ]

Only ``title`` and ``body`` are required. Everything else is optional:
``category`` (defaults to news), ``area`` (defaults to rochdale), ``excerpt``,
``byline``, ``published_at``, ``image_url``, ``image_credit``, ``source_url``,
``source_name``, ``slug``.

An entry with ``"draft": true`` is never published, which is how the templates
in the file stay in it without appearing on the site.

Unlike manual_events.json there is no date requirement and no expiry: an article
does not stop being true, so nothing here is dropped for being old. It leaves
the feed the same way any other article does, when it ages out of retention.
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

# Matches the pipeline's own set, so an editor cannot file a piece under a
# category the rest of the site does not render.
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
    """Blank-line-separated plain text becomes paragraphs.

    Escaped rather than passed through, so a stray angle bracket in typed copy
    cannot break the page or inject markup.
    """
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
    # Draft entries stay in the file as an inline template but never publish.
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

    record: dict[str, Any] = {
        "id": _clean(entry.get("id")) or _stable_id(source_url or slug),
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
        "image_url": _clean(entry.get("image_url")),
        "image_credit": _clean(entry.get("image_credit")) or "Rochdale Daily",
        "image_credit_url": _clean(entry.get("image_credit_url")),
        "byline": _clean(entry.get("byline")) or "Rochdale Daily Newsdesk",
        # An editor-written piece is never re-categorised, re-filtered or
        # rewritten. It carries the same lock manual events use, so no later
        # stage can quietly change or drop it.
        "manual_article": True,
        "editorial_lock": True,
        "publication_route": "editorial",
        "rewrite_quality_checked": True,
    }

    # Crime carries the standing legal note unless one is supplied.
    if category == "crime":
        record["police_matter"] = True
        record["legal_disclaimer"] = _clean(entry.get("legal_disclaimer")) or (
            "No finding of guilt should be inferred from an arrest, allegation "
            "or charge. Anyone accused is presumed innocent unless and until "
            "convicted."
        )
    if entry.get("legal_disclaimer"):
        record["legal_disclaimer"] = _clean(entry.get("legal_disclaimer"))
    if entry.get("right_to_reply"):
        record["right_to_reply"] = _clean(entry.get("right_to_reply"))

    return record


def load_manual_article_records(now: datetime | None = None) -> list[dict[str, Any]]:
    """Return normalised editor-written article records."""
    reference = now or datetime.now(timezone.utc)
    if not MANUAL_ARTICLES_PATH.exists():
        return []
    try:
        payload = json.loads(MANUAL_ARTICLES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for entry in payload:
        record = _normalise(entry, reference)
        if record is None or record["id"] in seen_ids:
            continue
        seen_ids.add(record["id"])
        records.append(record)
    return records
