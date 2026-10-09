#!/usr/bin/env python3
"""Guarantee that every published article has a usable image.

A meaningful existing editorial, source or Wikimedia image is preserved. If none
exists, the local cards library is searched for a filename-matched photograph.
Only when neither route produces a real image is a generated headline card used
as the final fallback. Image relevance is the editorial objective; the cards
folder is a cache/fallback implementation detail, not a publication rule.
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
FILLER_WORDS = {
    "the", "a", "an", "to", "of", "in", "at", "on", "for", "from", "with",
    "and", "or", "by", "after", "before", "into", "over", "under", "near",
}
# These are too broad to trust as a one-word filename match. They may still be
# part of a multi-word filename such as ``rochdale_infirmary.jpg``.
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



def is_manual_editorial(article: dict[str, Any]) -> bool:
    """Editor-written pieces from manual_articles.d / manual_articles.json."""
    return article.get("manual_article") is True or clean(article.get("source_kind")).lower() == "editorial"


def mark_editorial_photo(article: dict[str, Any], rel: str) -> None:
    """Record that a supplied cards-folder photo is the editor's choice.

    Manual source JSON predates the image_status marker, and the manual injector
    hard-replaces the stored record every run, so the marker set by a previous pass
    does not survive. Re-derive it from the source of truth (manual_article + a
    valid file in assets/img/cards) on every pass instead.
    """
    article["image_url"] = rel
    article["img"] = rel
    article["image_status"] = "editorial-photo"
    article["image_backfill_method"] = "manual-editorial-photo"
    article["source_image_reuse_status"] = "cards-only"
    article.pop("image_placeholder_reason", None)
    article.pop("image_match_score", None)


def existing_meaningful_image(article: dict[str, Any], root: Path) -> bool:
    """Keep a real image already selected by editorial/source/Commons enrichment."""
    value = clean(article.get("image_url") or article.get("img"))
    if not value:
        return False
    # A manual article pointing at a real, non-generated file inside assets/img/cards
    # is authoritative in every lane (publish, scrape-fast, scrape-kick). Previously
    # this rule only existed as a monkey-patch in frontpage_manual_publish.py, so the
    # scraper lanes replaced supplied photos with generated headline cards.
    if is_manual_editorial(article):
        manual_rel = cards_relative(value)
        if manual_rel and valid_cards_image(root, manual_rel) and not is_generated_card(root / manual_rel):
            mark_editorial_photo(article, manual_rel)
            return True
    low = value.lower().replace("\\", "/")
    status = clean(article.get("image_status")).lower()
    real_status = any(token in status for token in ("source-photo", "commons-photo", "editorial-photo"))
    if any(token in status for token in ("generated", "placeholder")):
        return False
    if any(token in low for token in ("generated-card", "placeholder", "category_", "category-")):
        return False
    if low.startswith(("https://", "http://")):
        return bool(real_status or clean(article.get("image_credit")) or clean(article.get("image_credit_url")))
    rel = low.lstrip("/")
    candidate = root / rel
    try:
        valid = candidate.is_file() and candidate.suffix.lower() in IMAGE_SUFFIXES and candidate.stat().st_size > 4096 and not is_generated_card(candidate)
    except OSError:
        return False
    if not valid:
        return False
    if rel.startswith("assets/img/cards/"):
        return real_status
    return bool(real_status or clean(article.get("image_credit")) or clean(article.get("image_credit_url")) or article.get("manual_article") is True or clean(article.get("source_kind")).lower() == "editorial")

def strip_remote_image_metadata(article: dict[str, Any]) -> None:
    for key in REMOTE_IMAGE_FIELDS:
        article.pop(key, None)


def normal_words(value: Any) -> list[str]:
    text = clean(value).lower()
    text = re.sub(r"[\u2019\u02bc']", "", text)
    return [word for word in re.sub(r"[^a-z0-9]+", " ", text).split() if word]


def filename_words(path: Path) -> list[str]:
    # Treat underscores, hyphens and spaces identically. Numbered variants such
    # as ``taken_to_hospital_2.jpeg`` share the same semantic filename.
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


def meaningful_words(words: list[str]) -> list[str]:
    return [word for word in words if word not in FILLER_WORDS]


def all_words_present(needles: list[str], haystack: list[str]) -> bool:
    if not needles:
        return False
    available = set(haystack)
    return all(word in available for word in needles)


def _field_match_score(subject: list[str], field_words: list[str], *, phrase_score: int, partial_score: int) -> int:
    """Return a score for a filename against one story field."""
    if not field_words:
        return -1

    subject_phrase = " ".join(subject)
    meaningful = meaningful_words(subject)

    if phrase_in(subject, field_words):
        # Longer filename phrases are intentionally favoured. This makes
        # taken_to_hospital.jpeg beat hospital.jpeg for the same headline.
        return phrase_score + len(subject) * 120 + len(subject_phrase)

    if not meaningful:
        return -1

    if all_words_present(meaningful, field_words):
        if len(meaningful) >= 2:
            return partial_score + len(meaningful) * 120 + sum(len(word) for word in meaningful)
        word = meaningful[0]
        if len(word) >= 5 and word not in TOO_GENERIC_SINGLE:
            return partial_score + 250 + len(word)

    return -1


def filename_match_score(article: dict[str, Any], path: Path) -> int:
    """Score how strongly a cards filename identifies an article.

    Priority is deliberately:
      title > slug > excerpt > body

    This means a filename matching the headline cannot be displaced by a random
    word appearing deep in the article body. Body/excerpt matching exists so a
    deliberately named image such as ``poisoned.jpeg`` can still be found when
    the exact word is omitted from a shortened headline.
    """
    if path.suffix.lower() not in IMAGE_SUFFIXES or is_generated_card(path):
        return -1

    subject = filename_words(path)
    if not subject:
        return -1

    title_words = normal_words(article.get("title"))
    slug_words = normal_words(slug_for(article))
    excerpt_words = normal_words(article.get("excerpt") or article.get("summary") or article.get("description"))
    body_words = normal_words(article.get("body") or article.get("content"))

    subject_phrase = " ".join(subject)
    title_phrase = " ".join(title_words)
    slug_phrase = " ".join(slug_words)

    # Exact story-name images always win.
    if subject_phrase and subject_phrase == title_phrase:
        return 20000 + len(subject) * 150 + len(subject_phrase)
    if subject_phrase and subject_phrase == slug_phrase:
        return 19000 + len(subject) * 150 + len(subject_phrase)

    candidates = [
        _field_match_score(subject, title_words, phrase_score=15000, partial_score=12000),
        _field_match_score(subject, slug_words, phrase_score=14000, partial_score=11000),
        _field_match_score(subject, excerpt_words, phrase_score=8000, partial_score=6000),
        _field_match_score(subject, body_words, phrase_score=4500, partial_score=3000),
    ]
    return max(candidates)


def choose_filename_match(article: dict[str, Any], root: Path) -> Path | None:
    """Choose the best matching photograph using only assets/img/cards/."""
    directory = root / CARDS_DIR
    if not directory.is_dir():
        return None

    scored: list[tuple[int, int, str, Path]] = []
    for path in directory.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        try:
            if path.stat().st_size <= 4096:
                continue
        except OSError:
            continue
        score = filename_match_score(article, path)
        if score >= 0:
            # Token count is a secondary specificity tie-breaker.
            scored.append((score, len(filename_words(path)), path.name.lower(), path))

    if not scored:
        return None

    best_score = max(item[0] for item in scored)
    best_token_count = max(item[1] for item in scored if item[0] == best_score)
    best = sorted(
        (item for item in scored if item[0] == best_score and item[1] == best_token_count),
        key=lambda item: item[2],
    )
    # If numbered variants tie exactly, choose deterministically by article slug.
    digest = int(hashlib.sha256(slug_for(article).encode("utf-8")).hexdigest()[:8], 16)
    return best[digest % len(best)][3]


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


# ---------------------------------------------------------------------------
# Generated cards, in the paper's own dress.
#
# The card used to be a near-black slab with a cyan bar and DejaVu Sans, a
# leftover from the cyan/navy palette the site dropped in September 2026. On a
# warm paper page set in Libre Baskerville it looked like it had come from a
# different website. It is now drawn from the same values as
# assets/css/rd-tokens.css and the same two typefaces, which ship in
# assets/fonts so the card is identical on every machine that draws it.
#
# Changing CARD_STYLE redraws every existing generated card once (see
# restyle_generated_cards), so the whole archive changes with it.
# ---------------------------------------------------------------------------
CARD_STYLE = "broadsheet-v1"
CARD_STYLE_STAMP = CARDS_DIR / ".generated-card-style"
FONT_DIR = Path("assets/fonts")
CARD_PAPER = (246, 245, 241)     # --paper  #f6f5f1
CARD_INK = (43, 40, 36)          # --ink    #2b2824
CARD_INK_SOFT = (91, 89, 82)     # --ink-soft #5b5952
CARD_LINE = (220, 218, 212)      # --line   #dcdad4
CARD_ACCENT = (107, 90, 70)      # warm accent #6b5a46
CARD_MARGIN = 84


def card_font(kind: str, size: int) -> ImageFont.ImageFont:
    """The site's own faces: Libre Baskerville for headlines, Instrument Sans for furniture."""
    name, weight = (
        ("LibreBaskerville-wght.ttf", 700) if kind == "serif" else ("InstrumentSans-wdth-wght.ttf", 600)
    )
    for base in (Path.cwd() / FONT_DIR, Path(__file__).resolve().parents[1] / FONT_DIR):
        path = base / name
        if not path.is_file():
            continue
        try:
            loaded = ImageFont.truetype(str(path), size=size)
            axes = loaded.get_variation_axes()
            loaded.set_variation_by_axes([
                weight if "eight" in str(axis.get("name")) else axis.get("default") for axis in axes
            ])
            return loaded
        except (OSError, AttributeError, ValueError):
            continue
    return font(size, bold=True)


