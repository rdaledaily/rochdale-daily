#!/usr/bin/env python3
"""Keep crawlable homepage Latest-news links in the committed HTML.

The homepage JavaScript still replaces this fallback with the live/filterable feed
for human readers. This committed fallback exists so search engines, link previews,
text browsers and readers with failed/disabled JavaScript can discover recent
journalism directly from the homepage.
"""
from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
ARTICLES = ROOT / "articles.json"
START = "<!-- STATIC_LATEST_START -->"
END = "<!-- STATIC_LATEST_END -->"
MAX_STORIES = 6


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


def eligible(row: object) -> bool:
    if not isinstance(row, dict):
        return False
    if str(row.get("status") or "published").lower() != "published":
        return False
    if row.get("requires_approval") is True:
        return False
    if not str(row.get("slug") or "").strip() or not str(row.get("title") or "").strip():
        return False
    # What's On has its own dedicated discovery surface. Keep the static Latest
    # fallback concentrated on journalism rather than ticket/event inventory.
    if str(row.get("category") or "").strip().lower() in {"event", "events", "what's on", "whats-on"}:
        return False
    published = parse_dt(row.get("first_published_at") or row.get("published_at"))
    return published <= datetime.now(timezone.utc)


def clean(value: object) -> str:
    return " ".join(str(value or "").split())


def local_card_image(value: object) -> str:
    """Return a real local article-card path, or an empty string.

    Do not invent a generic fallback here. The cards-only publishing invariant is
    responsible for assigning story images; rendering a made-up path in the
    crawlable homepage would turn an upstream image problem into a public 404.
    """
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

    if updated != text:
        INDEX.write_text(updated, encoding="utf-8")
        print(f"Updated crawlable homepage Latest fallback with {len(chosen)} stories.")
    else:
        print("Homepage static Latest fallback already current.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
