#!/usr/bin/env python3
"""No public page may link to a story page that does not exist.

Ahrefs, 26 Nov 2026: 12 internal links answered 404, every one from a Morning
Briefing to a story that had since been taken down (seven by the core-fact
backstop in article_gate.py, five by other removals). takedown_sweep.py did
strip those entries from the briefing PAGES when each story came down, but a
briefing's body is stored in manual_articles.json, so the next rebuild wrote
the dead entry straight back. A takedown can only sweep the pages that exist
at that moment; this runs at the end of every publishing lane (from
normalise_public_theme.py) and checks the finished site, whatever wrote it.

A link is dead when its target /articles/<slug> has no page on disk
(articles/<slug>.html or articles/<slug>/index.html) and no _redirects rule.
For each dead link:

  * an ENTRY for the story - a list item or card whose every link is to the
    dead story and which begins with that link (briefing items, related-story
    lists, section cards) - is removed whole, with any JSON-LD ListItem;
  * a MENTION in running text keeps its words and loses only the link, so
    no story copy is ever deleted.

Usage:
  python scraper/dead_links.py            # fix, then report anything left
  python scraper/dead_links.py --check    # report only, exit 1 if any
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from clean_urls import redirect_sources  # noqa: E402
from takedown_sweep import _drop_list_items, _enclosing, public_files, renumber_list_items  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SLUG = r"[a-z0-9][a-z0-9-]*"
# Absolute or root-relative: /articles/<slug>[.html]
_ROOTED = re.compile(
    r'href=(["\'])(?:https?://(?:www\.)?rochdaledaily\.co\.uk)?/articles/(' + SLUG + r')(?:\.html)?(?=[#?"\'])'
)
# Relative from a page inside articles/: href="<slug>[.html]"
_RELATIVE = re.compile(r'href=(["\'])(' + SLUG + r')(?:\.html)?(?=[#?"\'])')
_ANCHOR_OPEN = re.compile(r"<a\b[^>]*>", re.I)


def _targets(text: str, in_articles: bool) -> set[str]:
    found = {m.group(2) for m in _ROOTED.finditer(text)}
    if in_articles:
        found |= {m.group(2) for m in _RELATIVE.finditer(text)}
    return found


def page_exists(root: Path, slug: str, redirected: set[str]) -> bool:
    return (
        (root / "articles" / f"{slug}.html").is_file()
        or (root / "articles" / slug / "index.html").is_file()
        or f"/articles/{slug}" in redirected
    )


def _href_pattern(slug: str, in_articles: bool) -> re.Pattern[str]:
    rooted = r'(?:https?://(?:www\.)?rochdaledaily\.co\.uk)?/articles/' + re.escape(slug)
    target = f"(?:{rooted}|{re.escape(slug)})" if in_articles else rooted
    return re.compile(r'href=(["\'])' + target + r'(?:\.html)?(?:[#?][^"\']*)?\1')


def _is_entry(element: str, slug: str, href: re.Pattern[str]) -> bool:
    """An element that exists only to list the dead story."""
    anchors = _ANCHOR_OPEN.findall(element)
    if not anchors or not all(href.search(a) for a in anchors):
        return False
    if element.startswith("<article"):
        return True
    # <li ...> followed directly by the link (optionally inside a wrapper tag)
    return bool(re.match(r"<li\b[^>]*>\s*(?:<(?!a\b)[a-z0-9]+\b[^>]*>\s*)*<a\b", element, re.I))


# Morning Briefing / Evening Wrap-Up: "N new stories in the Rochdale borough
# since ..." appears in the body, meta, Open Graph, Twitter and JSON-LD.
_BRIEF_LIST = re.compile(r"<h2>The stories</h2>\s*<ul>(.*?)</ul>", re.S)
_BRIEF_COUNT = re.compile(r"\b(\d+) new stor(?:y|ies)(?= in the Rochdale borough since)")


def _brief_items(text: str) -> int | None:
    match = _BRIEF_LIST.search(text)
    return None if match is None else len(re.findall(r"<li\b", match.group(1)))


def _recount_briefing(text: str, before: int | None) -> str:
    """Keep "N new stories" true after entries leave a briefing's list.

    N counts every story published in the window; the list shows at most
    daily_briefing.MAX_ITEMS of them, so N can exceed the list. A removed entry
    was a story that is no longer published, so N falls by the number removed.
    Left alone unless every stated count agrees and is at least the list size.
    """
    after = _brief_items(text)
    if before is None or after is None or after == before:
        return text
    stated = {int(m.group(1)) for m in _BRIEF_COUNT.finditer(text)}
    if len(stated) != 1 or next(iter(stated)) < before:
        return text
    count = next(iter(stated)) - (before - after)
    words = f"{count} new {'story' if count == 1 else 'stories'}"
    return _BRIEF_COUNT.sub(words, text)


def fix_text(text: str, dead: list[str], in_articles: bool) -> tuple[str, int, int]:
    """Return (text, entries_removed, links_unwrapped)."""
    removed = unwrapped = 0
    listed_before = _brief_items(text)
    for slug in dead:
        text, n = _drop_list_items(text, slug)
        removed += n
        href = _href_pattern(slug, in_articles)
        position = 0
        while True:
            anchor = None
            for match in _ANCHOR_OPEN.finditer(text, position):
                if href.search(match.group(0)):
                    anchor = match
                    break
            if anchor is None:
                break
            span = _enclosing(text, anchor.start())
            if span and _is_entry(text[span[0]:span[1]], slug, href):
                text = text[:span[0]] + text[span[1]:]
                removed += 1
                position = span[0]
                continue
            close = text.lower().find("</a>", anchor.end())
            if close == -1:
                position = anchor.end()
                continue
            text = text[:anchor.start()] + text[anchor.end():close] + text[close + len("</a>"):]
            unwrapped += 1
            position = anchor.start()
    if removed:
        text = renumber_list_items(text)
        text = _recount_briefing(text, listed_before)
    return text, removed, unwrapped


def find_dead(root: Path = ROOT) -> dict[str, list[str]]:
    """{page: [dead slugs]} across every public HTML page."""
    redirected = redirect_sources(root)
    result: dict[str, list[str]] = {}
    for path in public_files(root):
        if path.suffix != ".html":
            continue
        rel = path.relative_to(root)
        in_articles = rel.parts[0] == "articles"
        text = path.read_text(encoding="utf-8", errors="ignore")
        dead = sorted(s for s in _targets(text, in_articles) if not page_exists(root, s, redirected))
        if dead:
            result[rel.as_posix()] = dead
    return result


def sweep(root: Path = ROOT, *, check: bool = False) -> list[str]:
    """Fix every page with a dead story link; return the pages changed."""
    changed: list[str] = []
    for rel, dead in find_dead(root).items():
        path = root / rel
        original = path.read_text(encoding="utf-8")
        updated, removed, unwrapped = fix_text(original, dead, rel.startswith("articles/"))
        if updated == original:
            continue
        changed.append(rel)
        if not check:
            path.write_text(updated, encoding="utf-8")
            print(f"Dead links: {rel}: {removed} entr{'y' if removed == 1 else 'ies'} removed, "
                  f"{unwrapped} link(s) unwrapped -> {', '.join(dead)}")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args()
    root = Path(args.root)
    if not args.check:
        sweep(root)
    left = find_dead(root)
    for rel, dead in left.items():
        print(f"DEAD LINK: {rel} -> {', '.join(dead)}")
    if left:
        print(f"ERROR: {len(left)} page(s) link to story pages that do not exist.")
        return 1
    print("No public page links to a missing story page.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
