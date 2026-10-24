"""In-text "Read more" links between genuinely related stories.

Measured 24 Oct 2026: 305 of 391 live pages already linked inside the text to
place and topic hubs (internal_links.py) and every page had a related block
after the text, but only 15 linked to another story from inside the text.
This adds up to three "Read more:" lines inside each live story (after the
2nd, 4th and 6th paragraphs, so short stories get fewer), pointing at the most
closely related stories, live or archived.

A link inside a story implies a real connection, so the bar is strict and
was tuned against the real feed:
  * headlines must share a distinctive word: at least one shared word appears
    in no more than ANCHOR_MAX_HEADLINES of the paper's ~2,100 headlines
    ("Hopwood", "Spudbros", "eclipse"), and the shared words together score
    MIN_SCORE on rarity (so "October", "family", "road" alone never link);
  * crime, police matters and sensitive subjects are excluded on BOTH sides:
    a "Read more" beside an unrelated court case implies a connection;
  * events, sponsored copy, briefings, retired or non-indexable pages, social
    posts, advertising pages and near-duplicate archive copies are never
    targets.

Added when the page is built, never stored. The lines carry
class="rd-related-inline", which archive_quality and archive_integrity
already strip before reading a body back, so they cannot stack or churn.
"""
from __future__ import annotations

import html as _html
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ANCHOR_MAX_HEADLINES = 8
MIN_SCORE = 10.0
MAX_LINKS = 3
AFTER_PARAGRAPHS = (2, 4, 6)

_STOP = frozenset(
    "a an the and or but of in on at to for by from with as is are was be been after over amid into its "
    "their his her this that these those new more than how why what when who where which will can could "
    "would should may might has have had not no all any every each some just also out up off about across "
    "near following before during while then there here rochdale borough local residents people year years "
    "week weeks day days month update latest news".split()
)
SENSITIVE = re.compile(
    r"\b(?:arrest\w*|charged|charges?|court|jail\w*|sentenc\w*|murder\w*|stab\w*|assault\w*|police|"
    r"abuse\w*|groom\w*|rap(?:e|ist)\w*|sexual\w*|predator\w*|exploitation|inquest|fatal\w*|died|death\w*|"
    r"killed|suicide|missing)\b",
    re.I,
)
JUNK_TITLE = re.compile(
    r"!|^(?:our|we|i)\b|\b(?:our|we're|we are)\b|linkedin|facebook|instagram|tiktok|"
    r"\bservices? (?:available|respond|offered|in)\b|unblock\w*|plumb\w*|locksmith\w*|removals?\b|"
    r"\b(?:watch|stream\w*) (?:live|online|free)\b",
    re.I,
)


def _tokens(title: str) -> set[str]:
    from headline_style import ALWAYS_CAPITAL, PLACES
    out: set[str] = set()
    for word in re.findall(r"[a-z][a-z’']+", str(title or "").lower()):
        word = re.sub(r"[’']s$", "", word)
        if len(word) >= 4 and word not in _STOP and word not in PLACES and word not in ALWAYS_CAPITAL:
            out.add(word[:-1] if word.endswith("s") and len(word) > 5 else word)
    return out


def _excluded_source(article: dict[str, Any]) -> bool:
    category = str(article.get("category") or "").lower()
    return (
        category in {"crime", "events"}
        or bool(article.get("police_matter") or article.get("sponsored") or article.get("briefing_slot"))
        or bool(article.get("event_start_at"))
        or str(article.get("status") or "published") != "published"
        or bool(article.get("requires_approval"))
        or bool(SENSITIVE.search(str(article.get("title") or "")))
    )


def _retired_slugs(root: Path) -> set[str]:
    retired: set[str] = set()
    try:
        for line in (root / "_redirects").read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0].startswith("/articles/"):
                retired.add(parts[0][len("/articles/"):].removesuffix(".html"))
    except OSError:
        pass
    return retired