def draw_tracked(draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str,
                 fnt: ImageFont.ImageFont, fill: tuple[int, int, int], tracking: float,
                 anchor_right: bool = False) -> float:
    """Draw letter-spaced capitals; returns the width drawn."""
    widths = [draw.textlength(char, font=fnt) for char in text]
    total = sum(widths) + tracking * max(0, len(text) - 1)
    x, y = xy
    if anchor_right:
        x -= total
    for char, width in zip(text, widths):
        draw.text((x, y), char, fill=fill, font=fnt)
        x += width + tracking
    return total


def fit_headline(draw: ImageDraw.ImageDraw, text: str, width: int) -> tuple[ImageFont.ImageFont, list[str], int]:
    """Largest size at which the headline fits in four lines without being cut."""
    words = clean(text).split()
    for size in (64, 58, 52, 46, 42):
        fnt = card_font("serif", size)
        lines: list[str] = []
        current = ""
        for word in words:
            trial = word if not current else f"{current} {word}"
            if draw.textlength(trial, font=fnt) <= width:
                current = trial
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        if len(lines) <= 4:
            return fnt, lines, size
    # Still too long at the smallest size: cut at four lines, honestly marked.
    last = lines[3]
    while last and draw.textlength(last + "…", font=fnt) > width:
        last = last[:-1]
    return fnt, lines[:3] + [last.rstrip() + "…"], size


