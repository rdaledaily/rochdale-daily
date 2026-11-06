"""Series links: stories on one running topic point at each other.

Christmas is the case that prompted this (6 Nov 2026). The paper runs it as
many separate stories: a switch-on, the road closures for it, the panto, a
festival, a ball, the parking. Measured on the live feed that day, 12 live
Christmas stories carried 37 related links between them and 3 pointed at
another Christmas story; the Heywood Christmas Festival page's related
reporting led with an abuse trial. The two existing linkers cannot see a
series: inline_related.py excludes events (most of a season is events and
road closures) and needs a RARE shared headline word, and "Christmas" is in
too many headlines to count as rare.

So a series is named, not guessed: story_series.json lists the running
topics, each a headline pattern plus a window in days so this year's season
never links to last year's. An editor can also put "series": "<id>" (or a
list of ids) on a manual article to add it to a series whatever its headline
says.

At the end of the copy (after the reader question, if any) a member gets one
line:  Enjoyed this article? We think you'll find A, B and C interesting.

Rules, both sides:
  * crime, police matters, sensitive headlines (inline_related.SENSITIVE),
    sponsored copy, briefings, unpublished or approval-held stories never
    join a series. A Christmas page must not recommend a court case, and an
    advert must not be presented as editorial recommendation;
  * same town first, then nearest in time, so every member is linked to;
  * near-identical copies of one story count once;
  * a story already linked inside the copy is not repeated;
  * no members in the window, no line. Nothing is padded with other stories.

Added when the page is built, never stored. The line carries
class="rd-series-links", which archive_quality and archive_integrity strip
before reading a body back, so it cannot stack.
"""
from __future__ import annotations

import html as _html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "story_series.json"
MAX_LINKS = 3
CLASS = "rd-series-links"
STRIP_RE = re.compile(r'<p\b[^>]*class=["\']rd-series-links["\'][^>]*>.*?</p>', re.S)

_CONFIG_CACHE: dict[str, Any] = {}


def load_series(path: Path = CONFIG_PATH) -> list[dict[str, Any]]:
    key = str(path)
    if key not in _CONFIG_CACHE:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        out = []
        for entry in (raw.get("series") or []) if isinstance(raw, dict) else []:
            try:
                out.append({
                    "id": str(entry["id"]).strip().lower(),
                    "label": str(entry.get("label") or entry["id"]),
                    "pattern": re.compile(str(entry["pattern"]), re.I),
                    "window_days": int(entry.get("window_days") or 60),
                })
            except (KeyError, TypeError, ValueError, re.error):
                continue
        _CONFIG_CACHE[key] = out
    return _CONFIG_CACHE[key]


def strip(content_html: str) -> str:
    return STRIP_RE.sub("", content_html)


def _when(article: dict[str, Any]) -> datetime | None:
    stamp = str(article.get("first_published_at") or article.get("published_at") or "")
    if not stamp:
        return None
    try:
        value = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _excluded(article: dict[str, Any]) -> bool:
    from inline_related import SENSITIVE
    category = str(article.get("category") or "").lower()
    return (
        category == "crime"
        or bool(article.get("police_matter") or article.get("sponsored") or article.get("briefing_slot"))
        or str(article.get("status") or "published") != "published"
        or bool(article.get("requires_approval"))
        or bool(SENSITIVE.search(str(article.get("title") or "")))
    )


def _explicit(article: dict[str, Any]) -> set[str]:
    raw = article.get("series")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return set()
    return {str(v).strip().lower() for v in raw if str(v).strip()}


def memberships(article: dict[str, Any], series: list[dict[str, Any]] | None = None) -> set[str]:
    """Ids of every series this story belongs to (empty when excluded)."""
    if _excluded(article):
        return set()
    series = load_series() if series is None else series
    known = {s["id"] for s in series}
    title = str(article.get("title") or "")
    found = {s["id"] for s in series if s["pattern"].search(title)}
    return found | (_explicit(article) & known)


def _area(article: dict[str, Any]) -> str:
    area = str(article.get("area") or "").strip().lower().replace("_", " ")
    return "" if area in {"", "rochdale", "borough", "greater manchester"} else area


def _words(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", title.lower()) if len(w) > 2}


def _near_duplicate(a: set[str], b: set[str]) -> bool:
    # "Road closures for Milnrow Remembrance Sunday" and the Norden one share
    # 6 of 7 words but are different stories: different named places are
    # never copies of each other.
    from headline_style import PLACES
    places_a, places_b = a & PLACES, b & PLACES
    if places_a and places_b and places_a != places_b:
        return False
    return len(a & b) / max(1, min(len(a), len(b))) >= 0.8


def related(article: dict[str, Any], all_articles: list[dict[str, Any]],
            series: list[dict[str, Any]] | None = None, limit: int = MAX_LINKS) -> list[tuple[str, str]]:
    series = load_series() if series is None else series
    mine = memberships(article, series)
    if not mine:
        return []
    when = _when(article)
    if when is None:
        return []
    windows = {s["id"]: s["window_days"] for s in series}
    own_slug = str(article.get("slug") or "")
    own_words = _words(str(article.get("title") or ""))
    own_area = _area(article)
    try:
        from generate_pages import article_should_noindex
    except Exception:  # pragma: no cover - only absent in isolated tests
        article_should_noindex = lambda _a: False  # noqa: E731

    pool = []
    for other in all_articles:
        slug = str(other.get("slug") or "")
        if not slug or slug == own_slug:
            continue
        shared = memberships(other, series) & mine
        if not shared:
            continue
        other_when = _when(other)
        if other_when is None:
            continue
        gap = abs((other_when - when).total_seconds()) / 86400
        if gap > max(windows[s] for s in shared):
            continue
        if article_should_noindex(other):
            continue
        same_area = bool(own_area) and _area(other) == own_area
        pool.append((not same_area, gap, -other_when.timestamp(), slug, str(other.get("title") or "").strip()))

    # Same town first, then the stories closest in time. Newest-first was
    # measured on the live feed and sent all eight Christmas pages to the same
    # three stories, leaving the older members with no incoming link at all;
    # nearest-in-time spreads the links so every member is reachable.
    pool.sort()
    chosen: list[tuple[str, str, set[str]]] = []
    for *_, slug, title in pool:
        words = _words(title)
        if not title or _near_duplicate(words, own_words):
            continue  # another copy of this very story is not a recommendation
        if any(_near_duplicate(words, taken) for _, _, taken in chosen):
            continue
        chosen.append((slug, title, words))
        if len(chosen) == limit:
            break
    return [(slug, title) for slug, title, _ in chosen]


def _join(links: list[str]) -> str:
    if len(links) == 1:
        return links[0]
    return ", ".join(links[:-1]) + " and " + links[-1]


def markup(links: list[tuple[str, str]]) -> str:
    if not links:
        return ""
    anchors = [
        f'<a href="/articles/{_html.escape(slug, quote=True)}">{_html.escape(title)}</a>'
        for slug, title in links
    ]
    return (
        f'<p class="{CLASS}">Enjoyed this article? We think you’ll find '
        f'{_join(anchors)} interesting.</p>'
    )


def insert(content_html: str, article: dict[str, Any], all_articles: list[dict[str, Any]]) -> str:
    """Append the series line at the very end of the copy."""
    content_html = strip(content_html)
    linked = set(re.findall(r'href="/articles/([^"#?.]+)', content_html))
    links = [(s, t) for s, t in related(article, all_articles, limit=MAX_LINKS + len(linked)) if s not in linked]
    line = markup(links[:MAX_LINKS])
    if not line:
        return content_html
    return content_html.rstrip() + line
