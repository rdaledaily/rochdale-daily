"""Shared editorial takedown blocklist.

story_blocklist.json is the single source of truth for stories the editor
has removed. Matching an entry here means a story must never appear in
articles.json, articles/frontpage.json, or as a published article page —
including after push-race merges and after the scraper re-collects the
same story from a new source URL.

Schema (all keys optional):
  {
    "title_patterns": ["henry nowak"],   # lowercase substring match on title
    "source_urls":    ["https://..."],    # canonicalised exact match
    "slugs":          ["some-page-slug"]  # exact slug match, lowercase
  }

frontpage_pipeline.py keeps its own equivalent loader for backwards
compatibility; the semantics here are intentionally identical.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

BLOCKLIST_PATH = Path(os.getenv("STORY_BLOCKLIST_JSON", "story_blocklist.json"))

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _plain(value: Any) -> str:
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", str(value or ""))).strip()


def canonical_url(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    try:
        parts = urlsplit(text)
    except ValueError:
        return text.lower()
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower() or "https", host, path, "", ""))


def load_blocklist(path: Path | None = None) -> dict[str, list[str]]:
    target = path or BLOCKLIST_PATH
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return {
        "title_patterns": [
            str(value).lower().strip()
            for value in payload.get("title_patterns", []) if value
        ],
        "source_urls": [
            canonical_url(str(value))
            for value in payload.get("source_urls", []) if value
        ],
        "slugs": [
            str(value).lower().strip()
            for value in payload.get("slugs", []) if value
        ],
    }


def save_blocklist(blocklist: dict[str, list[str]], path: Path | None = None) -> None:
    target = path or BLOCKLIST_PATH
    payload = {
        "title_patterns": sorted(set(blocklist.get("title_patterns", []))),
        "source_urls": sorted(set(blocklist.get("source_urls", []))),
        "slugs": sorted(set(blocklist.get("slugs", []))),
    }
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def is_blocked_article(article: dict[str, Any], blocklist: dict[str, list[str]]) -> bool:
    """True when the article matches any takedown entry.

    Checks the primary source URL AND every merged source URL, so a
    multi-source cluster that absorbed a blocked source is caught too.
    """
    title = _plain(article.get("title")).lower()
    slug = str(article.get("slug") or "").lower().strip()

    if slug and slug in set(blocklist.get("slugs", [])):
        return True

    blocked_urls = set(blocklist.get("source_urls", []))
    if blocked_urls:
        candidate_urls = {canonical_url(str(article.get("source_url") or ""))}
        for url in article.get("source_urls") or []:
            candidate_urls.add(canonical_url(str(url)))
        candidate_urls.discard("")
        if candidate_urls & blocked_urls:
            return True

    return any(
        pattern and pattern in title
        for pattern in blocklist.get("title_patterns", [])
    )


def is_blocked_text(title: str, source_url: str, blocklist: dict[str, list[str]]) -> bool:
    """Candidate-stage check for the scraper, before an article record exists."""
    lowered = _plain(title).lower()
    if any(pattern and pattern in lowered for pattern in blocklist.get("title_patterns", [])):
        return True
    canonical = canonical_url(source_url)
    return bool(canonical) and canonical in set(blocklist.get("source_urls", []))
