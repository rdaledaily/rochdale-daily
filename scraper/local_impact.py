"""'What it means for <place>' box for non-crime stories (editor, 12 Nov 2026).

The writer may offer two or three short points saying what the story changes
for people locally. The box only RESTATES the article: every figure and every
proper noun in a point must already be in the published headline, standfirst
or body, which have passed the source-fidelity gate. A point that brings in
anything new is dropped, and a box with fewer than two surviving points is not
shown at all. Nothing is ever substituted to fill it.

The heading varies from story to story (editor: "with variations because
that's repetitive") but is fixed per story, chosen from the slug, so a page
reads the same every time it is regenerated.
"""
from __future__ import annotations

import hashlib
import html
import re
from typing import Any

# Crime, court and police stories never carry the box (house rule: crime is
# reported, not turned into a reader takeaway). Sport and events have their own
# furniture (fixtures, What's On listings).
ELIGIBLE_CATEGORIES = frozenset({
    "news", "community", "business", "traffic", "transport", "environment",
    "education", "politics", "health",
})

# The group a story is about, only when the body itself names that group.
# key -> (display word, evidence the body must contain)
AUDIENCES: dict[str, tuple[str, str]] = {
    "parents": ("parents", r"parents?|mums?|dads?|mothers?|fathers?"),
    "mums": ("mums", r"mums?|mothers?"),
    "drivers": ("drivers", r"drivers?|motorists?"),
    "bus users": ("bus users", r"bus (?:users?|passengers?)|passengers?"),
    "rail passengers": ("rail passengers", r"(?:rail|train) passengers?|passengers?"),
    "tenants": ("tenants", r"tenants?"),
    "pupils": ("pupils", r"pupils?"),
    "students": ("students", r"students?"),
    "patients": ("patients", r"patients?"),
    "businesses": ("businesses", r"businesses|traders?"),
    "families": ("families", r"families"),
    "pensioners": ("pensioners", r"pensioners?|older (?:people|residents)"),
    "carers": ("carers", r"carers?"),
    "cyclists": ("cyclists", r"cyclists?"),
    "shoppers": ("shoppers", r"shoppers?"),
    "fans": ("fans", r"fans|supporters"),
    "dog owners": ("dog owners", r"dog owners?"),
    "householders": ("householders", r"householders?|households?"),
}
AUDIENCE_ENUM = ["", *AUDIENCES]

HEADINGS_PLACE = (
    "What it means for {place}",
    "What changes in {place}",
    "How {place} is affected",
    "Why it matters in {place}",
    "For people in {place}",
    "{place} at a glance",
)
HEADINGS_AUDIENCE = (
    "What it means for {place} {audience}",
    "What changes for {audience} in {place}",
    "How {place} {audience} are affected",
    "For {audience} in {place}",
)

WRITER_INSTRUCTION = (
    "local_impact: for non-crime stories only, up to 3 short points (each one "
    "sentence, 6-30 words) saying plainly what this changes for people in the "
    "story's area: dates, costs, routes, deadlines, who qualifies, where to go. "
    "Every fact must already be stated in your paragraphs; add nothing new. "
    "No questions, no advice in the paper's own voice, no opinion. Set audience "
    "only when the story is specifically about that group and the body names "
    "them; otherwise \"\". Return points [] when the story has no concrete local "
    "change, and always [] for crime, court and police stories."
)

SCHEMA_PROPERTY = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "audience": {"type": "string", "enum": AUDIENCE_ENUM},
        "points": {"type": "array", "maxItems": 3, "items": {"type": "string"}},
    },
    "required": ["audience", "points"],
}

MIN_POINTS = 2
MAX_POINTS = 3
_SENSITIVE_RE = re.compile(
    r"\b(?:police|arrest\w*|charged|court|jailed|sentenced|inquest|died|death|"
    r"killed|stabb\w*|murder\w*|assault\w*|rape|sexual|fatal\w*)\b",
    re.I,
)
_NUMBER_RE = re.compile(r"\d+(?:[.,:]\d+)*")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’-]*")
_STOP = frozenset(
    "the and for with from that this they their there have has will been were "
    "into about which when where while after before also more than over under "
    "people residents".split()
)


