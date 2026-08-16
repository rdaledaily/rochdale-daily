"""Keep sitemap lastmod timestamps honest at the final deployment boundary.

Scraper polling timestamps are operational metadata, not article modifications.
For automated stories, use the original publication time unless there is a
real timestamped live update or correction. Editorial/manual stories may use
last_updated_at because that field is controlled by the newsdesk.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

ARTICLES_JSON = Path("articles.json")
SITEMAP = Path("sitemap.xml")
NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
ET.register_namespace("", NS)


def parse_iso(value: object) -> datetime:
    text = str(value or "").strip()
    if not text:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def meaningful_lastmod(article: dict) -> str:
    published = str(article.get("first_published_at") or article.get("published_at") or "").strip()
    candidates = [published]
    editorial = bool(article.get("manual_article") or article.get("editorial_lock") or article.get("source_kind") == "editorial")
    if editorial:
        candidates.append(str(article.get("last_updated_at") or "").strip())

    for correction in article.get("corrections") or []:
        if isinstance(correction, dict):
            candidates.append(str(correction.get("date") or "").strip())

    # A timestamped live-update entry represents an actual published
    # development. A fresh scraped_at/ingested_at value does not.
    for key in ("live_updates", "updates", "timeline"):
        items = article.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or item.get("body") or item.get("update") or item.get("title") or "").strip()
            if not text:
                continue
            for time_key in ("timestamp", "published_at", "updated_at", "time", "date"):
                value = str(item.get(time_key) or "").strip()
                if value:
                    candidates.append(value)
                    break

    valid = [value for value in candidates if parse_iso(value) != datetime.min.replace(tzinfo=timezone.utc)]
    if not valid:
        return ""
    return max(valid, key=parse_iso)


def main() -> None:
    if not ARTICLES_JSON.exists() or not SITEMAP.exists():
        raise SystemExit("articles.json and sitemap.xml are required")
    payload = json.loads(ARTICLES_JSON.read_text(encoding="utf-8"))
    articles = payload if isinstance(payload, list) else payload.get("articles", [])
    by_slug = {str(a.get("slug")): a for a in articles if isinstance(a, dict) and a.get("slug")}

    tree = ET.parse(SITEMAP)
    root = tree.getroot()
    changed = 0
    for node in root.findall(f"{{{NS}}}url"):
        loc = node.find(f"{{{NS}}}loc")
        lastmod = node.find(f"{{{NS}}}lastmod")
        if loc is None or lastmod is None or not loc.text:
            continue
        match = re.search(r"/articles/([^/]+)\.html$", loc.text)
        if not match:
            continue
        article = by_slug.get(match.group(1))
        if not article:
            continue
        honest = meaningful_lastmod(article)
        if honest and lastmod.text != honest:
            lastmod.text = honest
            changed += 1

    tree.write(SITEMAP, encoding="utf-8", xml_declaration=True)
    # Reparse so malformed output can never be uploaded silently.
    ET.parse(SITEMAP)
    print(f"Sitemap lastmod audit complete: corrected {changed} article URL(s).")


if __name__ == "__main__":
    main()
