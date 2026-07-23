"""Compose a story card image that relates to a story's AREA and CATEGORY.

Every published story can be given a distinctive 1200x675 card even when no
source photograph exists. The card always encodes two things:

* AREA  — a real local photograph if one has been curated for that area
          (assets/img/areas/<area>.jpg), otherwise a deterministic background
          whose hue is seeded from the area name, plus an on-card area tag.
* CATEGORY — an accent colour, a drawn glyph, and a kicker label.

This needs no external assets to work: with an empty areas/ folder it produces
a clean, on-brand generated card per (area, category). Drop real Creative
Commons photos (e.g. from Geograph, credited via areas/credits.json) into
assets/img/areas/ and those stories automatically gain real local photography,
category-styled, with the photographer credited.

Nothing here fabricates photography of an event: a generated card is obviously a
typographic card, and a real photo is a genuine, credited image of the place.
"""
from __future__ import annotations

import colorsys
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

WIDTH = 1200
HEIGHT = 675
# Site accent. Kept as one constant so every generated card belongs to the
# same family: the old per-category palette meant a community story arrived
# orange and a politics story purple, which read as two unrelated designs
# rather than one masthead. Category is still signalled, by glyph and kicker
# label, not by hue.
CYAN = (34, 211, 238)
GOLD = CYAN  # retained name: referenced by the area pin and the news default
INK = (14, 18, 26)

# Per-category glyph accent + short label. To restore colour-coding, replace
# ACCENT below with the per-category values kept in the comment beneath.
ACCENT = CYAN
CATEGORY_STYLE: dict[str, tuple[tuple[int, int, int], str]] = {
    "crime": (ACCENT, "Crime"),
    "traffic": (ACCENT, "Traffic"),
    "transport": (ACCENT, "Transport"),
    "politics": (ACCENT, "Politics"),
    "education": (ACCENT, "Education"),
    "sport": (ACCENT, "Sport"),
    "events": (ACCENT, "Events"),
    "business": (ACCENT, "Business"),
    "community": (ACCENT, "Community"),
    "health": (ACCENT, "Health"),
    "environment": (ACCENT, "Environment"),
    "news": (ACCENT, "News"),
}
# Previous per-category accents, kept for reference:
#   crime (198,64,64)      traffic (214,150,46)   transport (66,148,168)
#   politics (150,108,184) education (78,128,196) sport (92,168,96)
#   events (198,108,168)   business (110,128,150) community (214,132,70)
#   health (92,170,150)    environment (104,162,84)

# Wards -> township, so a ward story can fall back to its township photo before
# the borough-wide one. Extend freely; unknown areas fall back to "rochdale".
AREA_PARENT: dict[str, str] = {
    "kirkholt": "rochdale", "spotland": "rochdale", "falinge": "rochdale",
    "deeplish": "rochdale", "smallbridge": "rochdale", "firgrove": "rochdale",
    "balderstone": "rochdale", "sudden": "rochdale", "lowerplace": "rochdale",
    "meanwood": "rochdale", "wardleworth": "rochdale", "shawclough": "rochdale",
    "healey": "rochdale", "syke": "rochdale", "cutgate": "rochdale",
    "darnhill": "heywood", "hopwood": "heywood",
    "alkrington": "middleton", "boarshaw": "middleton",
    "newhey": "milnrow", "slattocks": "milnrow",
    "smithy_bridge": "littleborough", "summit": "littleborough",
    "wardle": "littleborough", "norden": "rochdale", "bamford": "rochdale",
    "castleton": "rochdale",
}

# Categories where a curated photograph must never be used, and the generated
# card is the only acceptable illustration.
#
# A photograph of a real place behind a headline about an alleged offence says
# something the story does not: that this location is connected to the crime.
# On an appeal naming an individual it is worse, because the reader joins the
# name and the building unprompted. Where premises or passers-by are
# identifiable, that is an accuracy complaint under the Editors' Code and a
# defamation risk to whoever owns them.
#
# Text matching cannot separate "the incident happened here" from "the town was
# mentioned in passing", so no photograph can be placed safely by machine. A
# plain branded card carries no such implication, which is why newsrooms use one
# when they have no police-issued image.
NO_PHOTO_CATEGORIES = frozenset({"crime"})

