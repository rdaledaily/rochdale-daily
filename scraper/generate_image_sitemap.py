#!/usr/bin/env python3
"""Generate an image sitemap for canonical Rochdale Daily article-card images.

Google can discover ordinary <img> elements on article pages, but a dedicated
image sitemap gives the crawler an explicit page-to-image relationship and is
particularly useful while the site is still building crawl/index coverage.
Only published articles with a real local card image are emitted. This also
reinforces the newsroom invariant that canonical article images live under
assets/img/cards/ rather than depending on remote third-party URLs.
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
ARTICLES = ROOT / "articles.json"
OUTPUT = ROOT / "image-sitemap.xml"
SITE_BASE = "https://rochdaledaily.co.uk"
CARD_PREFIX = "assets/img/cards/"


def clean(value: object) -> str:
    return " ".join(str(value or "").split())


def eligible(row: object) -> tuple[str, str] | None:
    if not isinstance(row, dict):
        return None
    if str(row.get("status") or "published").lower() != "published":
        return None
    if row.get("requires_approval") is True:
        return None

    slug = clean(row.get("slug")).strip("/")
    image = clean(row.get("image_url") or row.get("img")).lstrip("/")
    if not slug or not image.startswith(CARD_PREFIX):
        return None
    if not (ROOT / image).is_file():
        return None
    return slug, image


def main() -> int:
    rows = json.loads(ARTICLES.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise SystemExit("articles.json must contain a JSON array")

    seen: set[str] = set()
    entries: list[str] = []
    for row in rows:
        item = eligible(row)
        if not item:
            continue
        slug, image = item
        if slug in seen:
            continue
        seen.add(slug)
        page_url = f"{SITE_BASE}/articles/{quote(slug)}.html"
        image_url = f"{SITE_BASE}/{quote(image, safe='/')}"
        title = str(row.get("title") or "").strip()[:200]
        caption = str(row.get("image_alt") or title).strip()[:200]
        entries.append(
            "  <url>\n"
            f"    <loc>{escape(page_url)}</loc>\n"
            "    <image:image>\n"
            f"      <image:loc>{escape(image_url)}</image:loc>\n"
            + (f"      <image:title>{escape(title)}</image:title>\n" if title else "")
            + (f"      <image:caption>{escape(caption)}</image:caption>\n" if caption else "")
            + "    </image:image>\n"
            "  </url>"
        )

    if not entries:
        raise SystemExit("No published articles with valid local card images; refusing empty image sitemap")

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        'xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">\n'
        + "\n".join(entries)
        + "\n</urlset>\n"
    )
    OUTPUT.write_text(xml, encoding="utf-8")

    # Fail the publishing run if a future edit produces malformed XML rather
    # than committing a sitemap that crawlers cannot consume.
    ET.parse(OUTPUT)
    print(f"Generated image sitemap with {len(entries)} article image URL(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
