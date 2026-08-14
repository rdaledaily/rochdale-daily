#!/usr/bin/env python3
"""Generate a Google News sitemap for recently published Rochdale Daily stories.

Google News sitemaps should contain only articles published in the last two days.
This generator is deliberately deterministic: it uses the original published_at
value and emits no build timestamp, avoiding unnecessary repository churn.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
ARTICLES_PATH = ROOT / "articles.json"
OUTPUT_PATH = ROOT / "news-sitemap.xml"
SITE_URL = "https://rochdaledaily.co.uk"
PUBLICATION_NAME = "Rochdale Daily"
LANGUAGE = "en"
MAX_NEWS_URLS = 1000
NEWS_WINDOW = timedelta(days=2)

SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
NEWS_NS = "http://www.google.com/schemas/sitemap-news/0.9"
ET.register_namespace("", SITEMAP_NS)
ET.register_namespace("news", NEWS_NS)


def parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_w3c(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def eligible_articles(rows: list[dict], now: datetime) -> list[tuple[datetime, dict]]:
    cutoff = now - NEWS_WINDOW
    selected: dict[str, tuple[datetime, dict]] = {}

    for article in rows:
        if not isinstance(article, dict):
            continue
        if str(article.get("status", "published")).lower() not in {"", "published"}:
            continue
        if article.get("hidden") is True or article.get("noindex") is True:
            continue

        slug = str(article.get("slug") or "").strip().strip("/")
        title = str(article.get("title") or "").strip()
        published = parse_datetime(article.get("published_at"))
        if not slug or not title or published is None:
            continue
        if published < cutoff or published > now + timedelta(minutes=5):
            continue

        # One canonical entry per slug, preferring the newest original publication
        # timestamp if malformed duplicate rows ever reach the feed.
        previous = selected.get(slug)
        if previous is None or published > previous[0]:
            selected[slug] = (published, article)

    return sorted(selected.values(), key=lambda item: item[0], reverse=True)[:MAX_NEWS_URLS]


def build_sitemap(rows: list[dict], now: datetime | None = None) -> ET.ElementTree:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    root = ET.Element(ET.QName(SITEMAP_NS, "urlset"))

    for published, article in eligible_articles(rows, now):
        slug = str(article["slug"]).strip().strip("/")
        title = str(article["title"]).strip()

        url_el = ET.SubElement(root, ET.QName(SITEMAP_NS, "url"))
        ET.SubElement(url_el, ET.QName(SITEMAP_NS, "loc")).text = f"{SITE_URL}/articles/{slug}.html"

        news_el = ET.SubElement(url_el, ET.QName(NEWS_NS, "news"))
        publication_el = ET.SubElement(news_el, ET.QName(NEWS_NS, "publication"))
        ET.SubElement(publication_el, ET.QName(NEWS_NS, "name")).text = PUBLICATION_NAME
        ET.SubElement(publication_el, ET.QName(NEWS_NS, "language")).text = LANGUAGE
        ET.SubElement(news_el, ET.QName(NEWS_NS, "publication_date")).text = format_w3c(published)
        ET.SubElement(news_el, ET.QName(NEWS_NS, "title")).text = title

    return ET.ElementTree(root)


def main() -> int:
    try:
        rows = json.loads(ARTICLES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Unable to read {ARTICLES_PATH}: {exc}")
    if not isinstance(rows, list):
        raise SystemExit("articles.json must contain a JSON array")

    tree = build_sitemap(rows)
    ET.indent(tree, space="  ")
    tree.write(OUTPUT_PATH, encoding="utf-8", xml_declaration=True)
    print(f"Wrote {OUTPUT_PATH.name} with {len(eligible_articles(rows, datetime.now(timezone.utc)))} recent article URLs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
