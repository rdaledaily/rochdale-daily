"""Apply the blanket incident rule to everything already published.

Editor, 9 Nov 2026: every incident story with "emergency" in its headline is
filed under Community and shows the red Incident card; non-crime crashes,
collisions and health emergencies show the card in their own section, "change every article with the same
details". New and live stories get the rule from the pipeline itself
(incident_rule.py); this pass brings the stored archive and every already
generated page into line, so no old page keeps a wrong section or photo.

Runs inside generate_pages.main (every lane), so no workflow edit is needed.
Idempotent: a page or record already in line is left byte-for-byte alone.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

import incident_rule as ir

ROOT = Path(__file__).resolve().parents[1]
SITE = "https://rochdaledaily.co.uk"
LABEL = "Community"

SECTION_RE = re.compile(r'"articleSection"\s*:\s*"([^"]*)"')
H1_RE = re.compile(r"<h1\b[^>]*>(.*?)</h1>", re.S | re.I)
HERO_RE = re.compile(r'<figure\b[^>]*class=["\']article-hero-image["\'][^>]*>.*?</figure>', re.S)
BREADCRUMB_RE = re.compile(r'(<nav class="article-breadcrumb"[^>]*>.*?<span aria-hidden="true">[^<]*</span>)'
                           r'<a\b[^>]*>[^<]*</a>', re.S)


def _hero() -> str:
    return ('<figure class="article-hero-image"><img src="/' + ir.INCIDENT_CARD + '" alt="'
            + ir.INCIDENT_ALT + '" loading="eager"><figcaption>Rochdale Daily</figcaption></figure>')


def fix_page(page: str, recategorise: bool = True) -> str:
    """Point the page at the Incident card; with recategorise (the "emergency"
    rule) also file it under Community. Crashes keep their own section."""
    absolute = SITE + "/" + ir.INCIDENT_CARD
    if recategorise:
        page = BREADCRUMB_RE.sub(lambda m: m.group(1) + '<a href="/news/' + ir.INCIDENT_CATEGORY + '.html">'
                                 + LABEL + '</a>', page, count=1)
        page = re.sub(r'("articleSection"\s*:\s*)"[^"]*"', lambda m: m.group(1) + json.dumps(LABEL.lower()), page)
        page = re.sub(r'(<meta property="article:section" content=")[^"]*(")', r'\g<1>' + LABEL + r'\2', page)
    # The whole image set (crops, sizes, alt, twitter, schema) in one place,
    # never a URL swap that leaves the old sizes behind (og_images.py).
    from og_images import rewrite_page_image
    page = rewrite_page_image(page, ir.INCIDENT_CARD, ir.INCIDENT_ALT)
    if HERO_RE.search(page):
        page = HERO_RE.sub(lambda _: _hero(), page, count=1)
    elif '<div class="article-copy">' in page:
        page = page.replace('<div class="article-copy">', _hero() + '<div class="article-copy">', 1)
    return page


def _rows(data: Any) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("articles", "stories", "items"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def fix_store(path: Path, image: bool = True) -> int:
    if not path.is_file():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    changed = 0
    for row in _rows(data):
        if not isinstance(row, dict) or not ir.wants_incident_card(row):
            continue
        before = json.dumps(row, sort_keys=True)
        if ir.is_incident(row):
            had_types = "types" in row
            ir.apply_incident_category(row)
            if not had_types:
                row.pop("types", None)
        if image:
            ir.apply_incident_card(row)
        changed += json.dumps(row, sort_keys=True) != before
    if changed:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changed


def main(root: Path = ROOT) -> dict[str, int]:
    stats = {"records": 0, "index_records": 0, "pages": 0}
    stats["records"] += fix_store(root / "articles" / "archive.json")
    stats["index_records"] += fix_store(root / "archive-index.json", image=False)
    for page_path in sorted((root / "articles").glob("*.html")):
        page = page_path.read_text(encoding="utf-8")
        h1 = H1_RE.search(page)
        if not h1:
            continue
        section = SECTION_RE.search(page)
        probe = {"title": html.unescape(re.sub(r"<[^>]+>", "", h1.group(1))),
                 "category": section.group(1).casefold() if section else ""}
        if not ir.wants_incident_card(probe):
            continue
        fixed = fix_page(page, recategorise=ir.is_incident(probe))
        if fixed != page:
            page_path.write_text(fixed, encoding="utf-8")
            stats["pages"] += 1
    print(f"Incident rule backfill: {stats}")
    return stats


if __name__ == "__main__":
    main()
