#!/usr/bin/env python3
"""Enforce Rochdale Daily's cards-only, filename-matched article-image policy.

Every published article image must live under ``assets/img/cards``.
No source-page photographs, Wikimedia Commons images, remote URLs, people-folder
images, area-folder images, or wider ``assets/img`` photographs are eligible.

Photographs in ``assets/img/cards`` are matched to stories by THEIR FILENAME.
A full filename phrase or a strong partial filename phrase may match the article
headline/slug. For example, ``the_resilient_roach.jpg`` matches a headline such
as ``Resilient Roach Project launches new initiative`` because the meaningful
filename phrase ``resilient roach`` occurs in the story name.

Longest / most-specific filename matches win. An existing cards image is not
blindly preserved: if its filename does not match the story, it is replaced by
a better filename match or by a generated Rochdale Daily fallback card.

The script accepts legacy command-line flags used by existing workflows, but
network-related flags are intentionally ignored: this module never performs a
network request.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from story_image import _folder_credit

CARDS_DIR = Path("assets/img/cards")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
WIDTH = 1200
HEIGHT = 675

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

LEADING_ARTICLES = {"the", "a", "an"}
# A one-word image name can match when the word is distinctive (for example
# assault.jpg). These words are too broad to be trusted on their own.
TOO_GENERIC_SINGLE = {
    "rochdale", "heywood", "middleton", "littleborough", "milnrow", "newhey",
    "norden", "news", "crime", "politics", "sport", "sports", "business",
    "health", "community", "environment", "traffic", "transport", "events",
    "event", "local", "borough", "town", "centre", "center", "image", "photo",
    "picture", "card", "generic", "default", "stock", "placeholder",
}
GENERATED_MARKERS = ("generated-card", "area-category-card", "placeholder")


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


def normal_words(value: Any) -> list[str]:
    text = clean(value).lower()
    text = re.sub(r"[\u2019\u02bc']", "", text)
    return [word for word in re.sub(r"[^a-z0-9]+", " ", text).split() if word]


def filename_words(path: Path) -> list[str]:
    stem = re.sub(r"[-_ ]\d+$", "", path.stem)
    words = normal_words(stem)
    while words and words[0] in LEADING_ARTICLES:
        words.pop(0)
    return words


def is_generated_card(path: Path) -> bool:
    low = path.stem.lower().replace("_", "-")
    return any(marker in low for marker in GENERATED_MARKERS)


def phrase_in(words: list[str], haystack: list[str]) -> bool:
    if not words or len(words) > len(haystack):
        return False
    size = len(words)
    return any(haystack[i:i + size] == words for i in range(len(haystack) - size + 1))


def filename_match_score(article: dict[str, Any], path: Path) -> int:
    """Score how strongly a cards filename names the story subject.

    Exact slug/full contiguous phrase wins. A partial match is accepted when all
    meaningful filename words occur in the headline/slug, even if a harmless
    leading article such as ``the`` differs. This is what makes
    ``the_resilient_roach.jpg`` match ``Resilient Roach Project``.
    """
    if path.suffix.lower() not in IMAGE_SUFFIXES or is_generated_card(path):
        return -1

    subject = filename_words(path)
    if not subject:
        return -1

    title_words = normal_words(article.get("title"))
    slug_words = normal_words(slug_for(article))
    combined = title_words + slug_words
    if not combined:
        return -1

    subject_phrase = " ".join(subject)
    slug_phrase = " ".join(slug_words)

    # One-story exact filenames beat all reusable subject images.
    if subject_phrase == slug_phrase:
        return 10000 + len(subject) * 100 + len(subject_phrase)

    # A full contiguous filename phrase in the headline/slug is the normal and
    # safest reusable match: resilient_roach.jpg -> Resilient Roach Project.
    if phrase_in(subject, title_words) or phrase_in(subject, slug_words):
        return 5000 + len(subject) * 100 + len(subject_phrase)

    # Partial filename matching: every meaningful filename token must be present
    # somewhere in the story name. Require two tokens unless the sole token is
    # distinctive enough to avoid generic category/town images matching widely.
    meaningful = [word for word in subject if word not in TOO_GENERIC_SINGLE]
    if not meaningful:
        return -1
    available = set(combined)
    if all(word in available for word in meaningful):
        if len(meaningful) >= 2:
            return 3000 + len(meaningful) * 100 + sum(len(word) for word in meaningful)
        word = meaningful[0]
        if len(word) >= 5 and word not in TOO_GENERIC_SINGLE:
            return 1200 + len(word)

    return -1


def choose_filename_match(article: dict[str, Any], root: Path) -> Path | None:
    """Choose the best matching photograph using only filenames in cards/."""
    directory = root / CARDS_DIR
    if not directory.is_dir():
        return None

    scored: list[tuple[int, str, Path]] = []
    for path in directory.iterdir():
        if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        try:
            if path.stat().st_size <= 4096:
                continue
        except OSError:
            continue
        score = filename_match_score(article, path)
        if score >= 0:
            scored.append((score, path.name.lower(), path))

    if not scored:
        return None

    best_score = max(item[0] for item in scored)
    best = sorted((item for item in scored if item[0] == best_score), key=lambda item: item[1])
    # If numbered variants produce an exact tie, choose deterministically by slug.
    digest = int(hashlib.sha256(slug_for(article).encode("utf-8")).hexdigest()[:8], 16)
    return best[digest % len(best)][2]


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
    article["image_backfill_method"] = "cards-filename-match"
    article["source_image_reuse_status"] = "cards-only"
    article["image_match_title"] = chosen.name
    article.pop("image_placeholder_reason", None)
    # Keep image_match_title, which now records the LOCAL cards filename; remove
    # all fields that could point a future job back to remote photography.
    for key in REMOTE_IMAGE_FIELDS - {"image_match_title"}:
        article.pop(key, None)


def set_generated(article: dict[str, Any], root: Path) -> None:
    rel = make_generated_card(article, root)
    article["image_url"] = rel
    article["img"] = rel
    article["image_credit"] = "Rochdale Daily"
    article["image_credit_url"] = "https://rochdaledaily.co.uk/"
    article["image_status"] = "cards-generated"
    article["image_backfill_method"] = "cards-generated"
    article["source_image_reuse_status"] = "cards-only"
    article["image_placeholder_reason"] = "No filename-matched photograph exists in assets/img/cards"
    strip_remote_image_metadata(article)


def enforce_article(article: dict[str, Any], root: Path) -> str:
    # Always re-check the library BEFORE preserving an existing cards image.
    # This makes the policy retrospective: adding resilient_roach.jpg today will
    # replace yesterday's generated card on the Resilient Roach story next run.
    chosen = choose_filename_match(article, root)
    if chosen is not None and valid_cards_image(root, chosen.relative_to(root).as_posix()):
        current = cards_relative(article.get("image_url") or article.get("img"))
        set_curated(article, root, chosen)
        return "kept-cards" if current == article["image_url"] else "cards-library"

    # A previously generated fallback may be kept when there is still no real
    # filename match. Other unrelated cards images are never preserved.
    current_rel = cards_relative(article.get("image_url") or article.get("img"))
    if current_rel and valid_cards_image(root, current_rel):
        current_path = root / current_rel
        if is_generated_card(current_path):
            article["image_url"] = current_rel
            article["img"] = current_rel
            article["source_image_reuse_status"] = "cards-only"
            strip_remote_image_metadata(article)
            return "kept-cards"

    set_generated(article, root)
    return "cards-generated"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--articles", type=Path, default=Path("articles.json"))
    parser.add_argument("--report", type=Path, default=Path("image_coverage_report.json"))
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
            "matched_filename": clean(article.get("image_match_title")),
        })
        print(f"{result:16} {slug_for(article)} -> {article.get('image_url')}")

    args.articles.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.report.write_text(json.dumps({"policy": "assets/img/cards only; filename matched", "stats": stats, "items": report}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
