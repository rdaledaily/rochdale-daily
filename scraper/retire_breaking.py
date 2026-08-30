#!/usr/bin/env python3
"""Retire breaking entries the newsroom pipeline has caught up with.

The GMP watcher puts a short, attributed stub on the front page within a minute.
The pipeline later publishes the proper article from the same GMP post. Without
this step the paper would carry both -- the stub sitting above the real thing.

This walks the published articles, matches them to breaking entries by GMP
source URL, marks those entries superseded and records which article replaced
them. The Pages Function then 301s the stub to the canonical article instead of
rendering it, so any link already shared keeps working.

Run it after generation, in the same workflows that already regenerate the
front page:

    python scraper/retire_breaking.py

Safe to run when there is nothing to do, and safe to run twice.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
BREAKING_FILE = ROOT / "breaking.json"
ARTICLE_FILES = ("articles.json", "manual_articles.json")


def canonical_url(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    path = (parsed.path or "/").rstrip("/") or "/"
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{parsed.scheme or 'https'}://{host}{path}{query}"


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def article_rows(payload) -> list[dict]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("articles", "items", "records"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    return []


def published_index() -> dict[str, str]:
    """Map every GMP source URL we have published to its article slug."""
    index: dict[str, str] = {}
    for name in ARTICLE_FILES:
        for row in article_rows(load_json(ROOT / name, [])):
            slug = str(row.get("slug") or "").strip()
            if not slug or str(row.get("status") or "published") != "published":
                continue
            urls = [row.get("source_url")]
            extra = row.get("source_urls")
            if isinstance(extra, (list, tuple)):
                urls.extend(extra)
            for url in urls:
                key = canonical_url(str(url or ""))
                if key and key not in index:
                    index[key] = slug
    return index


def retire(breaking: dict, index: dict[str, str]) -> tuple[dict, list[tuple[str, str]]]:
    items = list(breaking.get("items") or [])
    retired: list[tuple[str, str]] = []
    for entry in items:
        if entry.get("status") not in {"live", "held"}:
            continue
        slug = index.get(canonical_url(str(entry.get("source_url") or "")))
        if not slug:
            continue
        entry["status"] = "superseded"
        entry["superseded_by"] = slug
        entry["superseded_at"] = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        retired.append((str(entry.get("slug") or ""), slug))
    breaking["items"] = items
    return breaking, retired


def main() -> int:
    if not BREAKING_FILE.exists():
        print("no breaking.json; nothing to retire")
        return 0
    breaking = load_json(BREAKING_FILE, {"items": []})
    if not breaking.get("items"):
        print("no breaking entries; nothing to retire")
        return 0

    index = published_index()
    before = json.dumps(breaking, sort_keys=True)
    breaking, retired = retire(breaking, index)
    if json.dumps(breaking, sort_keys=True) == before:
        print(f"{len(breaking['items'])} breaking entr(ies); none superseded yet")
        return 0

    temp = BREAKING_FILE.with_suffix(".json.tmp")
    temp.write_text(
        json.dumps(breaking, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temp.replace(BREAKING_FILE)
    for stub, article in retired:
        print(f"superseded {stub} -> articles/{article}.html")
    print(f"retired {len(retired)} breaking entr(ies)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
