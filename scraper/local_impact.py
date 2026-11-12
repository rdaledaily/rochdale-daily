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


def _grounded(point: str, article_text: str, article_tokens: set[str]) -> bool:
    low = article_text.lower()
    # Every figure, date and time must already be in the article.
    for number in _NUMBER_RE.findall(point):
        if number not in article_text:
            return False
    # Every proper noun (a capitalised word that does not open the sentence).
    words = _WORD_RE.findall(point)
    for index, word in enumerate(words):
        if index and word[0].isupper() and word.lower() not in low:
            return False
    # And the point must plainly be about this article.
    content = {w.lower() for w in words if len(w) >= 4 and w.lower() not in _STOP}
    return len(content & article_tokens) >= 2


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
    article_tokens = {w.lower() for w in _WORD_RE.findall(article_text) if len(w) >= 4}
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
        key = point.casefold()
        if key in seen or not _grounded(point, article_text, article_tokens):
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
