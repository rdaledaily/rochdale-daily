#!/usr/bin/env python3
"""Keep homepage discovery metadata aligned with the crawlable Latest block.

The homepage already contains a server-rendered/static fallback between
STATIC_LATEST_START/END so crawlers and no-JavaScript readers can discover
recent journalism. This helper makes that same list machine-readable as a
schema.org ItemList and advertises the RSS feed through HTML autodiscovery.

It intentionally derives the ItemList from the rendered fallback rather than
re-selecting articles independently. That prevents structured data from
advertising a different set of stories from the links a crawler can actually
see on the page.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
SITE_BASE = "https://rochdaledaily.co.uk"
LATEST_START = "<!-- STATIC_LATEST_START -->"
LATEST_END = "<!-- STATIC_LATEST_END -->"
META_START = "<!-- LATEST_ITEMLIST_START -->"
META_END = "<!-- LATEST_ITEMLIST_END -->"
RSS_TAG = '<link rel="alternate" type="application/rss+xml" title="Rochdale Daily RSS" href="/rss.xml">'
MAX_ITEMS = 12

CARD_RE = re.compile(
    r'<a class="story-link" href="(?P<href>[^"]+)">.*?'
    r'<h3 class="card-headline">(?P<title>.*?)</h3>.*?'
    r'<time datetime="(?P<date>[^"]+)">',
    re.S,
)
TAG_RE = re.compile(r"<[^>]+>")


def clean_text(value: str) -> str:
    return " ".join(html.unescape(TAG_RE.sub(" ", value)).split())


def latest_block(text: str) -> str:
    if LATEST_START not in text or LATEST_END not in text:
        raise ValueError("Homepage static Latest markers are missing")
    return text.split(LATEST_START, 1)[1].split(LATEST_END, 1)[0]


def extract_items(text: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in CARD_RE.finditer(latest_block(text)):
        href = html.unescape(match.group("href")).strip()
        title = clean_text(match.group("title"))
        date = html.unescape(match.group("date")).strip()
        if not href.startswith("/articles/") or not title or href in seen:
            continue
        seen.add(href)
        items.append({"url": SITE_BASE + href, "title": title, "date": date})
        if len(items) >= MAX_ITEMS:
            break
    if not items:
        raise ValueError("No crawlable Latest article links were found")
    return items


def itemlist_markup(items: list[dict[str, str]]) -> str:
    payload = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": "Latest news from Rochdale Daily",
        "itemListOrder": "https://schema.org/ItemListOrderDescending",
        "numberOfItems": len(items),
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": position,
                "item": {
                    "@type": "NewsArticle",
                    "headline": item["title"],
                    "url": item["url"],
                    **({"datePublished": item["date"]} if item["date"] else {}),
                },
            }
            for position, item in enumerate(items, start=1)
        ],
    }
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f'{META_START}\n  <script type="application/ld+json" id="latest-news-itemlist">{data}</script>\n  {META_END}'


def enhance(text: str) -> str:
    items = extract_items(text)
    metadata = itemlist_markup(items)

    if META_START in text and META_END in text:
        text = re.sub(
            re.escape(META_START) + r".*?" + re.escape(META_END),
            metadata,
            text,
            count=1,
            flags=re.S,
        )
    else:
        if "</head>" not in text:
            raise ValueError("Homepage </head> not found")
        text = text.replace("</head>", f"  {metadata}\n</head>", 1)

    if RSS_TAG not in text:
        if "</head>" not in text:
            raise ValueError("Homepage </head> not found")
        text = text.replace("</head>", f"  {RSS_TAG}\n</head>", 1)
    return text


def main() -> int:
    text = INDEX.read_text(encoding="utf-8")
    updated = enhance(text)
    if updated != text:
        INDEX.write_text(updated, encoding="utf-8")
        print("Updated homepage RSS autodiscovery and Latest-news ItemList metadata.")
    else:
        print("Homepage discovery metadata already current.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
