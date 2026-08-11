#!/usr/bin/env python3
"""Enforce Rochdale Daily's cards-only article-image policy.

Every published article image must live under ``assets/img/cards``.
No source-page photographs, Wikimedia Commons images, remote URLs, people-folder
images, area-folder images, or wider ``assets/img`` photographs are eligible.

For each story:
1. Keep an existing valid image only when it already lives in assets/img/cards.
2. Otherwise use a deliberately curated cards-folder photograph matched by the
   article slug/headline using story_image.find_library_photo.
3. If there is no suitable curated photograph, generate a plain Rochdale Daily
   text card and save that generated card in assets/img/cards as well.

The script accepts the legacy command-line flags used by existing workflows, but
network-related flags are intentionally ignored: this module never performs a
network request.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from story_image import find_library_photo, _folder_credit

CARDS_DIR = Path("assets/img/cards")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
WIDTH = 1200
HEIGHT = 675

# Metadata that can point future jobs back at remote/source photography. Once an
# article is cards-only, remove these so the record itself cannot re-seed a
# Wikimedia/source-image resolver later.
REMOTE_IMAGE_FIELDS = {
    "source_image_candidate_url",
    "source_image_url",
    "source_image_candidates",
    "rss_image_url",
    "media_content_url",
    "media_thumbnail_url",
    "enclosure_url",
    "thumbnail_url",
    "rejected_image_candidates",
    "image_match_title",
}


def clean(value: Any) -> str:
    return str(value or "").strip()


def slug_for(article: dict[str, Any]) -> str:
    raw = clean(article.get("slug") or article.get("id") or article.get("title"))
    return re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")[:100] or "story"


def cards_relative(value: Any) -> str:
    value = clean(value).replace("\\", "/").lstrip("/")
    return value if value.startswith("assets/img/cards/") else ""


def valid_cards_image(root: Path, value: Any) -> bool:
    rel = cards_relative(value)
    if not rel:
        return False
    path = root / rel
    try:
        return (
            path.is_file()
            and path.suffix.lower() in IMAGE_SUFFIXES
            and path.stat().st_size > 4096
        )
    except OSError:
        return False


def strip_remote_image_metadata(article: dict[str, Any]) -> None:
    for key in REMOTE_IMAGE_FIELDS:
        article.pop(key, None)


def font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.ImageFont, width: int) -> list[str]:
    words = clean(text).split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = word if not current else f"{current} {word}"
        box = draw.textbbox((0, 0), trial, font=fnt)
        if box[2] - box[0] <= width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    if len(lines) > 4:
        lines = lines[:4]
        last = lines[-1]
        while last and draw.textbbox((0, 0), last + "…", font=fnt)[2] > width:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    return lines


def make_generated_card(article: dict[str, Any], root: Path) -> str:
    """Create a photo-free fallback card inside assets/img/cards."""
    slug = slug_for(article)
    target = root / CARDS_DIR / f"{slug}-generated-card.jpg"
    target.parent.mkdir(parents=True, exist_ok=True)

    canvas = Image.new("RGB", (WIDTH, HEIGHT), (13, 19, 28))
    draw = ImageDraw.Draw(canvas)
    cyan = (37, 164, 201)
    white = (248, 250, 252)
    muted = (184, 197, 211)

    draw.rectangle((0, 0, WIDTH, 18), fill=cyan)
    kicker_font = font(34, bold=True)
    title_font = font(66, bold=True)
    small_font = font(30)

    category = clean(article.get("category") or "news").upper()
    area = clean(article.get("area") or "Rochdale")
    draw.text((72, 72), category, fill=cyan, font=kicker_font)

    y = 145
    for line in wrap(draw, clean(article.get("title") or "Rochdale Daily"), title_font, WIDTH - 144):
        draw.text((72, y), line, fill=white, font=title_font)
        y += 78

    draw.text((72, HEIGHT - 100), f"{area}  •  Rochdale Daily", fill=muted, font=small_font)
    canvas.save(target, format="JPEG", quality=90, optimize=True)
    return target.relative_to(root).as_posix()


def curated_match(article: dict[str, Any], root: Path) -> Path | None:
    category = clean(article.get("category")).lower()
    return find_library_photo(
        clean(article.get("title")),
        slug_for(article),
        category,
        root / CARDS_DIR,
        # Crime images must be explicitly named for the story.
        slug_only=(category == "crime"),
    )


def set_curated(article: dict[str, Any], root: Path, chosen: Path) -> None:
    rel = chosen.relative_to(root).as_posix()
    base = re.sub(r"-\d+$", "", chosen.stem)
    credit = (
        _folder_credit(base, root / CARDS_DIR)
        or _folder_credit(chosen.stem, root / CARDS_DIR)
        or "Rochdale Daily"
    )
    article["image_url"] = rel
    article["img"] = rel
    article["image_credit"] = credit
    article["image_credit_url"] = "" if credit != "Rochdale Daily" else "https://rochdaledaily.co.uk/"
    article["image_status"] = "cards-library-photo"
    article["image_backfill_method"] = "cards-library"
    article["source_image_reuse_status"] = "cards-only"
    article.pop("image_placeholder_reason", None)
    strip_remote_image_metadata(article)


def set_generated(article: dict[str, Any], root: Path) -> None:
    rel = make_generated_card(article, root)
    article["image_url"] = rel
    article["img"] = rel
    article["image_credit"] = "Rochdale Daily"
    article["image_credit_url"] = "https://rochdaledaily.co.uk/"
    article["image_status"] = "cards-generated"
    article["image_backfill_method"] = "cards-generated"
    article["source_image_reuse_status"] = "cards-only"
    article["image_placeholder_reason"] = "No editor-curated matching photograph exists in assets/img/cards"
    strip_remote_image_metadata(article)


def enforce_article(article: dict[str, Any], root: Path) -> str:
    if valid_cards_image(root, article.get("image_url") or article.get("img")):
        rel = cards_relative(article.get("image_url") or article.get("img"))
        article["image_url"] = rel
        article["img"] = rel
        article["source_image_reuse_status"] = "cards-only"
        strip_remote_image_metadata(article)
        return "kept-cards"

    chosen = curated_match(article, root)
    if chosen is not None and valid_cards_image(root, chosen.relative_to(root).as_posix()):
        set_curated(article, root, chosen)
        return "cards-library"

    set_generated(article, root)
    return "cards-generated"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--articles", type=Path, default=Path("articles.json"))
    parser.add_argument("--report", type=Path, default=Path("image_coverage_report.json"))
    # Legacy flags kept only so older workflows do not break. They do not enable
    # network access or any non-cards image source.
    parser.add_argument("--retry-placeholders", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=0)
    parser.add_argument("--sleep", type=float, default=0.0)
    parser.add_argument("--output-dir", type=Path, default=CARDS_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    root = Path.cwd()
    data = json.loads(args.articles.read_text(encoding="utf-8"))
    rows = data if isinstance(data, list) else data.get("articles", [])
    if not isinstance(rows, list):
        raise SystemExit("Article feed must contain a JSON list")

    stats = {"kept_cards": 0, "cards_library": 0, "cards_generated": 0, "skipped": 0}
    report: list[dict[str, str]] = []

    for article in rows:
        if not isinstance(article, dict):
            continue
        if clean(article.get("status") or "published").lower() != "published":
            stats["skipped"] += 1
            continue
        result = enforce_article(article, root)
        if result == "kept-cards":
            stats["kept_cards"] += 1
        elif result == "cards-library":
            stats["cards_library"] += 1
        else:
            stats["cards_generated"] += 1
        report.append({
            "slug": slug_for(article),
            "result": result,
            "image_url": clean(article.get("image_url")),
        })
        print(f"{result:16} {slug_for(article)} -> {article.get('image_url')}")

    args.articles.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.report.write_text(json.dumps({"policy": "assets/img/cards only", "stats": stats, "items": report}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
