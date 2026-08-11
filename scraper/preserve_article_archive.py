#!/usr/bin/env python3
"""Preserve every published Rochdale Daily news article indefinitely.

The live scraper may legitimately keep only a working set of recent records in
``articles.json``.  That must never make older published stories disappear from
Latest News, category filters, search, or archive feeds.

This script maintains ``articles/archive.json`` as a persistent ledger of
published non-event stories and merges missing archive records back into
``articles.json``.  With ``--recover-history`` it also walks the Git history of
``articles.json`` so stories that disappeared before this ledger existed are
recovered retrospectively.

Current records always win for editable metadata, while the earliest known
publication date is retained.  Editorial takedowns in ``story_blocklist.json``
are never restored.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ARTICLES_PATH = Path("articles.json")
ARCHIVE_PATH = Path("articles/archive.json")
BLOCKLIST_PATH = Path("story_blocklist.json")

LOW_QUALITY_ROUTES = {
    "direct-crime-autopublish",
    "automatic-attributed-crime-fallback",
    "source-led-fallback",
}


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def article_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("articles"), list):
        return [item for item in payload["articles"] if isinstance(item, dict)]
    return []


def text(value: Any) -> str:
    return str(value or "").strip()


def normal(value: Any) -> str:
    return text(value).casefold()


def aliases(article: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for field in ("story_key", "id", "slug", "source_url"):
        value = normal(article.get(field))
        if value:
            values.append(f"{field}:{value}")
    title = normal(article.get("title"))
    published = text(article.get("first_published_at") or article.get("published_at"))[:10]
    if title:
        values.append(f"title-date:{title}|{published}")
    return values


def parse_time(value: Any) -> datetime | None:
    raw = text(value)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def first_publication(article: dict[str, Any]) -> datetime | None:
    return parse_time(article.get("first_published_at") or article.get("published_at"))


def last_update(article: dict[str, Any]) -> datetime | None:
    return parse_time(
        article.get("last_updated_at")
        or article.get("updated_at")
        or article.get("scraped_at")
        or article.get("published_at")
    )


def is_event(article: dict[str, Any]) -> bool:
    return (
        normal(article.get("category")) == "events"
        or normal(article.get("source_kind")) == "event"
    )


def is_published(article: dict[str, Any]) -> bool:
    return normal(article.get("status") or "published") == "published"


def is_low_quality(article: dict[str, Any]) -> bool:
    return normal(article.get("publication_route")) in LOW_QUALITY_ROUTES


def load_blocklist() -> dict[str, set[str]]:
    payload = read_json(BLOCKLIST_PATH, {})
    if not isinstance(payload, dict):
        return {"slugs": set(), "source_urls": set(), "title_patterns": set()}
    return {
        "slugs": {normal(value) for value in payload.get("slugs", []) if text(value)},
        "source_urls": {normal(value) for value in payload.get("source_urls", []) if text(value)},
        "title_patterns": {normal(value) for value in payload.get("title_patterns", []) if text(value)},
    }


def blocked(article: dict[str, Any], blocklist: dict[str, set[str]]) -> bool:
    if normal(article.get("slug")) in blocklist["slugs"]:
        return True
    if normal(article.get("source_url")) in blocklist["source_urls"]:
        return True
    title = normal(article.get("title"))
    return any(pattern and pattern in title for pattern in blocklist["title_patterns"])


def merge_records(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Merge two versions, preferring non-empty values from the newer record."""
    merged = dict(old)
    for key, value in new.items():
        if value not in (None, "", [], {}):
            merged[key] = value

    firsts = [value for value in (first_publication(old), first_publication(new)) if value]
    if firsts:
        first = min(firsts).isoformat().replace("+00:00", "Z")
        merged["first_published_at"] = first
        merged["published_at"] = first

    updates = [value for value in (last_update(old), last_update(new)) if value]
    if updates:
        merged["last_updated_at"] = max(updates).isoformat().replace("+00:00", "Z")
    return merged


