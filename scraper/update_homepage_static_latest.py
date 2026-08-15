#!/usr/bin/env python3
"""Keep crawlable homepage Latest-news links in the committed HTML.

The homepage JavaScript still replaces this fallback with the live/filterable feed
for human readers. This committed fallback exists so search engines, link previews,
text browsers and readers with failed/disabled JavaScript can discover recent
journalism directly from the homepage.

The same lightweight refresh also removes any legacy inline base64 masthead logo.
The real logo already exists as a cacheable static asset, so embedding roughly
140 KB of PNG data inside the HTML makes every homepage response unnecessarily
large and prevents the browser from caching the logo independently.
"""
from __future__ import annotations

import html
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
ARTICLES = ROOT / "articles.json"
START = "<!-- STATIC_LATEST_START -->"
END = "<!-- STATIC_LATEST_END -->"
MAX_STORIES = 12
SPORT_PREVIEW_MAX_HOURS = 8
LOCAL_TZ = ZoneInfo("Europe/London")

UTILITY_TITLE_PATTERNS = (
    re.compile(r"\blive (?:bus|tram|train) departures?\b", re.I),
    re.compile(r"\bcontact (?:details|information)\b", re.I),
)
UTILITY_URL_PATTERNS = (
    re.compile(r"/live-departures/", re.I),
    re.compile(r"/contact-us/[^?#]*(?:contact|details)", re.I),
)
SPORT_PREVIEW_PATTERN = re.compile(
    r"\b(?:today|this afternoon|this evening|kick[ -]?off|fixture|faces?|match preview)\b",
    re.I,
)
TODAY_DEADLINE_PATTERN = re.compile(
    r"\b(?:until|by|before)\s+(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ampm>am|pm)\s+today\b",
    re.I,
)

INLINE_MASTHEAD_LOGO_RE = re.compile(
    r'(<img\s+class="brand-logo"\s+src=")data:image/(?:png|webp|jpeg);base64,[^"]+("[^>]*>)',
    re.I,
)
MASTHEAD_LOGO_PATH = "/assets/img/logo.png"


def externalise_inline_masthead_logo(text: str) -> str:
    """Replace a legacy inline masthead image with the cacheable static logo."""
    return INLINE_MASTHEAD_LOGO_RE.sub(
        lambda match: f'{match.group(1)}{MASTHEAD_LOGO_PATH}{match.group(2)}',
        text,
        count=1,
    )


def parse_dt(value: object) -> datetime:
    text = str(value or "").strip()
    if not text:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_utility_not_news(row: dict) -> bool:
    """Return True for obvious machine-discovered service/utility endpoints."""
    if row.get("manual_article") is True or str(row.get("source_kind") or "").lower() == "editorial":
        return False
    title = str(row.get("title") or "")
    urls = [str(row.get("source_url") or "")]
    raw_urls = row.get("source_urls") or []
    if isinstance(raw_urls, list):
        urls.extend(str(url) for url in raw_urls)
    return any(pattern.search(title) for pattern in UTILITY_TITLE_PATTERNS) or any(
        pattern.search(url) for url in urls for pattern in UTILITY_URL_PATTERNS
    )


def is_expired_today_deadline(row: dict, now: datetime | None = None) -> bool:
    """Keep expired automated same-day offers/notices out of crawler-facing Latest."""
    if row.get("manual_article") is True or str(row.get("source_kind") or "").lower() == "editorial":
        return False
    text = " ".join(str(row.get(key) or "") for key in ("title", "excerpt", "summary"))
    match = TODAY_DEADLINE_PATTERN.search(text)
    if not match:
        return False
    hour = int(match.group("hour"))
    minute = int(match.group("minute") or 0)
    if not 1 <= hour <= 12 or not 0 <= minute <= 59:
        return False
    if match.group("ampm").lower() == "pm" and hour != 12:
        hour += 12
    elif match.group("ampm").lower() == "am" and hour == 12:
        hour = 0
    now = now or datetime.now(timezone.utc)
    local_now = now.astimezone(LOCAL_TZ)
    deadline = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return local_now > deadline


def is_expired_time_sensitive_preview(row: dict, now: datetime | None = None) -> bool:
    """Keep stale pre-match sports previews out of crawler-facing Latest links."""
    if row.get("manual_article") is True or str(row.get("source_kind") or "").lower() == "editorial":
        return False
    if str(row.get("category") or "").strip().lower() not in {"sport", "sports"}:
        return False

    text = " ".join(str(row.get(key) or "") for key in ("title", "excerpt", "summary"))
    if not SPORT_PREVIEW_PATTERN.search(text):
        return False

    now = now or datetime.now(timezone.utc)
    event_start = parse_dt(row.get("event_start_at"))
    if event_start.year > 1970:
        return now >= event_start + timedelta(hours=3)

    published = parse_dt(row.get("first_published_at") or row.get("published_at"))
    if published.year <= 1970:
        return False
    return now >= published + timedelta(hours=SPORT_PREVIEW_MAX_HOURS)


