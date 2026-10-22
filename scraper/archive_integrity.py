#!/usr/bin/env python3
"""Keep corrupted and duplicated archive pages out of Google's index.

Measured 19 October 2026 on the 1,713 article pages:

  * 85 groups of pages (203 pages) carry the same body text under different
    addresses. An early pipeline bug copied one story's body over others, so
    Google saw the same article many times with different headlines.
  * Some archived pages show a headline that has nothing to do with their own
    story: the page at /articles/rochdale-afc-appoints-new-manager is headed
    "Rochdale AFC Announces New Signings" and its body is about the Seven
    Sisters tower blocks.

Pages like these make the whole site look low quality to Google. Nothing is
deleted (old links keep working); this only changes what is offered for
indexing:

  * duplicates: every page in a group points its canonical (and og:url) at one
    primary page. The primary is the live story if the group has one, otherwise
    the page whose headline best matches its own body, then the oldest.
  * mismatched headline: an archived page whose headline shares no meaningful
    word with its own opening paragraphs is marked noindex,follow.
  * same story twice: an archived page with the same headline, on the same day,
    as another indexable page points its canonical at that page.
  * shared titles: indexable pages with the same <title> (different stories,
    same headline) get their publication date added to the title.

Live stories are regenerated every run and are never edited here. The sitemap
cleaner then lists only pages that are indexable and canonical to themselves.
Applied by normalise_public_theme.py, which every lane runs last.
"""
from __future__ import annotations

import difflib
import json
import re
from collections import defaultdict
from pathlib import Path

SITE = "https://rochdaledaily.co.uk"
SIMILARITY = 0.9          # body text this alike is the same article
STOP = set(
    "the a an of in on at to for and or with from by as is are was be been has have had after over "
    "new its it this that their his her will into than out up about rochdale daily borough".split()
)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
_BODY_RE = re.compile(r'<p class="article-standfirst"[^>]*>(.*?)</p>|<div class="article-body"[^>]*>([\s\S]*?)</div>', re.S)
_CANON_RE = re.compile(r'(<link rel="canonical" href=")([^"]+)(")')
_OGURL_RE = re.compile(r'(<meta property="og:url" content=")([^"]+)(")')
_ROBOTS_RE = re.compile(r'(<meta name="robots" content=")([^"]+)(")')
_DATE_RE = re.compile(r'"datePublished":\s*"([^"]+)"')


def _plain(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html or "").split())


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in STOP}


def page_parts(html: str) -> dict:
    h1 = _H1_RE.search(html)
    copy=re.search(r'<div[^>]*class="article-copy"[^>]*>(.*?)(?=<details[^>]*class="article-sources"|<section[^>]*class="(?:comments|read-next)|$)',html,re.S)
    if copy:
        body=_plain(copy.group(1))
    else:
        body = " ".join(_plain(a or b) for a, b in _BODY_RE.findall(html))
    date = _DATE_RE.search(html)
    return {"h1": _plain(h1.group(1)) if h1 else "", "body": body, "date": date.group(1) if date else ""}


def headline_matches_body(parts: dict) -> bool:
    head = _tokens(parts["h1"])
    opening = _tokens(" ".join(parts["body"].split()[:80]))
    return not head or not opening or bool(head & opening)


def plan(pages: dict[str, str], live: set[str]) -> dict[str, dict]:
    """slug -> {"canonical": slug} and/or {"noindex": True}, for archived pages only."""
    parts = {slug: page_parts(html) for slug, html in pages.items()}
    buckets: dict[str, list[str]] = defaultdict(list)
    for slug, p in parts.items():
        if len(p["body"]) >= 120:
            buckets[re.sub(r"\W+", " ", p["body"][:160].lower())].append(slug)

    actions: dict[str, dict] = {}
    for members in buckets.values():
        if len(members) < 2:
            continue
        reference = parts[members[0]]["body"][:3000]
        group = [m for m in members
                 if _plain(reference).casefold() == _plain(parts[m]["body"][:3000]).casefold()]
        if len(group) < 2:
            continue
        live_members = sorted(m for m in group if m in live)
        if live_members:
            primary = live_members[0]
        else:
            primary = sorted(group, key=lambda m: (not headline_matches_body(parts[m]),
                                                   -len(_tokens(parts[m]["h1"]) & _tokens(parts[m]["body"])),
                                                   parts[m]["date"] or "9999", m))[0]
        for member in group:
            if member != primary and member not in live:
                actions.setdefault(member, {})["canonical"] = primary

    for slug, p in parts.items():
        if slug in live or slug in actions:
            continue
        if not headline_matches_body(p):
            actions.setdefault(slug, {})["noindex"] = True
    return actions