def _indexable_page(root: Path, slug: str) -> bool:
    try:
        head = (root / "articles" / f"{slug}.html").read_text(encoding="utf-8")[:6000]
    except OSError:
        return False
    if "noindex" in head or "Redirecting to Rochdale Daily" in head:
        return False
    canonical = re.search(r'rel="canonical" href="([^"]+)"', head)
    return bool(canonical) and canonical.group(1).rstrip("/").removesuffix(".html").endswith("/" + slug)


class Index:
    def __init__(self, articles: list[dict[str, Any]], root: Path = ROOT) -> None:
        try:
            archive = json.loads((root / "archive-index.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            archive = []
        if not isinstance(archive, list):
            archive = []
        titles = [str(a.get("title") or "") for a in articles] + [str(e.get("title") or "") for e in archive]
        self.df = Counter(word for title in titles for word in _tokens(title))
        self.n = max(1, len(titles))
        retired = _retired_slugs(root)
        live = {str(a.get("slug") or "") for a in articles}
        self.targets: dict[str, tuple[str, set[str]]] = {}
        for article in articles:
            slug, title = str(article.get("slug") or ""), str(article.get("title") or "")
            if slug and slug not in retired and not _excluded_source(article) and not JUNK_TITLE.search(title):
                self.targets[slug] = (title, _tokens(title))
        for entry in archive:
            slug, title = str(entry.get("slug") or ""), str(entry.get("title") or "")
            if not slug or slug in live or slug in retired or slug in self.targets:
                continue
            if str(entry.get("category") or "").lower() in {"crime", "events"}:
                continue
            if SENSITIVE.search(title) or JUNK_TITLE.search(title) or not _indexable_page(root, slug):
                continue
            self.targets[slug] = (title, _tokens(title))

    def idf(self, word: str) -> float:
        return math.log(self.n / (1 + self.df[word]))

    def related(self, article: dict[str, Any], limit: int = MAX_LINKS) -> list[tuple[str, str]]:
        if _excluded_source(article):
            return []
        own_slug = str(article.get("slug") or "")
        own = _tokens(article.get("title") or "")
        scored = []
        for slug, (title, words) in self.targets.items():
            if slug == own_slug:
                continue
            shared = own & words
            if not shared or min(self.df[w] for w in shared) > ANCHOR_MAX_HEADLINES:
                continue
            score = sum(self.idf(w) for w in shared)
            if score >= MIN_SCORE:
                scored.append((score, slug, title, words))
        scored.sort(key=lambda row: (-row[0], row[1]))
        chosen: list[tuple[str, str, set[str]]] = []
        for _, slug, title, words in scored:
            # Archive copies of one story ("Construction begins at Birch
            # Business Park" x3) count once.
            if any(len(words & taken) / max(1, min(len(words), len(taken))) >= 0.8 for _, _, taken in chosen):
                continue
            chosen.append((slug, title, words))
            if len(chosen) == limit:
                break
        return [(slug, title) for slug, title, _ in chosen]


_CACHE: dict[int, Index] = {}


def index_for(articles: list[dict[str, Any]]) -> Index:
    key = id(articles)
    if key not in _CACHE:
        _CACHE.clear()
        _CACHE[key] = Index(articles)
    return _CACHE[key]


def insert(content_html: str, article: dict[str, Any], all_articles: list[dict[str, Any]]) -> str:
    """Place up to three Read more lines after paragraphs 2, 4 and 6."""
    links = index_for(all_articles).related(article)
    if not links:
        return content_html
    ends = [m.end() for m in re.finditer(r"</p>", content_html, re.I)]
    slots = [ends[n - 1] for n in AFTER_PARAGRAPHS if n <= len(ends) - 1]  # never after the last paragraph
    out, position = [], 0
    for at, (slug, title) in zip(slots, links):
        out.append(content_html[position:at])
        out.append(
            f'<p class="rd-related-inline">Read more: '
            f'<a href="/articles/{_html.escape(slug, quote=True)}.html">{_html.escape(title)}</a></p>'
        )
        position = at
    out.append(content_html[position:])
    return "".join(out)
