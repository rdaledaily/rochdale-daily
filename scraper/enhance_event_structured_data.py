#!/usr/bin/env python3
"""Add Google-friendly Event JSON-LD to eligible What's On article pages.

Rochdale Daily event records are rendered through the same article-page template
as journalism, which means they already carry NewsArticle metadata but do not
explicitly describe the underlying event to search engines.  This deployment
enhancer adds a second, bounded Event JSON-LD block only when the record has the
three properties Google requires for event eligibility: a name, start date and
physical location.

The transformation is deliberately conservative:
* journalism is never touched;
* event records missing a start date or location are skipped rather than
  emitting incomplete structured data;
* no ticket price, organiser or performer is invented;
* local event times are emitted with the Europe/London UTC offset;
* repeat execution replaces the existing Rochdale Daily Event block instead of
  duplicating it.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import html
import json
import re
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SITE_BASE = "https://rochdaledaily.co.uk"
EVENT_SCRIPT_ID = "rd-event-jsonld"
# Match the script plus only its immediately preceding horizontal whitespace.
# The first insertion may land after an existing </title> on the same line, so
# anchoring the matcher to the start of a line fails to recognise our own block
# on the second pass and duplicates it. Consuming only spaces/tabs before the
# script also preserves the exact surrounding newline layout when replacing it.
EVENT_SCRIPT_RE = re.compile(
    rf"[ \t]*<script\s+id=\"{EVENT_SCRIPT_ID}\"\s+type=\"application/ld\+json\">.*?</script>",
    re.S,
)
LONDON = ZoneInfo("Europe/London")


def load_articles(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("articles"), list):
        return [row for row in payload["articles"] if isinstance(row, dict)]
    return []


def is_event(article: dict[str, Any]) -> bool:
    return (
        str(article.get("source_kind") or "").casefold() == "event"
        or str(article.get("category") or "").casefold() == "events"
        or "events" in {str(item).casefold() for item in (article.get("types") or [])}
    )


def local_iso(value: Any) -> str:
    """Return an ISO-8601 value expressed in Europe/London where possible."""
    text = str(value or "").strip()
    if not text:
        return ""
    # datetime.fromisoformat() accepts YYYY-MM-DD and silently converts it to
    # midnight. Preserve a genuine date-only event as date-only instead: adding
    # 00:00 would invent a time that the source did not provide.
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LONDON)
    return parsed.astimezone(LONDON).isoformat(timespec="seconds")


def event_status(article: dict[str, Any]) -> str:
    raw = str(article.get("event_status") or "").strip().casefold()
    mapping = {
        "cancelled": "https://schema.org/EventCancelled",
        "canceled": "https://schema.org/EventCancelled",
        "postponed": "https://schema.org/EventPostponed",
        "rescheduled": "https://schema.org/EventRescheduled",
        "scheduled": "https://schema.org/EventScheduled",
    }
    return mapping.get(raw, "https://schema.org/EventScheduled")


def plain_description(article: dict[str, Any]) -> str:
    value = str(article.get("excerpt") or article.get("summary") or "").strip()
    value = html.unescape(re.sub(r"<[^>]+>", " ", value))
    return re.sub(r"\s+", " ", value).strip()[:500]


def event_payload(article: dict[str, Any]) -> dict[str, Any] | None:
    title = re.sub(r"\s+", " ", str(article.get("title") or "")).strip()
    slug = str(article.get("slug") or "").strip().strip("/")
    start = local_iso(article.get("event_start_at"))
    location = re.sub(r"\s+", " ", str(article.get("event_location") or "")).strip()
    if not title or not slug or not start or not location:
        return None

    canonical = f"{SITE_BASE}/articles/{slug}.html"
    payload: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Event",
        "@id": canonical + "#event",
        "name": title,
        "startDate": start,
        "eventStatus": event_status(article),
        "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
        "location": {
            "@type": "Place",
            "name": location.split(",", 1)[0].strip() or location,
            "address": {
                "@type": "PostalAddress",
                "name": location,
                "addressCountry": "GB",
            },
        },
        "url": canonical,
    }

    end = local_iso(article.get("event_end_at"))
    if end:
        payload["endDate"] = end

    description = plain_description(article)
    if description:
        payload["description"] = description

    image_path = str(article.get("image_url") or article.get("img") or "").strip()
    if image_path.startswith("assets/img/cards/"):
        payload["image"] = [f"{SITE_BASE}/{image_path}"]

    # The source URL is useful as a booking/info destination, but it is not
    # automatically an Offer: some event sources are council or organiser info
    # pages rather than ticket shops. Do not invent commerce metadata.
    return payload


def enhance_page(page: Path, article: dict[str, Any]) -> bool:
    payload = event_payload(article)
    if payload is None or not page.exists():
        return False

    original = page.read_text(encoding="utf-8")
    marker = "</head>"
    if marker not in original:
        return False

    block = (
        f'  <script id="{EVENT_SCRIPT_ID}" type="application/ld+json">'
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + "</script>"
    )

    if EVENT_SCRIPT_RE.search(original):
        updated = EVENT_SCRIPT_RE.sub(block, original, count=1)
    else:
        updated = original.replace(marker, block + "\n" + marker, 1)

    if updated == original:
        return False
    page.write_text(updated, encoding="utf-8")
    return True


def enhance_events(articles_path: Path, pages_dir: Path) -> tuple[int, int]:
    eligible = 0
    changed = 0
    for article in load_articles(articles_path):
        if not is_event(article) or str(article.get("status") or "published") != "published":
            continue
        payload = event_payload(article)
        if payload is None:
            continue
        eligible += 1
        page = pages_dir / f"{article.get('slug')}.html"
        if enhance_page(page, article):
            changed += 1
    return eligible, changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--articles", default="articles.json")
    parser.add_argument("--pages-dir", default="articles")
    args = parser.parse_args()

    eligible, changed = enhance_events(Path(args.articles), Path(args.pages_dir))
    print(f"Event structured data: {eligible} eligible event page(s); {changed} page(s) updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
