#!/usr/bin/env python3
"""Guarantee every published article leaves the pipeline with a usable image.

This is the final publication safety net. It never generates typography/place
cards. Earlier resolvers get first choice (manual image, source image, official
image, Wikimedia Commons, curated story photo). If those fail, this script
assigns an existing real photograph from the Rochdale Daily photo library,
choosing by area/category where possible.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

PLACEHOLDER_BITS = (
    "area-category-card", "placeholder", "default-image", "default_image",
    "category-image", "category_image", "img/generated", "stock_",
)
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}

# Ordered preferred real-photo filenames. Existence is checked at runtime, so
# this remains safe as the library evolves.
CATEGORY_CANDIDATES = {
    "crime": ["police.jpg", "gmp.jpg", "rochdale-town-hall.jpg"],
    "politics": ["rochdale-town-hall.jpg", "town-hall.jpg"],
    "community": ["rochdale-town-hall.jpg", "touchstones.jpg", "rochdale_canal.jpg"],
    "education": ["rochdale-town-hall.jpg", "touchstones.jpg"],
    "environment": ["rochdale_canal.jpg", "healey-dell.jpg", "rochdale-town-hall.jpg"],
    "events": ["rochdale-town-hall.jpg", "middleton-arena.jpg", "touchstones.jpg"],
    "health": ["rochdale-infirmary.jpg", "rochdale-town-hall.jpg"],
    "business": ["rochdale-town-hall.jpg", "the_baum.jpg"],
    "sport": ["rochdale_fc.jpg", "rochdale_hornets.jpg", "rochdale_hornets_women.jpg"],
    "traffic": ["traffic.jpg", "rochdale-town-hall.jpg"],
    "transport": ["tram.jpg", "rochdale_canal.jpg", "rochdale-town-hall.jpg"],
    "news": ["rochdale-town-hall.jpg", "rochdale_canal.jpg", "touchstones.jpg"],
}

AREA_HINTS = {
    "rochdale": ["rochdale-town-hall.jpg", "rochdale_canal.jpg"],
    "middleton": ["middleton-arena.jpg"],
    "healey": ["healey-dell.jpg"],
    "littleborough": ["littleborough.jpg"],
    "milnrow": ["milnrow.jpg"],
    "newhey": ["newhey.jpg"],
    "heywood": ["heywood.jpg"],
    "norden": ["norden.jpg"],
}


def clean(v: Any) -> str:
    return str(v or "").strip()


def is_placeholder(value: str) -> bool:
    low = clean(value).lower().replace("\\", "/")
    return not low or any(bit in low for bit in PLACEHOLDER_BITS)


def local_image_exists(root: Path, value: str) -> bool:
    if not value or value.startswith("http://") or value.startswith("https://"):
        return bool(value)
    path = root / value.lstrip("/")
    return path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES and path.stat().st_size > 4096


def usable(article: dict[str, Any], root: Path) -> bool:
    value = clean(article.get("image_url") or article.get("img"))
    return not is_placeholder(value) and local_image_exists(root, value)


def choose_library_photo(article: dict[str, Any], root: Path) -> Path | None:
    cards = root / "assets" / "img" / "cards"
    if not cards.is_dir():
        return None

    names: list[str] = []
    area = clean(article.get("area")).lower()
    category = clean(article.get("category")).lower()
    names.extend(AREA_HINTS.get(area, []))
    names.extend(CATEGORY_CANDIDATES.get(category, []))

    for name in names:
        path = cards / name
        if path.is_file() and path.stat().st_size > 4096:
            return path

    # Last-resort real-photo fallback: choose deterministically from the actual
    # photo library, excluding any generated/card-like filenames.
    candidates = []
    for path in cards.iterdir():
        if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        low = path.name.lower()
        if any(bit in low for bit in PLACEHOLDER_BITS):
            continue
        if path.stat().st_size <= 4096:
            continue
        candidates.append(path)
    if not candidates:
        return None

    candidates.sort(key=lambda p: p.name.lower())
    slug = clean(article.get("slug") or article.get("title"))
    score = sum(ord(ch) for ch in slug)
    return candidates[score % len(candidates)]


def main() -> int:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "articles.json")
    root = Path.cwd()
    data = json.loads(target.read_text(encoding="utf-8"))
    rows = data if isinstance(data, list) else data.get("articles", [])
    changed = 0
    unresolved = 0

    for article in rows:
        if not isinstance(article, dict):
            continue
        if clean(article.get("status") or "published").lower() != "published":
            continue
        if usable(article, root):
            # Keep img in sync for renderers that use the legacy field.
            article["img"] = clean(article.get("image_url") or article.get("img"))
            continue

        chosen = choose_library_photo(article, root)
        if chosen is None:
            unresolved += 1
            print(f"NO REAL IMAGE AVAILABLE: {clean(article.get('slug') or article.get('title'))}")
            continue

        rel = chosen.relative_to(root).as_posix()
        article["image_url"] = rel
        article["img"] = rel
        article["image_credit"] = article.get("image_credit") or "Rochdale Daily"
        article["image_credit_url"] = article.get("image_credit_url") or "https://rochdaledaily.co.uk/"
        article["image_status"] = "guaranteed-library-photo"
        article["source_image_reuse_status"] = "curated-library-photo"
        article.pop("image_placeholder_reason", None)
        changed += 1
        print(f"GUARANTEED IMAGE: {clean(article.get('slug'))} -> {rel}")

    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"changed": changed, "unresolved": unresolved}, indent=2))

    # Publishing should continue, but in normal operation unresolved should be 0.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