AREAS_DIR = Path("assets/img/areas")
PLACES_DIR = Path("assets/img/places")
PEOPLE_DIR = Path("assets/img/people")
CREDITS_PATH = AREAS_DIR / "credits.json"
PLACES_CREDITS_PATH = PLACES_DIR / "credits.json"
PEOPLE_CREDITS_PATH = PEOPLE_DIR / "credits.json"
_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")

# Purely grammatical words. A filename must yield a phrase of at least two
# tokens with at least one real word, so a single generic name can't match
# everything — but genuine place names like "Manchester Road" or "Town Centre"
# must still match.
_WEAK_PLACE_TOKENS = {"the", "of", "and", "in", "at", "on", "a"}


def _place_phrases(stem: str) -> list[str]:
    """Candidate phrases from a filename, longest first.

    ``manchester_road_rochdale`` -> ["manchester road rochdale",
                                     "manchester road", "manchester"]
    """
    tokens = [t for t in re.split(r"[^a-z0-9]+", stem.lower()) if t]
    return [" ".join(tokens[:n]) for n in range(len(tokens), 0, -1)]


def _phrase_is_specific(phrase: str) -> bool:
    tokens = phrase.split()
    if len(tokens) < 2:
        return False
    return any(token not in _WEAK_PLACE_TOKENS for token in tokens)


def find_place_photo(
    text: str,
    places_dir: Path = PLACES_DIR,
) -> tuple[Path, str] | None:
    """Best place photo whose filename names somewhere the story mentions.

    Files are named after the place, e.g. ``manchester_road_rochdale.jpg`` or
    ``hollingworth_lake_littleborough.jpg``. The longest phrase that actually
    appears in the story wins, so a photo of the specific road beats a generic
    area photo.
    """
    if not places_dir.is_dir():
        return None
    haystack = " " + re.sub(r"[^a-z0-9]+", " ", _clean(text).lower()) + " "
    best: tuple[int, Path, str] | None = None
    for path in sorted(places_dir.iterdir()):
        if path.suffix.lower() not in _IMAGE_SUFFIXES:
            continue
        for phrase in _place_phrases(path.stem):
            if not _phrase_is_specific(phrase):
                continue
            if f" {phrase} " in haystack:
                score = len(phrase.split())
                if best is None or score > best[0]:
                    best = (score, path, phrase)
                break
    if best is None:
        return None
    return best[1], best[2]


def find_person_photo(
    title: str,
    people_dir: Path = PEOPLE_DIR,
) -> tuple[Path, str] | None:
    """Photo of a person named in the HEADLINE.

    Two rules make this stricter than place matching, both for the same reason:
    putting a real person's face on a story is a far bigger claim than putting a
    photograph of a road on it, and getting it wrong is the kind of mistake that
    ends in a complaint or a legal letter.

    1. The headline only, never the body. Someone quoted three paragraphs down
       is not what the story is about, but a card carries no such nuance - it
       just shows their face under a category kicker. Requiring the headline
       means the person is the subject.

    2. The whole filename must match, with no shortening. Place matching walks
       back through shorter phrases so that a photo of a specific road can fall
       back to the town; doing that here would let ``mayor_of_rochdale.jpg``
       match on the fragment "mayor of" and illustrate a story about the mayor
       of Bury. Names are precise, so the match is exact.

    Files are named after the person or the office, e.g. ``paul_waugh.jpg`` or
    ``mayor_of_rochdale.jpg``. Single-word filenames are ignored: a surname on
    its own is far too easy to hit by accident.
    """
    if not people_dir.is_dir():
        return None
    haystack = " " + re.sub(r"[^a-z0-9]+", " ", _clean(title).lower()) + " "
    best: tuple[int, Path, str] | None = None
    for path in sorted(people_dir.iterdir()):
        if path.suffix.lower() not in _IMAGE_SUFFIXES:
            continue
        tokens = [t for t in re.split(r"[^a-z0-9]+", path.stem.lower()) if t]
        if len(tokens) < 2:
            continue
        phrase = " ".join(tokens)
        if f" {phrase} " in haystack:
            score = len(tokens)
            if best is None or score > best[0]:
                best = (score, path, phrase)
    if best is None:
        return None
    return best[1], best[2]


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _load_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def _area_slug(area: Any) -> str:
    return _clean(area).lower().replace(" ", "_").replace("-", "_") or "rochdale"


def _pretty_area(area: Any) -> str:
    return _clean(area).replace("_", " ").replace("-", " ").title() or "Rochdale"


