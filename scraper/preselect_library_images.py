#!/usr/bin/env python3
"""Automatically select a genuinely relevant photo from the newsroom library.

Run before external source and Commons image recovery. Do not manufacture a
photo, do not fetch another site's image, and do not alter editorial overrides.
Unmatched stories continue to the existing licensed-image and headline-card
fallback. Safe to run without an API key or network access.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ensure_article_images import (
    CARDS_DIR,
    choose_exact_story_photo,
    choose_filename_match,
    choose_named_library_photo,
    existing_meaningful_image,
    high_risk_photo_story,
    set_curated,
    valid_cards_image,
)


def preselect(article: dict[str, Any], root: Path) -> str:
    if existing_meaningful_image(article, root):
        return "kept-existing"

    if high_risk_photo_story(article):
        candidate = choose_exact_story_photo(article, root)
    else:
        candidate = choose_named_library_photo(article, root)
        if candidate is None:
            candidate = choose_filename_match(article, root)

    if candidate is None:
        return "no-match"
    try:
        relative = candidate.relative_to(root).as_posix()
    except ValueError:
        return "no-match"
    if not valid_cards_image(root, relative):
        return "no-match"

    set_curated(article, root, candidate)
    return "library-photo"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--articles", type=Path, default=Path("articles.json"))
    parser.add_argument("--report", type=Path, default=Path("image_library_preselection.json"))
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    root = Path.cwd()
    payload = json.loads(args.articles.read_text(encoding="utf-8"))
    rows = payload if isinstance(payload, list) else payload.get("articles", [])
    if not isinstance(rows, list):
        raise SystemExit("Expected an articles list")

    stats = {"library_photo": 0, "kept_existing": 0, "no_match": 0, "skipped": 0}
    selected: list[dict[str, str]] = []
    for article in rows:
        if not isinstance(article, dict) or str(article.get("status") or "published") != "published":
            stats["skipped"] += 1
            continue
        result = preselect(article, root)
        stats[result.replace("-", "_")] += 1
        if result == "library-photo":
            selected.append({
                "slug": str(article.get("slug") or ""),
                "image_url": str(article.get("image_url") or ""),
                "credit": str(article.get("image_credit") or ""),
            })

    args.articles.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.report.write_text(json.dumps({
        "policy": "Curated library and named aliases first; external photo only if permitted; generated headline card last.",
        "stats": stats,
        "selected": selected,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
