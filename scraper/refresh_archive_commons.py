#!/usr/bin/env python3
"""Retrospectively improve automated article images with stricter Commons matches.

Only automatically managed images are eligible. Manually selected, curated-library
and original-source images are preserved. Existing strict Wikimedia matches are
replaced only when a materially better story-related match is found.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from related_commons_images import candidate_score, clean, download, find_candidate

AUTO_STATUSES = {
    "generated-placeholder",
    "area-category-card",
    "wikimedia-commons",
    "wikimedia-commons-related",
}
AUTO_METHODS = {
    "wikimedia-commons",
    "wikimedia-commons-related",
    "area-category-card",
    "generated-placeholder",
}
PROTECTED_STATUSES = {
    "source-image-cached",
    "curated-library-photo",
    "manual",
    "manual-image",
    "editor-selected",
}


def slug_for(article: dict[str, Any]) -> str:
    raw = clean(article.get("slug") or article.get("id") or article.get("title"))
    return re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")[:80] or "story"


def is_placeholder(article: dict[str, Any]) -> bool:
    image = clean(article.get("image_url")).lower()
    reuse = clean(article.get("source_image_reuse_status")).lower()
    status = clean(article.get("image_status")).lower()
    return (
        not image
        or "placeholder" in image
        or "area-category-card" in image
        or status in {"generated-placeholder", "area-category-card"}
        or reuse == "category-fallback"
    )


def is_commons_managed(article: dict[str, Any]) -> bool:
    status = clean(article.get("image_status")).lower()
    method = clean(article.get("image_backfill_method")).lower()
    credit = clean(article.get("image_credit")).lower()
    reuse = clean(article.get("source_image_reuse_status")).lower()
    return (
        status in {"wikimedia-commons", "wikimedia-commons-related"}
        or method in {"wikimedia-commons", "wikimedia-commons-related"}
        or reuse == "wikimedia-commons-reusable"
        or "wikimedia commons" in credit
    )


def is_protected(article: dict[str, Any]) -> bool:
    status = clean(article.get("image_status")).lower()
    method = clean(article.get("image_backfill_method")).lower()
    if status in PROTECTED_STATUSES:
        return True
    if method and method not in AUTO_METHODS and not is_placeholder(article):
        # Publisher/source extraction and any explicitly named custom method win.
        return True
    image = clean(article.get("image_url")).replace("\\", "/")
    if image.startswith("assets/img/cards/") and not is_placeholder(article):
        return True
    return False


def current_match_score(article: dict[str, Any]) -> int:
    stored = article.get("image_match_score")
    try:
        if stored is not None:
            return int(stored)
    except (TypeError, ValueError):
        pass
    title = clean(article.get("image_match_title"))
    if title:
        return candidate_score(article, title)
    return -1


def save_candidate(article: dict[str, Any], candidate: dict[str, str], output_dir: Path, score: int) -> bool:
    fetched = download(candidate["url"])
    if not fetched:
        return False
    payload, ext = fetched
    digest = hashlib.sha256(payload).hexdigest()[:12]
    path = output_dir / f"{slug_for(article)}-commons-{digest}{ext}"
    if not path.exists():
        path.write_bytes(payload)
    article["image_url"] = path.as_posix()
    article["image_credit"] = candidate["credit"]
    article["image_credit_url"] = candidate["credit_url"]
    article["source_image_candidate_url"] = candidate["url"]
    article["image_status"] = "wikimedia-commons-related"
    article["image_backfill_method"] = "wikimedia-commons-related"
    article["source_image_reuse_status"] = "wikimedia-commons-reusable"
    article["image_match_title"] = candidate["title"]
    article["image_match_score"] = score
    article.pop("image_placeholder_reason", None)
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--articles", type=Path, default=Path("articles.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("assets/article-images"))
    parser.add_argument("--refresh-all", action="store_true", help="Re-check every auto-managed archive image.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum eligible articles to query; 0 means unlimited.")
    args = parser.parse_args()

    data = json.loads(args.articles.read_text(encoding="utf-8"))
    rows = data if isinstance(data, list) else data.get("articles", [])
    args.output_dir.mkdir(parents=True, exist_ok=True)

    queried = changed = protected = no_match = not_better = 0
    for article in rows:
        if not isinstance(article, dict):
            continue
        if clean(article.get("status") or "published").lower() != "published":
            continue
        if is_protected(article):
            protected += 1
            continue

        eligible = is_placeholder(article) or is_commons_managed(article)
        if args.refresh_all:
            # "all" intentionally means all auto-managed images, never editorial,
            # photographer, curated-library or original-source selections.
            eligible = eligible or clean(article.get("image_status")).lower() in AUTO_STATUSES
        if not eligible:
            continue
        if args.limit and queried >= args.limit:
            break
        queried += 1

        candidate = find_candidate(article)
        if not candidate:
            no_match += 1
            continue
        new_score = candidate_score(article, candidate["title"])
        old_score = current_match_score(article)

        # Placeholders always improve when a strict match exists. Existing strict
        # Commons images require a clear score improvement to prevent churn.
        if is_commons_managed(article) and not is_placeholder(article):
            same = clean(article.get("image_match_title")).lower() == clean(candidate["title"]).lower()
            if same or (old_score >= 0 and new_score < old_score + 2):
                if old_score < 0:
                    article["image_match_score"] = new_score
                not_better += 1
                continue

        if save_candidate(article, candidate, args.output_dir, new_score):
            changed += 1
            print(f"archive-commons  {slug_for(article)}  score={new_score} <- {candidate['title']}")

    args.articles.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "queried": queried,
        "changed": changed,
        "protected": protected,
        "no_match": no_match,
        "not_better": not_better,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
