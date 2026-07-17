"""Editor-curated events for Rochdale Daily.

Manual events live in ``manual_events.json`` — a file the pipeline ONLY ever
reads, never writes. This is deliberate: articles.json is a generated artifact
that scraper.py and frontpage_pipeline.py rewrite on every run, so anything
added there by hand is stripped out again. Events placed in manual_events.json
are injected into the feed at render time and therefore cannot be overwritten.

Each entry needs very little; the loader fills in sensible defaults and marks
the record ``manual_event`` / ``editorial_lock`` so downstream code trusts it
and never re-filters it. Minimal entry::

    {
      "title": "Rochdale Feel Good Festival 2026",
      "event_start_at": "2026-08-22T11:00:00Z",
      "event_location": "Rochdale Town Centre",
      "description": "The annual free music and arts festival returns...",
      "source_url": "https://www.rochdale.gov.uk/feelgood",
      "image_url": "assets/img/events/feel-good-festival.jpg"
    }

Only ``title`` and ``event_start_at`` are required. Events whose start date is
already in the past (by more than 12 hours) are dropped automatically.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

MANUAL_EVENTS_PATH = Path(os.getenv("MANUAL_EVENTS_JSON", "manual_events.json"))
DEFAULT_EVENT_IMAGE = ""


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", _clean(value).lower()).strip("-")
    return slug[:90] or "local-event"


def _stable_id(value: str) -> str:
    return hashlib.sha256(_clean(value).encode("utf-8")).hexdigest()[:18]


def _parse_dt(value: Any) -> datetime | None:
    text = _clean(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _content_html(entry: dict[str, Any]) -> str:
    body = entry.get("content_html")
    if isinstance(body, str) and body.strip():
        return body
    description = entry.get("description") or entry.get("excerpt") or ""
    if isinstance(description, list):
        paragraphs = [_clean(part) for part in description if _clean(part)]
    else:
        paragraphs = [_clean(part) for part in str(description).split("\n\n") if _clean(part)]
    if not paragraphs:
        paragraphs = [_clean(entry.get("title"))]
    return "".join(f"<p>{html.escape(part)}</p>" for part in paragraphs if part)


def _excerpt(entry: dict[str, Any]) -> str:
    excerpt = _clean(entry.get("excerpt"))
    if excerpt:
        return excerpt[:360]
    description = entry.get("description") or ""
    if isinstance(description, list):
        description = " ".join(str(part) for part in description)
    return _clean(description)[:360]


def _normalise(entry: dict[str, Any], now: datetime) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    # Draft/disabled entries stay in the file as an inline template but never
    # publish. Remove "draft": true (or set it false) to make an event live.
    if entry.get("draft") or entry.get("enabled") is False:
        return None
    title = _clean(entry.get("title"))
    start = _parse_dt(entry.get("event_start_at") or entry.get("start"))
    if not title or start is None:
        return None
    # Drop events that have already happened (grace window mirrors the feed).
    if start < now - timedelta(hours=12):
        return None

    slug = _slugify(entry.get("slug") or title)
    source_url = _clean(entry.get("source_url") or entry.get("url") or entry.get("ticket_url"))
    identity = source_url or slug
    published_at = _parse_dt(entry.get("published_at")) or now
    image_url = _clean(entry.get("image_url")) or DEFAULT_EVENT_IMAGE
    image_credit = _clean(entry.get("image_credit")) or "Rochdale Daily event artwork"
    location = _clean(entry.get("event_location") or entry.get("location") or "Rochdale")

    record: dict[str, Any] = {
        "id": _clean(entry.get("id")) or _stable_id(identity),
        "slug": slug,
        "story_key": f"manual-event:{slug}",
        "title": title,
        "excerpt": _excerpt(entry),
        "content_html": _content_html(entry),
        "area": _clean(entry.get("area")).lower() or "rochdale",
        "category": "events",
        "types": ["events"],
        "source_kind": "event",
        "status": "published",
        "event_start_at": _iso(start),
        "event_end_at": _iso(_parse_dt(entry.get("event_end_at"))) if _parse_dt(entry.get("event_end_at")) else "",
        "event_location": location,
        "published_at": _iso(published_at),
        "first_published_at": _iso(published_at),
        "scraped_at": _iso(now),
        "source_name": _clean(entry.get("source_name")) or "Rochdale Daily",
        "source_url": source_url,
        "source_names": [_clean(entry.get("source_name")) or "Rochdale Daily"],
        "source_urls": [source_url] if source_url else [],
        "image_url": image_url,
        "image_credit": image_credit,
        "image_credit_url": _clean(entry.get("image_credit_url")),
        "byline": _clean(entry.get("byline")) or "Rochdale Daily Newsdesk",
        # Flags that tell every downstream stage this record is editor-owned:
        # it must never be re-filtered, re-categorised, or dropped, and it is
        # allowed into the events rail regardless of its source domain.
        "manual_event": True,
        "editorial_lock": True,
    }
    return record


def load_manual_event_records(now: datetime | None = None) -> list[dict[str, Any]]:
    """Return normalised, still-current editor-curated event records."""
    reference = now or datetime.now(timezone.utc)
    if not MANUAL_EVENTS_PATH.exists():
        return []
    try:
        payload = json.loads(MANUAL_EVENTS_PATH.read_text(encoding="utf-8"))
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