def apply(html: str, action: dict) -> str:
    if action.get("canonical"):
        target = f"{SITE}/articles/{action['canonical']}"
        html = _CANON_RE.sub(lambda m: m.group(1) + target + m.group(3), html, count=1)
        html = _OGURL_RE.sub(lambda m: m.group(1) + target + m.group(3), html, count=1)
    if action.get("noindex"):
        html = _ROBOTS_RE.sub(lambda m: m.group(1) + "noindex,follow" + m.group(3), html, count=1)
    return html


_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
_SUFFIX = " | Rochdale Daily"
_DATED_RE = re.compile(r" \u00b7 \d{1,2} [A-Z][a-z]{2} \d{4}$")


def _indexable(html: str, slug: str) -> bool:
    head = html.split("</head>", 1)[0]
    robots = _ROBOTS_RE.search(head)
    canonical = _CANON_RE.search(head)
    return not (robots and "noindex" in robots.group(2)) and bool(canonical) and canonical.group(2).rstrip("/").endswith("/" + slug)


def _day(stamp: str) -> str:
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", stamp or "")
    if not match:
        return ""
    months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
    return f"{int(match.group(3))} {months[int(match.group(2)) - 1]} {match.group(1)}"


def title_plan(pages: dict[str, str]) -> dict[str, str]:
    """slug -> new <title> text, for indexable pages that share a title with another.

    Different stories with the same headline (four weekends of "Service Changes
    on Rochdale Line") compete with each other in search; the date tells them
    apart honestly.
    """
    groups: dict[str, list[str]] = defaultdict(list)
    for slug, html in pages.items():
        title = _TITLE_RE.search(html.split("</head>", 1)[0])
        if title and _indexable(html, slug):
            groups[title.group(1).strip()].append(slug)
    plan_: dict[str, str] = {}
    for title, members in groups.items():
        if len(members) < 2:
            continue
        stem = title[: -len(_SUFFIX)] if title.endswith(_SUFFIX) else title
        if _DATED_RE.search(stem):
            continue
        for slug in members:
            day = _day(page_parts(pages[slug])["date"])
            if day:
                plan_[slug] = f"{stem} \u00b7 {day}{_SUFFIX if title.endswith(_SUFFIX) else ''}"
    return plan_


def same_day_duplicates(pages: dict[str, str], live: set[str]) -> dict[str, dict]:
    """Archived pages with the same headline on the same day as another indexable page are
    the same story published twice: point them at one primary (the live page, else the fullest)."""
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for slug, html in pages.items():
        if not _indexable(html, slug):
            continue
        parts = page_parts(html)
        if parts["h1"] and parts["date"]:
            groups[(parts["h1"].lower(), parts["date"][:10])].append(slug)
    actions: dict[str, dict] = {}
    for members in groups.values():
        if len(members) < 2:
            continue
        live_members = sorted(m for m in members if m in live)
        primary = live_members[0] if live_members else max(members, key=lambda m: (len(page_parts(pages[m])["body"]), m))
        for member in members:
            # A shared headline/date is not proof of the same event. Different
            # incidents and service updates often use the same headline.
            same_body=_plain(page_parts(pages[member])["body"]).casefold()==_plain(page_parts(pages[primary])["body"]).casefold()
            if member != primary and member not in live and same_body:
                actions[member] = {"canonical": primary}
    return actions


def apply_title(html: str, title: str) -> str:
    return _TITLE_RE.sub(lambda m: f"<title>{title}</title>", html, count=1)


def live_slugs(root: Path) -> set[str]:
    try:
        rows = json.loads((root / "articles.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {str(row.get("slug")) for row in rows if isinstance(row, dict) and row.get("slug")}


def run(root: Path, *, check: bool = False) -> list[str]:
    folder = root / "articles"
    if not folder.is_dir():
        return []
    files = {path.stem: path for path in folder.glob("*.html")}
    live = live_slugs(root)
    if not live:
        return []           # without the live list, never touch anything
    pages = {slug: path.read_text(encoding="utf-8", errors="ignore") for slug, path in files.items()}
    updated = dict(pages)
    for slug, action in plan(pages, live).items():
        updated[slug] = apply(updated[slug], action)
    for slug, action in same_day_duplicates(updated, live).items():
        updated[slug] = apply(updated[slug], action)
    for slug, title in title_plan(updated).items():
        updated[slug] = apply_title(updated[slug], title)
    changed = []
    for slug, html in updated.items():
        if html != pages[slug]:
            changed.append(f"articles/{slug}.html")
            if not check:
                files[slug].write_text(html, encoding="utf-8")
    return changed