def _category_key(category: Any) -> str:
    key = _clean(category).lower()
    return key if key in CATEGORY_STYLE else "news"


def _area_hue(area_slug: str) -> float:
    digest = hashlib.sha256(area_slug.encode("utf-8")).digest()
    return digest[0] / 255.0


def _area_photo(area_slug: str, areas_dir: Path) -> Path | None:
    """Most specific curated photo: exact area -> parent township -> borough."""
    seen: set[str] = set()
    candidate = area_slug
    for _ in range(4):
        if not candidate or candidate in seen:
            break
        seen.add(candidate)
        for suffix in _IMAGE_SUFFIXES:
            path = areas_dir / f"{candidate}{suffix}"
            if path.is_file():
                return path
        candidate = AREA_PARENT.get(candidate, "rochdale" if candidate != "rochdale" else "")
    return None


def _photo_credit(area_slug: str, credits_path: Path) -> str:
    try:
        credits = json.loads(credits_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(credits, dict):
        return ""
    candidate = area_slug
    seen: set[str] = set()
    for _ in range(4):
        if not candidate or candidate in seen:
            break
        seen.add(candidate)
        value = credits.get(candidate)
        if isinstance(value, str) and value.strip():
            return value.strip()
        candidate = AREA_PARENT.get(candidate, "rochdale" if candidate != "rochdale" else "")
    return ""


def _folder_credit(stem: str, directory: Path) -> str:
    """Credit for a curated photo. Absent = the publisher's own photograph.

    Used for both the places and people folders, which share the same flat
    ``credits.json`` keyed by filename without its extension.
    """
    try:
        credits = json.loads((directory / "credits.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(credits, dict):
        return ""
    value = credits.get(stem)
    return value.strip() if isinstance(value, str) else ""


def _photo_background(path: Path) -> Image.Image:
    photo = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    return ImageOps.fit(photo, (WIDTH, HEIGHT), method=Image.Resampling.LANCZOS)


def _generated_background(area_slug: str, accent: tuple[int, int, int]) -> Image.Image:
    """Deterministic dark background: an area-seeded hue blended with the
    category accent, as a soft diagonal so no two (area, category) look alike."""
    hue = _area_hue(area_slug)
    r, g, b = colorsys.hsv_to_rgb(hue, 0.45, 0.22)
    base = (int(r * 255), int(g * 255), int(b * 255))
    top = tuple(int(base[i] * 0.6 + INK[i] * 0.4) for i in range(3))
    bottom = tuple(int(base[i] * 0.5 + accent[i] * 0.18 + INK[i] * 0.32) for i in range(3))

    gradient = Image.new("RGB", (1, HEIGHT))
    for y in range(HEIGHT):
        t = y / HEIGHT
        gradient.putpixel((0, y), tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3)))
    background = gradient.resize((WIDTH, HEIGHT))

    # Soft diagonal wedge in the accent for a bit of geometry.
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    odraw.polygon([(0, HEIGHT), (WIDTH, HEIGHT - 300), (WIDTH, HEIGHT), (0, HEIGHT)],
                  fill=(accent[0], accent[1], accent[2], 40))
    odraw.polygon([(0, 0), (360, 0), (0, 360)], fill=(accent[0], accent[1], accent[2], 26))
    background = Image.alpha_composite(background.convert("RGBA"), overlay).convert("RGB")
    return background


def _scrim(image: Image.Image, accent: tuple[int, int, int], is_photo: bool) -> Image.Image:
    """Darken for legibility; a little heavier over a real photo."""
    scrim = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(scrim)
    top_alpha = 90 if is_photo else 40
    for y in range(HEIGHT):
        t = y / HEIGHT
        alpha = int(top_alpha + (235 - top_alpha) * (t ** 1.6))
        sdraw.line([(0, y), (WIDTH, y)], fill=(INK[0], INK[1], INK[2], alpha))
    out = Image.alpha_composite(image.convert("RGBA"), scrim)
    return out.convert("RGB")


# --- category glyphs (simple line icons drawn with primitives) ---------------
def _glyph_crime(d, x, y, s, c):
    d.polygon([(x, y), (x + s, y), (x + s, y + s * 0.55), (x + s / 2, y + s), (x, y + s * 0.55)], outline=c, width=4)
def _glyph_sport(d, x, y, s, c):
    d.ellipse([x, y, x + s, y + s], outline=c, width=4); d.line([(x, y + s / 2), (x + s, y + s / 2)], fill=c, width=4); d.line([(x + s / 2, y), (x + s / 2, y + s)], fill=c, width=4)
def _glyph_traffic(d, x, y, s, c):
    d.polygon([(x + s / 2, y), (x + s, y + s), (x, y + s)], outline=c, width=4); d.line([(x + s / 2, y + s * 0.4), (x + s / 2, y + s * 0.72)], fill=c, width=4)
def _glyph_transport(d, x, y, s, c):
    d.rounded_rectangle([x, y, x + s, y + s * 0.8], radius=6, outline=c, width=4); d.line([(x, y + s * 0.45), (x + s, y + s * 0.45)], fill=c, width=3); d.ellipse([x + s * 0.15, y + s * 0.7, x + s * 0.32, y + s * 0.87], outline=c, width=3); d.ellipse([x + s * 0.68, y + s * 0.7, x + s * 0.85, y + s * 0.87], outline=c, width=3)
def _glyph_politics(d, x, y, s, c):
    d.line([(x, y + s), (x + s, y + s)], fill=c, width=4); [d.line([(x + s * f, y + s * 0.2), (x + s * f, y + s)], fill=c, width=4) for f in (0.15, 0.5, 0.85)]; d.line([(x, y + s * 0.2), (x + s, y + s * 0.2)], fill=c, width=4)
def _glyph_education(d, x, y, s, c):
    d.polygon([(x + s / 2, y), (x + s, y + s * 0.32), (x + s / 2, y + s * 0.64), (x, y + s * 0.32)], outline=c, width=4); d.line([(x + s, y + s * 0.32), (x + s, y + s * 0.7)], fill=c, width=4)
def _glyph_events(d, x, y, s, c):
    pts = []; import math
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5; r = s / 2 if i % 2 == 0 else s / 4.6
        pts.append((x + s / 2 + r * math.cos(ang), y + s / 2 + r * math.sin(ang)))
    d.polygon(pts, outline=c, width=4)
def _glyph_business(d, x, y, s, c):
    d.rectangle([x, y + s * 0.15, x + s * 0.6, y + s], outline=c, width=4); d.rectangle([x + s * 0.6, y + s * 0.45, x + s, y + s], outline=c, width=4)
def _glyph_community(d, x, y, s, c):
    d.ellipse([x + s * 0.1, y, x + s * 0.4, y + s * 0.3], outline=c, width=4); d.ellipse([x + s * 0.6, y, x + s * 0.9, y + s * 0.3], outline=c, width=4); d.arc([x, y + s * 0.35, x + s * 0.5, y + s * 1.1], 180, 360, fill=c, width=4); d.arc([x + s * 0.5, y + s * 0.35, x + s, y + s * 1.1], 180, 360, fill=c, width=4)
def _glyph_health(d, x, y, s, c):
    d.rectangle([x + s * 0.38, y, x + s * 0.62, y + s], outline=c, width=4, fill=c); d.rectangle([x, y + s * 0.38, x + s, y + s * 0.62], outline=c, width=4, fill=c)
def _glyph_environment(d, x, y, s, c):
    d.line([(x + s / 2, y + s), (x + s / 2, y + s * 0.4)], fill=c, width=4); d.ellipse([x, y, x + s * 0.6, y + s * 0.6], outline=c, width=4); d.ellipse([x + s * 0.4, y + s * 0.1, x + s, y + s * 0.7], outline=c, width=4)
def _glyph_news(d, x, y, s, c):
    d.rectangle([x, y, x + s, y + s], outline=c, width=4); [d.line([(x + s * 0.15, y + s * f), (x + s * 0.85, y + s * f)], fill=c, width=3) for f in (0.3, 0.5, 0.7)]

_GLYPHS: dict[str, Callable] = {
    "crime": _glyph_crime, "sport": _glyph_sport, "traffic": _glyph_traffic,
    "transport": _glyph_transport, "politics": _glyph_politics,
    "education": _glyph_education, "events": _glyph_events,
    "business": _glyph_business, "community": _glyph_community,
    "health": _glyph_health, "environment": _glyph_environment, "news": _glyph_news,
}


def _wrap(draw, text, font, max_width, max_lines):
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = word if not current else f"{current} {word}"
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and words:
        while lines and draw.textlength(lines[-1] + "…", font=font) > max_width:
            lines[-1] = lines[-1].rsplit(" ", 1)[0] if " " in lines[-1] else lines[-1][:-1]
        lines[-1] = lines[-1] + "…"
    return lines


def compose_story_card(
    title: str,
    area: Any,
    category: Any,
    out_path: Path,
    areas_dir: Path = AREAS_DIR,
    credits_path: Path = CREDITS_PATH,
    story_text: str = "",
    places_dir: Path = PLACES_DIR,
    people_dir: Path = PEOPLE_DIR,
) -> tuple[str, str]:
    """Render the card to out_path. Returns (relative_path, image_credit)."""
    area_slug = _area_slug(area)
    cat_key = _category_key(category)
    accent, cat_label = CATEGORY_STYLE[cat_key]
    area_name = _pretty_area(area)

    # Most specific first. A person named in the headline is the subject of the
    # story, so their photograph beats any location; a photo of the actual place
    # named in the story then beats a generic photo of the area.
    photo = None
    credit = "Rochdale Daily"
    if cat_key not in NO_PHOTO_CATEGORIES:
        person_match = find_person_photo(title, people_dir)
        if person_match is not None:
            photo = person_match[0]
            credit = _folder_credit(photo.stem, people_dir) or "Rochdale Daily"
        if photo is None:
            place_match = find_place_photo(f"{title} {story_text}", places_dir)
            if place_match is not None:
                photo = place_match[0]
                credit = _folder_credit(photo.stem, places_dir) or "Rochdale Daily"
        if photo is None:
            photo = _area_photo(area_slug, areas_dir)
            if photo is not None:
                credit = _photo_credit(area_slug, credits_path) or "Rochdale Daily"

    if photo is not None:
        background = _photo_background(photo)
    else:
        background = _generated_background(area_slug, accent)
        credit = "Rochdale Daily"

    canvas = _scrim(background, accent, is_photo=photo is not None)
    draw = ImageDraw.Draw(canvas)

    margin = 72
    # Top accent bar
    draw.rectangle([0, 0, WIDTH, 8], fill=accent)

    # Category kicker + glyph (top-left)
    glyph = _GLYPHS.get(cat_key, _glyph_news)
    glyph(draw, margin, margin, 44, accent)
    kicker_font = _load_font(30, bold=True)
    draw.text((margin + 62, margin + 6), cat_label.upper(), font=kicker_font, fill=accent)

    # Title (wrapped, lower-middle)
    title_font = _load_font(60, bold=True)
    lines = _wrap(draw, _clean(title) or "Rochdale Daily", title_font, WIDTH - margin * 2, 3)
    line_h = 72
    block_h = line_h * len(lines)
    y = HEIGHT - 150 - block_h
    for line in lines:
        draw.text((margin, y), line, font=title_font, fill=(245, 247, 250))
        y += line_h

    # Area tag with pin (bottom-left)
    tag_font = _load_font(28, bold=True)
    area_upper = area_name.upper()
    pin_x, pin_y = margin, HEIGHT - 74
    draw.ellipse([pin_x, pin_y, pin_x + 22, pin_y + 22], outline=GOLD, width=4)
    draw.polygon([(pin_x + 4, pin_y + 16), (pin_x + 11, pin_y + 30), (pin_x + 18, pin_y + 16)], fill=GOLD)
    draw.text((pin_x + 34, pin_y - 4), area_upper, font=tag_font, fill=GOLD)

    # Wordmark (bottom-right)
    brand_font = _load_font(26, bold=True)
    brand = "ROCHDALE DAILY"
    bw = draw.textlength(brand, font=brand_font)
    draw.text((WIDTH - margin - bw, HEIGHT - 74), brand, font=brand_font, fill=(210, 216, 224))

    # Photo credit (tiny, bottom-right under wordmark) when a real photo is used
    if photo is not None and credit:
        credit_font = _load_font(17, bold=False)
        ctext = f"Photo: {credit}"
        cw = draw.textlength(ctext, font=credit_font)
        draw.text((WIDTH - margin - cw, HEIGHT - 42), ctext, font=credit_font, fill=(180, 186, 196))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, "JPEG", quality=88, optimize=True)
    try:
        relative = out_path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        relative = out_path.as_posix()
    return relative, credit
