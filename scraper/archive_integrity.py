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
                 if difflib.SequenceMatcher(None, reference, parts[m]["body"][:3000]).quick_ratio() >= SIMILARITY]
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
    changed = []
    for slug, action in plan(pages, live).items():
        updated = apply(pages[slug], action)
        if updated != pages[slug]:
            changed.append(f"articles/{slug}.html")
            if not check:
                files[slug].write_text(updated, encoding="utf-8")
    return changed
