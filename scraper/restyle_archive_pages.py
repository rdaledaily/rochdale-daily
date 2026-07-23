#!/usr/bin/env python3
"""Bring archived article pages onto the current card design.

Why these pages go stale
------------------------
``generate_pages.py`` rewrites a page for every article in ``articles.json``,
and deliberately keeps every page that has ever been published so old URLs stay
discoverable. ``articles.json`` holds about a fortnight, so the great majority of
pages on disk have no article behind them any more and are never rewritten
again. They keep the masthead, palette and card artwork of whatever generation
produced them.

That is why retired designs keep surfacing on the site: a page written months
ago still points at ``assets/img/stock_politics.jpg`` from a generator that no
longer exists, sitting alongside a current page using the cyan house card. Two
visual identities, one site.

What this does
--------------
For every page still referencing legacy artwork, the headline and section are
read back out of the page itself - the data is not in the feed any more, but it
is in the HTML - and a current-generation card is composed from them. The page's
image references are then rewritten to point at it.

Nothing is deleted and no URL changes. The archive stays exactly as
discoverable as before; it simply stops advertising a design that was retired.

Usage
-----
    python scraper/restyle_archive_pages.py            # report only
    python scraper/restyle_archive_pages.py --apply    # write the cards and pages
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from story_image import compose_story_card  # noqa: E402

ARTICLES_JSON = Path("articles.json")
PAGES_DIR = Path("articles")
CARD_DIR = Path("assets/article-images")

# Artwork from retired generators. Any page still pointing at one of these is
# showing a design the site no longer uses.
LEGACY_PATTERNS = (
    re.compile(r"assets/img/stock_[a-z0-9_]+\.(?:jpg|jpeg|png|webp)", re.I),
    re.compile(r"assets/img/generated/[^\"'\s]+\.(?:jpg|jpeg|png|webp|svg)", re.I),
    re.compile(r"assets/img/category[-_][a-z0-9_]+\.(?:jpg|jpeg|png|webp|svg)", re.I),
)

SECTION_TO_CATEGORY = {
    "news": "news", "crime": "crime", "courts": "crime", "politics": "politics",
    "council & democracy": "politics", "council and democracy": "politics",
    "traffic": "traffic", "traffic & travel": "traffic", "transport": "transport",
    "sport": "sport", "business": "business", "health": "health",
    "education": "education", "environment": "environment",
    "community": "community", "what's on": "events", "events": "events",
}


def text_of(pattern: str, source: str) -> str:
    match = re.search(pattern, source, re.S | re.I)
    if not match:
        return ""
    raw = re.sub(r"<[^>]+>", " ", match.group(1))
    return re.sub(r"\s+", " ", html.unescape(raw)).strip()


def read_page(path: Path) -> dict:
    source = path.read_text(encoding="utf-8", errors="ignore")
    title = text_of(r"<h1[^>]*>(.*?)</h1>", source)
    if not title:
        title = text_of(r"<title>(.*?)</title>", source).replace("| Rochdale Daily", "").strip()

    section = text_of(r'<span class="story-kicker"[^>]*>(.*?)</span>', source)
    if not section:
        section = text_of(r'<meta property="article:section" content="([^"]*)"', source)

    # The area is not stored on the page, so fall back to the borough. A card
    # tagged ROCHDALE on a Heywood story is a small inaccuracy; leaving a
    # retired design in place is a larger one.
    return {
        "source": source,
        "title": title,
        "category": SECTION_TO_CATEGORY.get(section.lower().strip(), "news"),
        "area": "rochdale",
    }


def legacy_refs(source: str) -> set[str]:
    found: set[str] = set()
    for pattern in LEGACY_PATTERNS:
        found.update(pattern.findall(source))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="compose the cards and rewrite the pages")
    parser.add_argument("--limit", type=int, default=0,
                        help="stop after this many pages, for a cautious first run")
    args = parser.parse_args()

    if not PAGES_DIR.is_dir():
        print("Run this from the repository root.")
        return 1

    live: set[str] = set()
    if ARTICLES_JSON.exists():
        for entry in json.loads(ARTICLES_JSON.read_text(encoding="utf-8")):
            if isinstance(entry, dict) and entry.get("slug"):
                live.add(str(entry["slug"]))

    pages = sorted(PAGES_DIR.glob("*.html"))
    stale = []
    for path in pages:
        source = path.read_text(encoding="utf-8", errors="ignore")
        refs = legacy_refs(source)
        if refs:
            stale.append((path, refs))

    print(f"pages on disk         : {len(pages)}")
    print(f"still in the feed     : {sum(1 for p in pages if p.stem in live)}")
    print(f"showing retired art   : {len(stale)}")

    if not stale:
        print("\nNothing to do — every page is on the current design.")
        return 0

    counts: dict[str, int] = {}
    for _, refs in stale:
        for ref in refs:
            counts[ref] = counts.get(ref, 0) + 1
    print("\nretired artwork still in use:")
    for ref, n in sorted(counts.items(), key=lambda kv: -kv[1])[:12]:
        print(f"  {n:4d}  {ref}")

    if not args.apply:
        print("\nReport only. Re-run with --apply to restyle them.")
        return 0

    done = 0
    for path, refs in stale:
        if args.limit and done >= args.limit:
            break
        page = read_page(path)
        if not page["title"]:
            print(f"  ! {path.stem[:56]} — no headline found, left alone")
            continue

        card_path = CARD_DIR / f"{path.stem}-area-category-card.jpg"
        try:
            relative, _credit = compose_story_card(
                page["title"], page["area"], page["category"], card_path,
                story_text=page["title"],
            )
        except Exception as error:  # noqa: BLE001
            print(f"  ! {path.stem[:56]} — could not compose a card: {error}")
            continue

        source = page["source"]
        for pattern in LEGACY_PATTERNS:
            source = pattern.sub(relative.lstrip("/"), source)
        path.write_text(source, encoding="utf-8")
        done += 1

    print(f"\nRestyled {done} pages onto the current card design.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
