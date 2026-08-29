#!/usr/bin/env python3
"""Generate a Google News sitemap for recently published Rochdale Daily stories.

Google News sitemaps should contain only articles published in the last two days.
This generator is deliberately deterministic: it uses the original publication
value and emits no build timestamp, avoiding unnecessary repository churn.

The live archive can occasionally contain two URLs for the same story while a
manual article is replacing a scraped version. Google News should never be asked
to choose between duplicate headlines, so this generator collapses exact
normalised-headline duplicates and prefers the editorial/manual record.
"""
from __future__ import annotations
import json
import re
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

# Public-service pages can be useful to readers and remain in the normal site
# index, but a live-departure board or departmental contact-detail page is not
# journalism merely because the discovery crawler found it recently. Keeping
# these out of Google News protects the publication's topical quality signal.
UTILITY_TITLE_PATTERNS = (
    re.compile(r"\blive (?:bus|tram|train) departures?\b", re.I),
    re.compile(r"\bcontact (?:details|information)\b", re.I),
)
UTILITY_URL_PATTERNS = (
    re.compile(r"/live-departures/", re.I),
    re.compile(r"/contact-us/[^?#]*(?:contact|details)", re.I),
)

def parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip(): return None
    raw = value.strip()
    if raw.endswith("Z"): raw = raw[:-1] + "+00:00"
    try: parsed = datetime.fromisoformat(raw)
    except ValueError: return None
    if parsed.tzinfo is None: parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)

def format_w3c(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def title_fingerprint(value: object) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()
    text = re.sub(r"\s+", " ", text)
    return text if len(text) >= 24 else ""

def editorial_priority(article: dict) -> int:
    return int(article.get("manual_article") is True or str(article.get("source_kind") or "").lower() == "editorial")

def is_utility_not_news(article: dict) -> bool:
    if article.get("manual_article") is True or str(article.get("source_kind") or "").lower() == "editorial":
        return False
    title = str(article.get("title") or "")
    urls = [str(article.get("source_url") or "")]
    raw_urls = article.get("source_urls") or []
    if isinstance(raw_urls, list): urls.extend(str(url) for url in raw_urls)
    return any(p.search(title) for p in UTILITY_TITLE_PATTERNS) or any(p.search(url) for url in urls for p in UTILITY_URL_PATTERNS)

def article_page_exists(slug: str) -> bool:
    """True when the story has a page a reader could actually open."""
    if not slug:
        return False
    return (ROOT / "articles" / f"{slug}.html").is_file() or (
        ROOT / "articles" / slug / "index.html"
    ).is_file()


def eligible_articles(rows: list[dict], now: datetime) -> list[tuple[datetime, dict]]:
    cutoff = now - NEWS_WINDOW
    by_slug: dict[str, tuple[datetime, dict]] = {}
    for article in rows:
        if not isinstance(article, dict): continue
        if str(article.get("status", "published")).lower() not in {"", "published"}: continue
        if article.get("hidden") is True or article.get("noindex") is True: continue
        if str(article.get("source_kind") or "").lower() in {"event", "listing"}: continue
        if is_utility_not_news(article): continue
        slug = str(article.get("slug") or "").strip().strip("/")
        title = str(article.get("title") or "").strip()
        published = parse_datetime(article.get("first_published_at") or article.get("published_at"))
        if not slug or not title or published is None: continue
        if published < cutoff or published > now + timedelta(minutes=5): continue
        previous = by_slug.get(slug)
        if previous is None or published > previous[0]: by_slug[slug] = (published, article)
    by_headline: dict[str, tuple[datetime, dict]] = {}
    headline_free: list[tuple[datetime, dict]] = []
    for item in by_slug.values():
        published, article = item
        fingerprint = title_fingerprint(article.get("title"))
        if not fingerprint:
            headline_free.append(item); continue
        previous = by_headline.get(fingerprint)
        if previous is None:
            by_headline[fingerprint] = item; continue
        previous_published, previous_article = previous
        if (editorial_priority(article), published) > (editorial_priority(previous_article), previous_published):
            by_headline[fingerprint] = item
    selected = list(by_headline.values()) + headline_free
    return sorted(selected, key=lambda item: item[0], reverse=True)[:MAX_NEWS_URLS]

def build_sitemap(rows: list[dict], now: datetime | None = None) -> ET.ElementTree:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    root = ET.Element(ET.QName(SITEMAP_NS, "urlset"))
    for published, article in eligible_articles(rows, now):
        slug, title = str(article["slug"]).strip().strip("/"), str(article["title"]).strip()
        url_el = ET.SubElement(root, ET.QName(SITEMAP_NS, "url"))
        ET.SubElement(url_el, ET.QName(SITEMAP_NS, "loc")).text = f"{SITE_URL}/articles/{slug}.html"
        news_el = ET.SubElement(url_el, ET.QName(NEWS_NS, "news"))
        publication_el = ET.SubElement(news_el, ET.QName(NEWS_NS, "publication"))
        ET.SubElement(publication_el, ET.QName(NEWS_NS, "name")).text = PUBLICATION_NAME
        ET.SubElement(publication_el, ET.QName(NEWS_NS, "language")).text = LANGUAGE
        ET.SubElement(news_el, ET.QName(NEWS_NS, "publication_date")).text = format_w3c(published)
        ET.SubElement(news_el, ET.QName(NEWS_NS, "title")).text = title
    return ET.ElementTree(root)

def article_page_exists(slug: object) -> bool:
    """True when the story has a page a reader could actually open.

    A feed record can outlive its page when a headline rewrite changes the slug.
    On 29 August two of the ten URLs in the news sitemap were 404s for exactly
    that reason, and Google News was being handed both. The page on disk is the
    authority for what may be syndicated.
    """
    name = str(slug or "").strip().strip("/")
    if not name:
        return False
    return (ROOT / "articles" / f"{name}.html").is_file() or (
        ROOT / "articles" / name / "index.html"
    ).is_file()


def main() -> int:
    try: rows = json.loads(ARTICLES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc: raise SystemExit(f"Unable to read {ARTICLES_PATH}: {exc}")
    if not isinstance(rows, list): raise SystemExit("articles.json must contain a JSON array")
    dropped = [r for r in rows if isinstance(r, dict) and not article_page_exists(r.get("slug"))]
    rows = [r for r in rows if isinstance(r, dict) and article_page_exists(r.get("slug"))]
    for row in dropped:
        print(f"skipped {row.get('slug')}: no article page on disk")
    now = datetime.now(timezone.utc)
    selected = eligible_articles(rows, now)
    tree = build_sitemap(rows, now); ET.indent(tree, space="  ")
    tree.write(OUTPUT_PATH, encoding="utf-8", xml_declaration=True)
    print(f"Wrote {OUTPUT_PATH.name} with {len(selected)} recent news article URLs")
    return 0

if __name__ == "__main__": raise SystemExit(main())
