"""Background for short stories: the history, the people and the local picture.

Measured 24 Oct 2026: 116 of 363 live stories were under 200 words, and the
rewrite-time context search (context_research.py) had found nothing extra for
418 of 418 records. A short story about Dale or the Hornets said nothing about
who they are; a roadworks notice never said whose ward the street is in.

This adds a "Background" box to short stories, built only from two checked
sources, never from a model:

  * story_facts.json: finished, cited sentences about the subjects the paper
    covers most (Rochdale AFC, the Hornets, the council, the towns, the
    foodbank, Springhill Hospice ...). The editor can change any of them.
  * council_roster.json: who represents the ward the story names.

Nothing is invented, and the same story always gets the same box, so pages do
not churn between runs. Subjects are matched on the headline and the opening
paragraph, so a passing mention does not pull in an unrelated fact; a fact is
chosen for the story by its topic words, and is skipped if the story already
says it. Sponsored copy, briefings, crime, missing-person appeals, sensitive
stories and party-political items never get a box: background beside those
implies a connection or a judgement the paper has not made.

Added when the page is built, never stored. The box carries
data-rd-background="1"; archive_quality and archive_integrity strip it before
reading a body back, so it cannot stack.
"""
from __future__ import annotations

import hashlib
import html as _html
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FACTS_FILE = ROOT / "story_facts.json"
ROSTER_FILE = ROOT / "council_roster.json"
WORD_LIMIT = 250            # stories this short get a box
MAX_FACTS = 3
MAX_SUBJECTS = 2
# council_roster.json lists the councillors elected in May 2026; a story from
# before then may have had different ones.
ROSTER_FROM = "2026-05-08"
COUNCILLORS_URL = "https://democracy.rochdale.gov.uk/mgMemberIndex.aspx"

BOX_RE = re.compile(r'<div\b[^>]*data-rd-background=["\']1["\'][^>]*>.*?</div>', re.S)

_EXCLUDE_TITLE = re.compile(
    r"\b(?:arrest\w*|charged|charges?|court|trial|jail\w*|sentenc\w*|murder\w*|stab\w*|assault\w*|police|"
    r"abuse\w*|racis[mt]|racial|groom\w*|rap(?:e|ist)\w*|sexual\w*|exploitation|inquest|fatal\w*|died|death\w*|"
    r"killed|suicide|missing|tobacco|liquidation|"
    r"reform uk|restore britain|labour|conservative|lib dem\w*|green party|election|candidate|mp\b|lawmaker)\b",
    re.I,
)


def _plain(value: Any) -> str:
    return " ".join(_html.unescape(re.sub(r"<[^>]+>", " ", str(value or ""))).split())


def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


_FACTS: dict[str, Any] = {}


def _subjects(root: Path) -> list[dict[str, Any]]:
    key = str(root)
    if key not in _FACTS:
        data = _load(root / FACTS_FILE.name, {})
        _FACTS[key] = data.get("subjects", []) if isinstance(data, dict) else []
    return _FACTS[key]


def word_count(article: dict[str, Any]) -> int:
    return len(re.findall(r"\b[\w’'-]+\b", _plain(article.get("content_html"))))


def eligible(article: dict[str, Any]) -> bool:
    if article.get("sponsored") or article.get("briefing_slot") or article.get("police_matter"):
        return False
    if article.get("sensitive_story") or article.get("event_start_at"):
        return False
    if str(article.get("source_kind") or "") == "event":
        return False
    category = str(article.get("category") or "").lower()
    if category in {"crime", "events", "politics"}:
        return False
    title = str(article.get("title") or "")
    if title.lower().startswith(("sponsored", "morning briefing", "evening briefing")):
        return False
    if _EXCLUDE_TITLE.search(title):
        return False
    try:
        from inline_related import JUNK_TITLE
        if JUNK_TITLE.search(title):
            return False
    except ImportError:
        pass
    return word_count(article) < WORD_LIMIT


def _headline(article: dict[str, Any]) -> str:
    return _plain(article.get("title"))


def _words(text: str) -> set[str]:
    return {w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9-]+", text)}


def _already_said(fact: str, body: str) -> bool:
    """The story already carries this fact: every number in it, or most of its words."""
    # Recent years appear in almost every story, so they prove nothing.
    numbers = [n for n in re.findall(r"\d[\d,.]*\d|\d", fact) if not re.fullmatch(r"202[4-9]", n)]
    if numbers and sum(bool(re.search(r"(?<![\d,.])" + re.escape(n) + r"(?![\d])", body)) for n in numbers) * 2 >= len(numbers):
        return True
    fact_words = {w for w in _words(fact) if len(w) > 4}
    return bool(fact_words) and len(fact_words & _words(body)) / len(fact_words) > 0.7


def _story_date(article: dict[str, Any]) -> str:
    for key in ("first_published_at", "published_at", "source_published_at"):
        value = str(article.get(key) or "")
        if re.match(r"\d{4}-\d{2}-\d{2}", value):
            return value[:10]
    return ""


def _stable(slug: str, fact_id: str) -> int:
    return int(hashlib.sha1(f"{slug}:{fact_id}".encode()).hexdigest()[:8], 16)


