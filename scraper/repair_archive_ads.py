#!/usr/bin/env python3
"""
Rochdale Daily — repair advert slots on frozen archive pages.

WHY THIS EXISTS
---------------
generate_pages.py rebuilds only the articles currently in articles.json, which
holds roughly a fortnight. Every other page on disk keeps the template that was
current on the day it was written, for good — so a change to the article
template reaches new pages and silently misses the archive.

That is how 52 pages ended up with advert containers carrying no
``data-ad-slot`` attribute and no ``/assets/ads.js`` at all. ads.js selects on
``[data-ad-slot]``, so those slots were invisible to it: every one of those
pages rendered the dashed "AD — 728×90" placeholder and could never show an
advert. They are ordinary archive pages that still receive search traffic, so
that is real lost inventory rather than a cosmetic fault.

WHAT IT DOES
------------
For every generated article page:

  * adds ``data-ad-slot="article-leaderboard|incontent|mrec"`` to an advert
    container that is missing it, matched on the existing class;
  * adds the ``/assets/ads.js`` script tag before </body> if absent;
  * adds ``/assets/js/cookie-consent.js`` for the same reason — those pages
    predate the banner and so never ask for consent.

It is idempotent: a page that already has all three is left byte-identical, so
this can run on every pipeline run and becomes a no-op once the archive is
clean. It only ever adds attributes and script tags; it never rewrites content.

Usage:
    python scraper/repair_archive_ads.py
    python scraper/repair_archive_ads.py --dry-run
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PAGES_DIR = REPO_ROOT / "articles"

# class fragment -> the slot name ads.js expects
SLOT_CLASSES = {
    "ad-slot-leaderboard": "article-leaderboard",
    "ad-slot-incontent": "article-incontent",
    "ad-slot-mrec": "article-mrec",
}

ADS_SCRIPT = '<script defer src="/assets/ads.js"></script>'
CONSENT_SCRIPT = '<script defer src="/assets/js/cookie-consent.js"></script>'


def add_slot_attributes(html: str) -> tuple[str, int]:
    """Tag advert containers that have a slot class but no data-ad-slot."""
    added = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal added
        tag = match.group(0)
        if "data-ad-slot" in tag:
            return tag
        for css_class, slot in SLOT_CLASSES.items():
            if css_class in tag:
                added += 1
                # Insert after the class attribute so the markup matches what
                # generate_pages.py now produces, byte for byte.
                return tag.replace(
                    'class="', 'data-ad-slot="%s" class="' % slot, 1
                )
        return tag

    return re.sub(r"<div[^>]*\bad-slot\b[^>]*>", repl, html), added


def add_script(html: str, tag: str) -> tuple[str, bool]:
    if tag in html or "</body>" not in html:
        return html, False
    return html.replace("</body>", f"  {tag}\n</body>", 1), True


def repair(html: str) -> tuple[str, list[str]]:
    notes: list[str] = []
    html, added = add_slot_attributes(html)
    if added:
        notes.append(f"{added} slot(s) tagged")
    html, ok = add_script(html, CONSENT_SCRIPT)
    if ok:
        notes.append("cookie-consent.js")
    html, ok = add_script(html, ADS_SCRIPT)
    if ok:
        notes.append("ads.js")
    return html, notes


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair advert slots on archive pages.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not PAGES_DIR.exists():
        print("repair_archive_ads: no articles directory", file=sys.stderr)
        return 0

    pages = sorted(PAGES_DIR.glob("*.html"))
    changed = 0
    for path in pages:
        try:
            before = path.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"  could not read {path.name}: {exc}", file=sys.stderr)
            continue
        after, notes = repair(before)
        if after == before:
            continue
        changed += 1
        print(f"  {path.name[:64]:<66}{', '.join(notes)}")
        if not args.dry_run:
            path.write_text(after, encoding="utf-8")

    print(
        f"\npages checked: {len(pages)} | repaired: {changed}"
        + (" | DRY RUN, nothing written" if args.dry_run else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
