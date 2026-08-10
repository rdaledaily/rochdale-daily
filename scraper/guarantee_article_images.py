#!/usr/bin/env python3
"""Guarantee every published article leaves the pipeline with an image.

Final image priority:
1. Keep any already-usable supplied/source/official/Wikimedia image.
2. Use a relevant existing Rochdale Daily library photograph. Search the
   curated card matcher first, then the wider assets/img library by filename.
3. Only if no relevant library photograph exists, create the curated Rochdale
   Daily area/category place card as the absolute last resort.

Publishing never fails solely because image sourcing was difficult.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from story_image import compose_story_card, find_library_photo, _folder_credit

PLACEHOLDER_BITS = (
    "area-category-card", "placeholder", "default-image", "default_image",
    "category-image", "category_image", "img/generated", "stock_",
)
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
CARDS_DIR = Path("assets/img/cards")
LIBRARY_ROOT = Path("assets/img")
OUTPUT_DIR = Path("assets/article-images")
STOP = {
    "rochdale","heywood","middleton","littleborough","milnrow","newhey","norden",
    "healey","wardle","news","latest","today","local","community","residents",
    "after","before","with","from","into","over","under","plans","plan","new",
    "the","and","for","this","that","their","more","about","amid","could","would",
}


def clean(v: Any) -> str:
    return str(v or "").strip()


def slug_for(article: dict[str, Any]) -> str:
    return clean(article.get("slug") or article.get("id") or article.get("title")).strip()


def is_placeholder(value: str) -> bool:
    low = clean(value).lower().replace("\\", "/")
    return not low or any(bit in low for bit in PLACEHOLDER_BITS)


def local_image_exists(root: Path, value: str) -> bool:
    value = clean(value)
    if value.startswith("http://") or value.startswith("https://"):
        return True
    if not value:
        return False
    path = root / value.lstrip("/")
    return path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES and path.stat().st_size > 4096


def usable(article: dict[str, Any], root: Path) -> bool:
    value = clean(article.get("image_url") or article.get("img"))
    return not is_placeholder(value) and local_image_exists(root, value)


def norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", clean(value).lower()).strip()


def tokens(value: str) -> list[str]:
    return [w for w in norm(value).split() if len(w) >= 4 and w not in STOP and not w.isdigit()]


def wider_library_match(article: dict[str, Any], root: Path) -> Path | None:
    """Find a genuinely relevant image anywhere under assets/img.

    Matching is intentionally filename-driven: an image only wins when its
    filename shares a strong subject phrase or at least two meaningful headline
    tokens. This searches the whole existing image library, not just cards/.
    """
    lib = root / LIBRARY_ROOT
    if not lib.is_dir():
        return None

    title = clean(article.get("title"))
    slug = slug_for(article)
    wanted = set(tokens(title) + tokens(slug))
    if not wanted:
        return None

    best: tuple[int, Path] | None = None
    for path in lib.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        rel_low = path.relative_to(root).as_posix().lower()
        if "generated" in rel_low or "area-category-card" in rel_low or "placeholder" in rel_low:
            continue
        if path.stat().st_size <= 4096:
            continue

        stem_tokens = set(tokens(path.stem))
        shared = wanted & stem_tokens
        if len(shared) < 2:
            # One very distinctive long token can be enough, e.g. "watergrove".
            if not any(len(t) >= 9 for t in shared):
                continue
        score = len(shared) * 4 + sum(2 for t in shared if len(t) >= 8)
        if norm(path.stem) in norm(slug) or norm(path.stem) in norm(title):
            score += 8
        if best is None or score > best[0]:
            best = (score, path)
    return best[1] if best else None


def set_library_photo(article: dict[str, Any], root: Path) -> bool:
    """Assign only a library image that genuinely matches this story."""
    title = clean(article.get("title"))
    slug = slug_for(article)
    category = clean(article.get("category")).lower()

    chosen = find_library_photo(title, slug, category, root / CARDS_DIR, slug_only=False)
    if chosen is None or not chosen.is_file() or chosen.stat().st_size <= 4096:
        chosen = wider_library_match(article, root)
    if chosen is None or not chosen.is_file() or chosen.stat().st_size <= 4096:
        return False

    rel = chosen.relative_to(root).as_posix()
    base = chosen.stem
    credit_dir = chosen.parent
    credit = (
        _folder_credit(base, credit_dir)
        or _folder_credit(base.rsplit("-", 1)[0], credit_dir)
        or "Rochdale Daily"
    )
    article["image_url"] = rel
    article["img"] = rel
    article["image_credit"] = credit
    article["image_credit_url"] = "" if credit != "Rochdale Daily" else "https://rochdaledaily.co.uk/"
    article["image_status"] = "curated-library-photo"
    article["source_image_reuse_status"] = "curated-library-photo"
    article.pop("image_placeholder_reason", None)
    return True


def set_place_card(article: dict[str, Any], root: Path) -> None:
    slug = slug_for(article) or "story"
    output = root / OUTPUT_DIR / f"{slug}-area-category-card.jpg"
    output.parent.mkdir(parents=True, exist_ok=True)
    local_path, credit = compose_story_card(
        clean(article.get("title")), article.get("area"), article.get("category"), output,
        story_text=(clean(article.get("excerpt")) + " " + clean(article.get("summary"))).strip(),
    )
    article["image_url"] = local_path
    article["img"] = local_path
    article["image_credit"] = credit or "Rochdale Daily"
    article["image_credit_url"] = "" if credit and credit != "Rochdale Daily" else "https://rochdaledaily.co.uk/"
    article["image_status"] = "area-category-card"
    article["source_image_reuse_status"] = "category-fallback"
    article["image_placeholder_reason"] = "Last-resort curated Rochdale Daily place card; no usable source, Commons or relevant library photograph was available"


def main() -> int:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "articles.json")
    root = Path.cwd()
    data = json.loads(target.read_text(encoding="utf-8"))
    rows = data if isinstance(data, list) else data.get("articles", [])
    kept = library = place_cards = 0

    for article in rows:
        if not isinstance(article, dict) or clean(article.get("status") or "published").lower() != "published":
            continue
        if usable(article, root):
            article["img"] = clean(article.get("image_url") or article.get("img"))
            kept += 1
            continue
        if set_library_photo(article, root):
            library += 1
            print(f"LIBRARY IMAGE: {slug_for(article)} -> {article['image_url']}")
            continue
        set_place_card(article, root)
        place_cards += 1
        print(f"LAST-RESORT PLACE CARD: {slug_for(article)} -> {article['image_url']}")

    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"kept_existing_real_image": kept, "relevant_library_image": library, "last_resort_place_card": place_cards}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