def choose_facts(article: dict[str, Any], root: Path = ROOT) -> list[dict[str, Any]]:
    # The headline decides what a story is about. Matching the body pulled in
    # a Milnrow fact because one school in a foodbank story was in Milnrow.
    lead = _headline(article)
    body = _plain(article.get("content_html"))
    story_text = (_plain(article.get("title")) + " " + body).lower()
    story_words = _words(story_text)
    slug = str(article.get("slug") or "")
    when = _story_date(article)
    matched = []
    for position, subject in enumerate(_subjects(root)):
        found = re.search(subject.get("match") or r"(?!)", lead, re.I)
        if not found:
            continue
        if subject.get("exclude") and re.search(subject["exclude"], lead, re.I):
            continue
        matched.append((found.start(), position, subject))
    matched.sort(key=lambda row: (row[0], row[1]))     # the subject the headline leads with
    chosen: list[dict[str, Any]] = []
    for _, _, subject in matched[:MAX_SUBJECTS]:
        ranked = []
        for fact in subject.get("facts", []):
            if _already_said(fact["text"], body):
                continue
            # "Dale returned to the Football League in May 2026" must never sit
            # beside a 2025 National League report.
            if fact.get("from") and (not when or when < fact["from"]):
                continue
            topics = [t.lower() for t in fact.get("topics", [])]
            # Capped at 2 so one broad fact does not win every story; among
            # equally relevant facts the choice rotates by story (stable).
            relevance = min(2, sum(1 for t in topics if (t in story_text if " " in t else t in story_words)))
            # A fact must bear on this story: its topic words appear in it, or it
            # is the subject's "core" fact (who they are). A loosely related
            # fact makes a story look padded, which is the opposite of the aim.
            if not relevance and not fact.get("core"):
                continue
            ranked.append((-relevance, _stable(slug, fact["id"]), fact))
        ranked.sort(key=lambda row: (row[0], row[1]))
        # The lead subject gets two facts, a second subject one.
        take = min(2 if not chosen else 1, int(subject.get("max_facts") or 2))
        chosen.extend(fact for _, _, fact in ranked[:take])
        if len(chosen) >= MAX_FACTS:
            break
    return chosen[:MAX_FACTS]


def ward_line(article: dict[str, Any], root: Path = ROOT) -> tuple[str, dict[str, str]] | None:
    """Who represents the ward the story is about: one ward, firmly identified."""
    try:
        from editorial_contract import ward_decision
        decision = ward_decision(article)
    except Exception:
        return None
    if str(article.get("category") or "").lower() in {"sport", "events", "health"}:
        return None
    if _story_date(article) < ROSTER_FROM:
        return None                     # a ward is context for local issues, not fixtures
    wards = decision.get("wards") or []
    if len(wards) != 1 or decision.get("status") not in {"explicit-ward", "postcode-verified", "named-locality"}:
        return None
    ward = wards[0]
    # The headline must name the place, so a borough-wide story that mentions
    # one library in passing is not pinned to that ward.
    headline = _headline(article).lower()
    places = {ward.lower(), *[part.strip() for part in re.split(r",| and ", ward.lower())]}
    try:
        from selection_policy import AREA_TO_WARD
        places |= {locality for locality, mapped in AREA_TO_WARD.items() if mapped == ward}
    except ImportError:
        pass
    if not any(re.search(r"\b" + re.escape(place) + r"\b", headline) for place in places if len(place) > 3):
        return None
    roster = _load(root / ROSTER_FILE.name, {})
    names = [c["name"] for c in roster.get("councillors", []) if c.get("ward") == ward and c.get("name")]
    if len(names) != 3:
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", ward.lower()).strip("-")
    link = f'<a href="/wards/{slug}">{_html.escape(ward)}</a>'
    text = (f"Local councillors for the {link} ward are "
            f"{_html.escape(names[0])}, {_html.escape(names[1])} and {_html.escape(names[2])}.")
    return text, {"title": "Councillors by ward - Rochdale Borough Council", "url": COUNCILLORS_URL}


def _pointer(article: dict[str, Any]) -> str:
    """One internal link to the listing that answers the reader's next question."""
    category = str(article.get("category") or "").lower()
    title = str(article.get("title") or "")
    if category == "traffic" and re.search(r"roadworks?|road closure|closed|closure", title, re.I):
        return 'Every current council roadworks notice is listed on our <a href="/roadworks">Roadworks in Rochdale</a> page.'
    if category not in {"traffic", "transport", "sport"} and re.search(
            r"\b(?:party|pantomime|panto|festival|celebration|open day|sessions|events?|services and events)\b", title, re.I):
        return 'More things to do across the borough are on our <a href="/whats-on">What\'s On</a> page.'
    return ""


def box(article: dict[str, Any], root: Path = ROOT) -> str:
    """The Background box for one story, or '' when there is nothing checked to add."""
    if not eligible(article):
        return ""
    facts = choose_facts(article, root)
    paragraphs = [_html.escape(f["text"]) for f in facts]
    sources = [f["source"] for f in facts]
    ward = ward_line(article, root)
    if ward:
        paragraphs.append(ward[0])
        sources.append(ward[1])
    if not paragraphs:
        return ""
    pointer = _pointer(article)
    if pointer:
        paragraphs.append(pointer)
    seen, links = set(), []
    for source in sources:
        if source["url"] in seen:
            continue
        seen.add(source["url"])
        links.append(f'<a href="{_html.escape(source["url"], quote=True)}" rel="noopener">{_html.escape(source["title"])}</a>')
    return (
        '<div class="rd-background" data-rd-background="1"><h2>Background</h2>'
        + "".join(f"<p>{p}</p>" for p in paragraphs)
        + f'<p class="rd-background-sources">Background sources: {"; ".join(links)}</p></div>'
    )


def strip(content_html: str) -> str:
    return BOX_RE.sub("", content_html)


def insert(content_html: str, article: dict[str, Any], root: Path = ROOT) -> str:
    """Place the box after the story and before the reader question, if any."""
    content_html = strip(content_html)
    markup = box(article, root)
    if not markup:
        return content_html
    ending = re.search(r'<p\b[^>]*data-rd-reader-ending=["\']1["\']', content_html)
    if ending:
        return content_html[:ending.start()] + markup + content_html[ending.start():]
    return content_html.rstrip() + markup
