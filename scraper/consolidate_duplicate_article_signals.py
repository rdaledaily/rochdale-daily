#!/usr/bin/env python3
"""Consolidate SEO signals for near-duplicate automated articles without deleting URLs.

The newsroom occasionally rewrites the same underlying development into a new
slug (for example, repeated transport alerts with slightly different titles).
Deleting those URLs is risky because they may already have links or shares. This
module instead chooses one canonical article and:

* points near-duplicate article pages at that canonical URL;
* removes duplicate URLs from sitemap.xml;
* leaves every article page accessible to readers.

The detector is intentionally conservative: articles must share a category,
have strongly similar titles, and come from the same normalised source family.
Manual/editorial journalism always wins over automated copies; otherwise the
oldest first publication keeps the canonical URL so accumulated search equity is
not needlessly moved.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
import argparse
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
ARTICLES_PATH = ROOT / "articles.json"
SITEMAP_PATH = ROOT / "sitemap.xml"
SITE_BASE = "https://rochdaledaily.co.uk/articles/"
_WORD_RE = re.compile(r"[a-z0-9]{3,}")
_STOP = {
    "the", "and", "for", "from", "with", "due", "until", "after", "before",
    "rochdale", "update", "latest", "live", "today", "this", "that", "into",
}


@dataclass(frozen=True)
class Duplicate:
    duplicate_slug: str
    canonical_slug: str


def _dt(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return datetime.max.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _manual(article: dict[str, Any]) -> bool:
    route = str(article.get("publication_route") or "").lower()
    source_kind = str(article.get("source_kind") or "").lower()
    byline = str(article.get("byline") or "").lower()
    return bool(
        source_kind in {"manual", "editorial"}
        or route in {"manual", "editorial", "manual-editorial"}
        or "editor" in byline
    )


def _source_family(article: dict[str, Any]) -> str:
    raw = str(article.get("source_url") or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = re.sub(r"/+", "/", parsed.path or "/").rstrip("/") or "/"
    # Query strings and fragments on live alert pages often describe the same
    # source family while varying between scraper passes.
    return f"{host}{path}"


def _tokens(title: Any) -> set[str]:
    return {
        word for word in _WORD_RE.findall(str(title or "").lower())
        if word not in _STOP
    }


def _title_similarity(a: Any, b: Any) -> float:
    left = re.sub(r"\s+", " ", str(a or "").lower()).strip()
    right = re.sub(r"\s+", " ", str(b or "").lower()).strip()
    if not left or not right:
        return 0.0
    lt, rt = _tokens(left), _tokens(right)
    jaccard = len(lt & rt) / len(lt | rt) if lt and rt else 0.0
    sequence = SequenceMatcher(None, left, right).ratio()
    return max(jaccard, sequence)


def _eligible(article: Any) -> bool:
    return bool(
        isinstance(article, dict)
        and str(article.get("status") or "published").lower() == "published"
        and str(article.get("slug") or "").strip()
        and str(article.get("title") or "").strip()
        and str(article.get("category") or "").strip()
        and _source_family(article)
    )


def find_duplicates(articles: Any) -> list[Duplicate]:
    if not isinstance(articles, list):
        return []
    rows = [article for article in articles if _eligible(article)]
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for article in rows:
        key = (str(article.get("category") or "").lower(), _source_family(article))
        groups.setdefault(key, []).append(article)

    duplicates: list[Duplicate] = []
    for group in groups.values():
        if len(group) < 2:
            continue
        ordered = sorted(
            group,
            key=lambda article: (
                0 if _manual(article) else 1,
                _dt(article.get("first_published_at") or article.get("published_at")),
                str(article.get("slug") or ""),
            ),
        )
        claimed: set[str] = set()
        for i, candidate in enumerate(ordered):
            candidate_slug = str(candidate.get("slug") or "")
            if candidate_slug in claimed:
                continue
            for other in ordered[i + 1 :]:
                other_slug = str(other.get("slug") or "")
                if other_slug in claimed:
                    continue
                if _title_similarity(candidate.get("title"), other.get("title")) < 0.78:
                    continue
                # Manual/editorial stories can absorb automated duplicates, but
                # two separately written manual stories are never auto-collapsed.
                if _manual(candidate) and _manual(other):
                    continue
                duplicates.append(Duplicate(other_slug, candidate_slug))
                claimed.add(other_slug)
    return duplicates


def _canonical_url(slug: str) -> str:
    return f"{SITE_BASE}{slug}.html"


def _rewrite_article_page(path: Path, canonical_slug: str) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    canonical = _canonical_url(canonical_slug)
    updated, count = re.subn(
        r'<link\s+rel=["\']canonical["\']\s+href=["\'][^"\']+["\']\s*/?>',
        f'<link rel="canonical" href="{canonical}">',
        text,
        count=1,
        flags=re.I,
    )
    if not count:
        return False
    if updated != text:
        path.write_text(updated, encoding="utf-8")
        return True
    return False


def _filter_sitemap(path: Path, duplicate_slugs: set[str]) -> int:
    if not path.exists() or not duplicate_slugs:
        return 0
    ET.register_namespace("", "http://www.sitemaps.org/schemas/sitemap/0.9")
    tree = ET.parse(path)
    root = tree.getroot()
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    removed = 0
    for url in list(root.findall("s:url", ns)):
        loc = url.find("s:loc", ns)
        value = (loc.text or "").strip() if loc is not None else ""
        if any(value.rstrip("/").endswith(f"/articles/{slug}.html") for slug in duplicate_slugs):
            root.remove(url)
            removed += 1
    if removed:
        tree.write(path, encoding="utf-8", xml_declaration=True)
    return removed


def apply(articles_path: Path = ARTICLES_PATH, sitemap_path: Path = SITEMAP_PATH, root: Path = ROOT) -> tuple[int, int]:
    try:
        payload = json.loads(articles_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0, 0
    duplicates = find_duplicates(payload)
    pages_changed = 0
    for item in duplicates:
        page = root / "articles" / f"{item.duplicate_slug}.html"
        pages_changed += int(_rewrite_article_page(page, item.canonical_slug))
    removed = _filter_sitemap(sitemap_path, {item.duplicate_slug for item in duplicates})
    return pages_changed, removed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--articles", type=Path, default=ARTICLES_PATH)
    parser.add_argument("--sitemap", type=Path, default=SITEMAP_PATH)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    pages, sitemap_rows = apply(args.articles, args.sitemap, args.root)
    print(f"Duplicate SEO consolidation: {pages} article canonical(s) updated; {sitemap_rows} sitemap URL(s) removed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
