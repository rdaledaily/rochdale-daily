#!/usr/bin/env python3
"""Bring already-written pages up to two Bing Webmaster SEO rules.

Bing's Site Scan (14 Nov 2026) flagged two page-level faults across the
archive:

* "Title too long": 717 of 1,972 article pages had a <title> over 70
  characters. New pages are now written through headline_style.title_tag,
  which shortens; this pass shortens the <title> of pages that are not
  re-rendered each run (the archive). The <h1> keeps the full headline.
* "The <img> tag does not have an ALT attribute defined": Bing counts alt=""
  as missing. 14,785 thumbnails in story links (More on this, Read next,
  onward lists, homepage cards) shipped alt="". Inside a link, this pass sets
  the alt to the linked story's headline, read from the link itself.

Idempotent: a page already within the rules is left byte-for-byte alone. The
<title> is the only thing in <head> it touches, so sitemap lastmod (read from
the page's JSON-LD) does not move.
"""
from __future__ import annotations

import html
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from headline_style import TITLE_HARD_LIMIT, shorten_title  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S | re.I)
_ANCHOR_RE = re.compile(r"<a\b[^>]*>(?:(?!</?a\b).)*?</a>", re.S | re.I)
_EMPTY_ALT_IMG_RE = re.compile(r'<img\b[^>]*\balt=""[^>]*>', re.I)
# The element inside a story link that holds its headline.
_HEADLINE_RE = re.compile(
    r'<(span|h[1-6]|p|div)\b[^>]*class="[^"]*(?:title|headline)[^"]*"[^>]*>(.*?)</\1>',
    re.S | re.I,
)
_TAG_RE = re.compile(r"<[^>]+>")


def _text(fragment: str) -> str:
    return " ".join(html.unescape(_TAG_RE.sub(" ", fragment)).split())


def fix_title(page: str) -> str:
    match = _TITLE_RE.search(page)
    if not match:
        return page
    current = _text(match.group(1))
    if len(current) <= TITLE_HARD_LIMIT:
        return page
    short = shorten_title(current)
    return page[: match.start()] + "<title>" + html.escape(short, quote=False) + "</title>" + page[match.end():]


def _alt_for_anchor(anchor: str) -> str:
    headline = _HEADLINE_RE.search(anchor)
    text = _text(headline.group(2)) if headline else _text(anchor)
    return text[:200]


def fix_link_image_alts(page: str) -> str:
    if 'alt=""' not in page:
        return page

    def repair(anchor_match: re.Match) -> str:
        anchor = anchor_match.group(0)
        if 'alt=""' not in anchor:
            return anchor
        alt = _alt_for_anchor(anchor)
        if not alt:
            return anchor
        attr = 'alt="' + html.escape(alt, quote=True) + '"'
        return _EMPTY_ALT_IMG_RE.sub(lambda m: m.group(0).replace('alt=""', attr, 1), anchor)

    return _ANCHOR_RE.sub(repair, page)


def fix_page(page: str) -> str:
    return fix_link_image_alts(fix_title(page))


def sweep(pages_dir: Path | None = None, write: bool = True) -> dict:
    pages_dir = pages_dir or ROOT / "articles"
    report = {"pages_scanned": 0, "pages_fixed": 0, "titles_shortened": 0, "alts_filled": 0}
    for path in sorted(pages_dir.glob("*.html")):
        report["pages_scanned"] += 1
        try:
            page = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        titled = fix_title(page)
        new = fix_link_image_alts(titled)
        if new == page:
            continue
        report["pages_fixed"] += 1
        report["titles_shortened"] += titled != page
        report["alts_filled"] += page.count('alt=""') - new.count('alt=""')
        if write:
            path.write_text(new, encoding="utf-8")
    return report


if __name__ == "__main__":
    print(sweep())