class ArticleStore:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self.alias_to_key: dict[str, str] = {}
        self.sequence = 0

    def add(self, article: dict[str, Any]) -> None:
        article = dict(article)
        names = aliases(article)
        existing_keys = []
        for name in names:
            key = self.alias_to_key.get(name)
            if key and key not in existing_keys:
                existing_keys.append(key)

        if existing_keys:
            key = existing_keys[0]
            combined = self.records[key]
            for duplicate_key in existing_keys[1:]:
                combined = merge_records(combined, self.records.pop(duplicate_key))
                for alias, mapped in list(self.alias_to_key.items()):
                    if mapped == duplicate_key:
                        self.alias_to_key[alias] = key
            combined = merge_records(combined, article)
            self.records[key] = combined
        else:
            self.sequence += 1
            key = names[0] if names else f"anonymous:{self.sequence}"
            self.records[key] = article

        for name in aliases(self.records[key]):
            self.alias_to_key[name] = key

    def values(self) -> list[dict[str, Any]]:
        return list(self.records.values())


def historical_versions() -> Iterable[list[dict[str, Any]]]:
    try:
        output = subprocess.check_output(
            ["git", "log", "--format=%H", "--all", "--", str(ARTICLES_PATH)],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []

    commits = [line.strip() for line in output.splitlines() if line.strip()]
    # Process oldest to newest so later historical edits replace earlier fields.
    versions: list[list[dict[str, Any]]] = []
    seen_content: set[str] = set()
    for commit in reversed(commits):
        try:
            raw = subprocess.check_output(
                ["git", "show", f"{commit}:{ARTICLES_PATH}"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
        except (subprocess.CalledProcessError, UnicodeDecodeError):
            continue
        # Many commits point to an identical articles.json blob. Avoid reparsing it.
        signature = str(hash(raw))
        if signature in seen_content:
            continue
        seen_content.add(signature)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        items = article_list(payload)
        if items:
            versions.append(items)
    return versions


def sort_key(article: dict[str, Any]) -> float:
    value = first_publication(article) or last_update(article)
    return value.timestamp() if value else 0.0


def serialise_articles(items: list[dict[str, Any]]) -> str:
    return json.dumps(items, ensure_ascii=False, indent=2) + "\n"


def write_articles_if_changed(path: Path, items: list[dict[str, Any]]) -> bool:
    new_text = serialise_articles(items)
    try:
        old_text = path.read_text(encoding="utf-8")
        old_payload = json.loads(old_text)
        old_items = article_list(old_payload)
        if old_items == items:
            return False
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new_text, encoding="utf-8")
    return True


def write_archive_if_changed(items: list[dict[str, Any]]) -> bool:
    existing = read_json(ARCHIVE_PATH, {})
    existing_items = article_list(existing)
    if existing_items == items:
        return False
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "count": len(items),
        "articles": items,
    }
    ARCHIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ARCHIVE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--recover-history",
        action="store_true",
        help="Recover published stories from every historical articles.json revision.",
    )
    args = parser.parse_args()

    current = article_list(read_json(ARTICLES_PATH, []))
    previous_archive = article_list(read_json(ARCHIVE_PATH, {}))
    blocklist = load_blocklist()

    archive_store = ArticleStore()

    # Oldest material first; current articles are applied last and therefore win.
    if args.recover_history:
        for version in historical_versions():
            for article in version:
                if is_published(article) and not is_event(article) and not is_low_quality(article) and not blocked(article, blocklist):
                    archive_store.add(article)

    for article in previous_archive:
        if is_published(article) and not is_event(article) and not is_low_quality(article) and not blocked(article, blocklist):
            archive_store.add(article)

    for article in current:
        if is_published(article) and not is_event(article) and not is_low_quality(article) and not blocked(article, blocklist):
            archive_store.add(article)

    archive = sorted(archive_store.values(), key=sort_key, reverse=True)

    # Rebuild articles.json from the permanent news ledger plus current live
    # events. This makes every historical published story available to the
    # homepage filters and Read More immediately, without resurrecting expired
    # events or editorially removed material.
    combined_store = ArticleStore()
    for article in archive:
        combined_store.add(article)
    for article in current:
        if is_event(article) and is_published(article) and not blocked(article, blocklist):
            combined_store.add(article)
    combined = sorted(combined_store.values(), key=sort_key, reverse=True)

    archive_changed = write_archive_if_changed(archive)
    articles_changed = write_articles_if_changed(ARTICLES_PATH, combined)

    print(
        f"Permanent archive: {len(archive)} published news stories; "
        f"articles.json: {len(combined)} total records; "
        f"archive_changed={archive_changed}; articles_changed={articles_changed}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