def draw_generated_card(target: Path, title: str, category: str, sponsored: bool = False) -> None:
    """Draw one photo-free card: paper ground, ruled head, serif headline, masthead foot."""
    canvas = Image.new("RGB", (WIDTH, HEIGHT), CARD_PAPER)
    draw = ImageDraw.Draw(canvas)
    left, right = CARD_MARGIN, WIDTH - CARD_MARGIN

    headline = clean(title) or "Rochdale Daily"
    if headline.lower().startswith("sponsored:"):
        sponsored = True
        headline = headline.split(":", 1)[1].strip() or headline
    kicker = "SPONSORED" if sponsored else (clean(category) or "news").upper()

    # Section head: the same thin-over-thick double rule the pages use.
    draw.rectangle((left, 70, right, 70), fill=CARD_INK)
    draw.rectangle((left, 75, right, 77), fill=CARD_INK)
    label = card_font("sans", 24)
    draw_tracked(draw, (left, 100), kicker, label, CARD_ACCENT, 4.2)

    fnt, lines, size = fit_headline(draw, headline, right - left)
    leading = int(size * 1.26)
    block = leading * len(lines)
    top, bottom = 150, HEIGHT - 122
    y = top + max(0, (bottom - top - block) // 2) - int(size * 0.08)
    for line in lines:
        draw.text((left, y), line, fill=CARD_INK, font=fnt)
        y += leading

    draw.rectangle((left, HEIGHT - 104, right, HEIGHT - 104), fill=CARD_LINE)
    foot = card_font("sans", 22)
    draw_tracked(draw, (left, HEIGHT - 82), "ROCHDALE DAILY", foot, CARD_INK, 4.6)
    draw_tracked(draw, (right, HEIGHT - 82), "ROCHDALEDAILY.CO.UK", foot, CARD_INK_SOFT, 3.2, anchor_right=True)

    target.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(target, format="JPEG", quality=88, optimize=True)


def make_generated_card(article: dict[str, Any], root: Path) -> str:
    """Create a photo-free fallback card inside assets/img/cards."""
    slug = slug_for(article)
    target = root / CARDS_DIR / f"{slug}-generated-card.jpg"
    draw_generated_card(
        target,
        clean(article.get("title") or "Rochdale Daily"),
        clean(article.get("category") or "news"),
        sponsored=article.get("sponsored") is True,
    )
    return target.relative_to(root).as_posix()


def restyle_generated_cards(root: Path, rows: list[Any]) -> dict[str, int]:
    """Redraw every existing generated card once when the card style changes.

    A generated card is otherwise drawn once and kept for ever, so a new style
    would only ever reach new stories while 500-odd archive pages kept the old
    one. The headline and section come from the live feed, then the archive
    index. A card with no article behind it in either cannot be redrawn - there
    is no headline to draw - and is counted, not guessed at.
    """
    stamp = root / CARD_STYLE_STAMP
    try:
        if stamp.read_text(encoding="utf-8").strip() == CARD_STYLE:
            return {"redrawn": 0, "no_article": 0, "already_current": 1}
    except OSError:
        pass

    known: dict[str, dict[str, Any]] = {}
    try:
        archive = json.loads((root / "archive-index.json").read_text(encoding="utf-8"))
        for entry in archive if isinstance(archive, list) else []:
            if isinstance(entry, dict) and entry.get("slug"):
                known[str(entry["slug"])] = entry
    except (OSError, ValueError):
        pass
    for row in rows:
        if isinstance(row, dict) and slug_for(row):
            known[slug_for(row)] = row  # the live record is the fresher of the two

    redrawn = no_article = 0
    for path in sorted((root / CARDS_DIR).glob("*-generated-card.jpg")):
        entry = known.get(path.name[: -len("-generated-card.jpg")])
        if entry is None:
            no_article += 1
            continue
        draw_generated_card(
            path,
            clean(entry.get("title") or "Rochdale Daily"),
            clean(entry.get("category") or "news"),
            sponsored=entry.get("sponsored") is True,
        )
        redrawn += 1
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(CARD_STYLE + "\n", encoding="utf-8")
    print(f"Generated-card restyle ({CARD_STYLE}): {redrawn} redrawn; {no_article} have no article and were left.")
    return {"redrawn": redrawn, "no_article": no_article, "already_current": 0}


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
    article["image_match_score"] = filename_match_score(article, chosen)
    article.pop("image_placeholder_reason", None)
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
    article.pop("image_match_score", None)
    strip_remote_image_metadata(article)


def enforce_article(article: dict[str, Any], root: Path) -> str:
    if existing_meaningful_image(article, root):
        return "kept-existing"

    chosen = choose_filename_match(article, root)
    if chosen is not None and valid_cards_image(root, chosen.relative_to(root).as_posix()):
        current = cards_relative(article.get("image_url") or article.get("img"))
        set_curated(article, root, chosen)
        return "kept-cards" if current == article["image_url"] else "cards-library"

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

    restyle = restyle_generated_cards(root, rows)

    stats = {"kept_cards": 0, "cards_library": 0, "cards_generated": 0, "skipped": 0}
    report: list[dict[str, Any]] = []

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
            "match_score": article.get("image_match_score"),
        })
        print(f"{result:16} {slug_for(article)} -> {article.get('image_url')}")

    # The newsdesk composer (newsdesk.html) offers the editor a picker over the
    # real photo library. This manifest is its data: every valid, non-generated
    # image in assets/img/cards, refreshed by every lane that runs this script,
    # so the picker can never drift from the folder.
    manifest_entries = sorted(
        candidate.name
        for candidate in (root / CARDS_DIR).glob("*")
        if candidate.is_file()
        and candidate.suffix.lower() in IMAGE_SUFFIXES
        and candidate.stat().st_size > 4096
        and not is_generated_card(candidate)
    )
    (root / CARDS_DIR / "manifest.json").write_text(
        json.dumps({"images": manifest_entries}, indent=2) + "\n", encoding="utf-8"
    )

    args.articles.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.report.write_text(
        json.dumps(
            {
                "policy": "preserve meaningful existing image; then filename-matched local photo; generated card only as final fallback",
                "stats": stats,
                "items": report,
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
