#!/usr/bin/env python3
"""Generate a standards-compliant RSS 2.0 feed from published Rochdale Daily stories.

The feed is intentionally built from the same canonical articles.json archive as
article pages and the homepage. It gives readers, feed apps and news aggregators
a stable repeat-visit channel without relying on social platforms or JavaScript.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
ARTICLES = ROOT / "articles.json"
OUTPUT = ROOT / "rss.xml"
SITE = "https://rochdaledaily.co.uk"
MAX_ITEMS = 50


def clean(value: object) -> str:
    return " ".join(str(value or "").split())


def parse_dt(value: object) -> datetime:
    text = clean(value)
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
    if not clean(row.get("slug")) or not clean(row.get("title")):
        return False
    published = parse_dt(row.get("first_published_at") or row.get("published_at"))
    return published <= datetime.now(timezone.utc)


def xml_text(value: object) -> str:
    return escape(clean(value), {'"': "&quot;", "'": "&apos;"})


def item_xml(row: dict) -> str:
    slug = clean(row.get("slug")).strip("/")
    url = f"{SITE}/articles/{slug}.html"
    published = parse_dt(row.get("first_published_at") or row.get("published_at"))
    pub_date = format_datetime(published) if published.year > 1970 else ""
    category = clean(row.get("category") or "News").replace("-", " ").title()
    description = clean(row.get("excerpt") or row.get("summary"))
    image = clean(row.get("image_url") or row.get("img")).lstrip("/")
    enclosure = ""
    if image.startswith("assets/img/cards/") and (ROOT / image).is_file():
        enclosure = f"\n      <media:content url=\"{SITE}/{xml_text(image)}\" medium=\"image\" />"
    return (
        "    <item>\n"
        f"      <title>{xml_text(row.get('title'))}</title>\n"
        f"      <link>{url}</link>\n"
        f"      <guid isPermaLink=\"true\">{url}</guid>\n"
        + (f"      <pubDate>{pub_date}</pubDate>\n" if pub_date else "")
        + f"      <category>{xml_text(category)}</category>\n"
        + f"      <description>{xml_text(description)}</description>"
        + enclosure
        + "\n    </item>"
    )


def main() -> int:
    rows = json.loads(ARTICLES.read_text(encoding="utf-8"))
    candidates = [row for row in rows if eligible(row)]
    candidates.sort(
        key=lambda row: parse_dt(row.get("first_published_at") or row.get("published_at")),
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
        if len(chosen) >= MAX_ITEMS:
            break
    if not chosen:
        raise SystemExit("No eligible published stories available for RSS feed")

    latest = parse_dt(chosen[0].get("last_updated_at") or chosen[0].get("first_published_at") or chosen[0].get("published_at"))
    last_build = format_datetime(latest if latest.year > 1970 else datetime.now(timezone.utc))
    items = "\n".join(item_xml(row) for row in chosen)
    payload = f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:media="http://search.yahoo.com/mrss/">
  <channel>
    <title>Rochdale Daily</title>
    <link>{SITE}/</link>
    <description>Independent local news, public-service information and reporting from Rochdale borough.</description>
    <language>en-gb</language>
    <lastBuildDate>{last_build}</lastBuildDate>
    <atom:link href="{SITE}/rss.xml" rel="self" type="application/rss+xml" />
{items}
  </channel>
</rss>
'''
    OUTPUT.write_text(payload, encoding="utf-8")
    print(f"Wrote RSS feed with {len(chosen)} published stories.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