def _plain(value: Any) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return " ".join(html.unescape(text).split())


def place_label(area: str, article_text: str) -> str:
    """Display name for the story's area key, e.g. smithy_bridge -> Smithy Bridge.
    An area the article never names is shown as the borough town instead."""
    key = str(area or "").strip().lower()
    label = " ".join(part.capitalize() for part in key.replace("_", " ").split())
    if not label or label.lower() not in article_text.lower():
        return "Rochdale"
    return label


# A figure with whatever is glued to it (2.5m, 10.29am, 21%), and the word that
# follows it, so "15 days" can never borrow the 15 from "15 January" and "£2.5"
# can never borrow from "£2.5m".
_FIGURE_RE = re.compile(r"(?<![\w.,:])(\d+(?:[.,:]\d+)*[a-z%]*)(?![\w])(?:\W+([A-Za-z]+))?", re.I)
_NEGATION_RE = re.compile(
    r"\b(?:not|no|never|none|nobody|nothing|neither|nor|without|cannot|unable)\b|n[’']t\b", re.I
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
MIN_OVERLAP = 0.5


def _stem(word: str) -> str:
    word = word.lower().replace("’", "'")
    word = re.sub(r"'s$", "", word)
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word


def _content(text: str) -> set[str]:
    return {_stem(w) for w in _WORD_RE.findall(text) if len(w) >= 3 and w.lower() not in _STOP}


def _figures(text: str) -> list[tuple[str, str]]:
    """[(figure, following word)] with the figure's thousands commas removed."""
    return [(m.group(1).replace(",", "").lower(), _stem(m.group(2) or "")) for m in _FIGURE_RE.finditer(text)]


def _sentences(article_parts: list[str]) -> list[str]:
    out: list[str] = []
    for part in article_parts:
        out.extend(s for s in _SENTENCE_SPLIT_RE.split(_plain(part)) if s.strip())
    return out


def _matches_sentence(point: str, sentence: str) -> bool:
    # Every figure comes from this one sentence, with the same word after it
    # when both have one.
    available = _figures(sentence)
    for figure, after in _figures(point):
        if not any(f == figure and (not after or not a or after == a or after in _STOP or a in _STOP)
                   for f, a in available):
            return False
    # "will not close" and "will close" are opposite facts.
    if bool(_NEGATION_RE.search(point)) != bool(_NEGATION_RE.search(sentence)):
        return False
    # Mostly the sentence's own words.
    content = _content(point)
    if not content:
        return False
    return len(content & _content(sentence)) / len(content) >= MIN_OVERLAP


CORRECTION_OVERLAP = 0.5


def corrected(point: str, sentences: list[str]) -> str | None:
    """Editor, 14 Nov 2026: "Change them, don't block them." A point that gets a
    fact wrong is replaced by the story sentence it was restating, word for
    word, so the box can only ever repeat what the checked story says. The
    sentence is chosen by shared words, ignoring the figures and negatives the
    point got wrong; if no sentence is clearly the one (at least half the
    point's words), there is nothing safe to change it to and it is dropped."""
    content = _content(point)
    if not content:
        return None
    # The figure the point misquoted ("£2.5" for "£2.5m") says which sentence
    # it came from, so a sentence holding those digits ranks higher.
    digits = {re.sub(r"[^\d.]", "", f) for f, _ in _figures(point)}
    best, best_rank = None, 0.0
    for sentence in sentences:
        overlap = len(content & _content(sentence)) / len(content)
        held = {re.sub(r"[^\d.]", "", f) for f, _ in _figures(sentence)}
        rank = overlap + (0.5 * len(digits & held) / len(digits) if digits else 0.0)
        if (overlap >= CORRECTION_OVERLAP / 2 or digits & held) and rank > best_rank:
            best, best_rank = sentence, rank
    if best is None or best_rank < CORRECTION_OVERLAP:
        return None
    best = best.strip()
    if not best.endswith((".", "!", "?")):
        best += "."
    n_words = len(best.split())
    if n_words < 6 or n_words > 30 or "?" in best or "!" in best or _SENSITIVE_RE.search(best):
        return None
    return best


def _grounded(point: str, article_text: str, sentences: list[str]) -> bool:
    """A point must restate ONE sentence of the article: its figures (whole, with
    the same unit), its negatives and most of its words all come from that
    sentence. Facts from different sentences cannot be stitched together, which
    is how a consultation's closing date became a library's (14 Nov 2026 test)."""
    low = article_text.lower()
    # Every proper noun (a capitalised word that does not open the sentence).
    words = _WORD_RE.findall(point)
    for index, word in enumerate(words):
        if index and word[0].isupper() and word.lower() not in low:
            return False
    return any(_matches_sentence(point, sentence) for sentence in sentences)


def build(
    draft_impact: Any,
    *,
    title: str,
    excerpt: str,
    paragraphs: list[str],
    category: str,
    area: str,
    sensitive: bool = False,
    police_matter: bool = False,
) -> dict[str, Any] | None:
    """Return {'place','audience','points'} or None when no box should show."""
    if sensitive or police_matter or str(category or "").lower() not in ELIGIBLE_CATEGORIES:
        return None
    if _SENSITIVE_RE.search(_plain(title)):
        return None
    if not isinstance(draft_impact, dict):
        return None
    article_text = _plain(" ".join([title, excerpt, *paragraphs]))
    sentences = _sentences([title, excerpt, *paragraphs])
    # Corrections come from the body only: the headline is never repeated.
    body_sentences = _sentences([excerpt, *paragraphs])
    points: list[str] = []
    seen: set[str] = set()
    for raw in draft_impact.get("points") or []:
        point = _plain(raw).strip(" -•*")
        if not point:
            continue
        if not point.endswith((".", "!", "?")):
            point += "."
        n_words = len(point.split())
        if n_words < 6 or n_words > 30 or "?" in point or "!" in point:
            continue
        if _SENSITIVE_RE.search(point):
            continue
        if not _grounded(point, article_text, sentences):
            point = corrected(point, body_sentences)
            if point is None:
                continue
        key = point.casefold()
        if key in seen:
            continue
        # A point that only repeats the headline tells the reader nothing.
        if key.rstrip(".") == _plain(title).casefold():
            continue
        seen.add(key)
        points.append(point)
        if len(points) >= MAX_POINTS:
            break
    if len(points) < MIN_POINTS:
        return None
    audience = ""
    wanted = str(draft_impact.get("audience") or "").strip().lower()
    if wanted in AUDIENCES:
        word, evidence = AUDIENCES[wanted]
        if re.search(r"\b(?:" + evidence + r")\b", article_text, re.I):
            audience = word
    return {"place": place_label(area, article_text), "audience": audience, "points": points}


def heading(slug: str, place: str, audience: str = "") -> str:
    choices = HEADINGS_AUDIENCE if audience else HEADINGS_PLACE
    index = int(hashlib.sha1(str(slug or place).encode("utf-8")).hexdigest(), 16) % len(choices)
    return choices[index].format(place=place, audience=audience)


def render(impact: dict[str, Any] | None, slug: str) -> str:
    if not impact or len(impact.get("points") or []) < MIN_POINTS:
        return ""
    title = heading(slug, impact["place"], impact.get("audience") or "")
    items = "".join(f"<li>{html.escape(point)}</li>" for point in impact["points"])
    return (
        # A <section>, not an <aside>: closing_filler_sweep.py and
        # archive_quality.py end the story region at the first <aside>, so an
        # aside mid-article would hide the real ending from them.
        '<section class="rd-impact" aria-label="' + html.escape(title, quote=True) + '">'
        f'<h2 class="rd-impact-title">{html.escape(title)}</h2>'
        f'<ul class="rd-impact-list">{items}</ul></section>'
    )


def paragraphs_with_box(paragraph_html: list[str], box_html: str) -> str:
    """The box closes the report, before any useful links. Measured on a live
    story (12 Nov 2026): placed after paragraph 2 it sat directly above the
    paragraph it restates, so the reader met the same fact twice in a row."""
    return "".join(paragraph_html) + (box_html or "")