def eligible(row: object) -> bool:
    if not isinstance(row, dict):
        return False
    if str(row.get("status") or "published").lower() != "published":
        return False
    if row.get("requires_approval") is True:
        return False
    if not str(row.get("slug") or "").strip() or not str(row.get("title") or "").strip():
        return False
    if str(row.get("category") or "").strip().lower() in {"event", "events", "what's on", "whats-on"}:
        return False
    if is_utility_not_news(row):
        return False
    if is_expired_today_deadline(row):
        return False
    if is_expired_time_sensitive_preview(row):
        return False
    published = parse_dt(row.get("first_published_at") or row.get("published_at"))
    return published <= datetime.now(timezone.utc)


def clean(value: object) -> str:
    return " ".join(str(value or "").split())


def local_card_image(value: object) -> str:
    image = clean(value).lstrip("/")
    if not image.startswith("assets/img/cards/"):
        return ""
    path = ROOT / image
    if not path.is_file():
        return ""
    return image


def card(row: dict) -> str:
    slug = html.escape(clean(row.get("slug")).strip("/"), quote=True)
    title = html.escape(clean(row.get("title")), quote=False)
    excerpt = html.escape(clean(row.get("excerpt") or row.get("summary")), quote=False)
    if len(excerpt) > 220:
        excerpt = excerpt[:217].rstrip() + "..."
    category = clean(row.get("category") or "News").replace("-", " ").title()
    area = clean(row.get("area") or "Rochdale").replace("-", " ").title()
    image = local_card_image(row.get("image_url") or row.get("img"))
    published = parse_dt(row.get("first_published_at") or row.get("published_at"))
    date_label = published.strftime("%d %b %Y") if published.year > 1970 else "Latest"
    datetime_attr = published.isoformat().replace("+00:00", "Z") if published.year > 1970 else ""
    href = f"/articles/{slug}.html"
    image_markup = (
        f'<div class="story-image-wrap"><img src="/{html.escape(image, quote=True)}" alt="" loading="lazy" decoding="async"></div>\n'
        if image
        else ""
    )
    date_markup = (
        f'<time datetime="{html.escape(datetime_attr, quote=True)}">{html.escape(date_label)}</time>'
        if datetime_attr
        else html.escape(date_label)
    )
    return (
        '              <article class="news-card static-latest-card">\n'
        f'                <a class="story-link" href="{href}">\n'
        f'                  {image_markup}'
        f'                  <span class="story-kicker">{html.escape(category)}</span>\n'
        f'                  <h3 class="card-headline">{title}</h3>\n'
        f'                  <p class="card-summary">{excerpt}</p>\n'
        f'                  <div class="story-meta">{html.escape(area)} · {date_markup}</div>\n'
        '                </a>\n'
        '              </article>'
    )


def main() -> int:
    rows = json.loads(ARTICLES.read_text(encoding="utf-8"))
    candidates = [r for r in rows if eligible(r)]
    candidates.sort(
        key=lambda r: parse_dt(r.get("first_published_at") or r.get("published_at")),
        reverse=True,
    )
    chosen = []
    seen = set()
    for row in candidates:
        slug = clean(row.get("slug"))
        if slug in seen:
            continue
        seen.add(slug)
        chosen.append(row)
        if len(chosen) >= MAX_STORIES:
            break

    if not chosen:
        raise SystemExit("No eligible published stories available for homepage static Latest fallback")

    block = START + "\n" + "\n".join(card(r) for r in chosen) + "\n            " + END
    text = INDEX.read_text(encoding="utf-8")

    if START in text and END in text:
        updated = re.sub(
            re.escape(START) + r".*?" + re.escape(END),
            block,
            text,
            count=1,
            flags=re.S,
        )
    else:
        needle = '<div class="news-grid" id="news-grid"></div>'
        replacement = '<div class="news-grid" id="news-grid">\n            ' + block + '\n            </div>'
        if needle not in text:
            raise SystemExit("Homepage news-grid placeholder not found; refusing a broad HTML rewrite")
        updated = text.replace(needle, replacement, 1)

    updated = externalise_inline_masthead_logo(updated)

    if updated != text:
        INDEX.write_text(updated, encoding="utf-8")
        print(f"Updated crawlable homepage Latest fallback with {len(chosen)} stories and normalised masthead asset.")
    else:
        print("Homepage static Latest fallback and masthead asset already current.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
