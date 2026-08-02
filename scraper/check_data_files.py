#!/usr/bin/env python3
"""
Rochdale Daily — validate the hand-edited data files.

WHY THIS EXISTS
---------------
Several files on this site are edited by hand through the GitHub web interface:
manual_articles.json, manual_events.json, adverts.json, ward_areas.json and the
blocklist. They are read by code that fails quietly.

manual_articles.py is the clearest case. It parses the file inside a try/except
and returns an empty list on any error, because a broken file must not stop the
news pipeline. The consequence is that one stray comma removes EVERY manual
article from the site at once, with no error anywhere: valid-looking JSON in the
editor, a green pipeline run, and articles that simply are not there. That
happened five times in a single day.

The same shape of failure applies elsewhere. ads.js catches a bad adverts.json
and leaves the placeholders up, so a malformed file means no advertising with no
warning — on a site whose costs are covered by advertising.

This script turns those silent failures into a failed CI run naming the file and
the line. It only reads; it never writes or repairs.

Usage:
    python scraper/check_data_files.py
    python scraper/check_data_files.py --warn-only    # report, exit 0
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

VALID_CATEGORIES = {
    "news", "crime", "politics", "traffic", "transport", "sport", "business",
    "health", "education", "environment", "community", "events",
}

# Markers ChatGPT leaves behind when it has been browsing. They render as
# literal text mid-sentence.
CITATION_MARKER = re.compile(r"::?contentReference\[oaicite:\d+\]\{index=\d+\}")

# UTF-8 read as Latin-1: "Â£15", "19Â°C", "cafÃ©s", "â" for an em dash.
MOJIBAKE = re.compile(r"Â[£°]|Ã[©¨¡]|â€|â\u0080")

problems: list[str] = []
notes: list[str] = []


def fail(where: str, message: str) -> None:
    problems.append(f"{where}: {message}")


def note(where: str, message: str) -> None:
    notes.append(f"{where}: {message}")


def load(path: Path):
    """Parse JSON, reporting the line and column of any syntax error."""
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        lines = raw.splitlines()
        context = ""
        if 0 < exc.lineno <= len(lines):
            context = f"  ->  {lines[exc.lineno - 1].strip()[:90]}"
        hint = ""
        if exc.lineno <= len(lines):
            previous = lines[exc.lineno - 2].rstrip() if exc.lineno >= 2 else ""
            if previous.endswith(",") and lines[exc.lineno - 1].strip() in ("]", "}"):
                hint = ("  (a trailing comma on the line above: the last item in a "
                        "list or object must not end with one)")
        fail(path.name, f"invalid JSON at line {exc.lineno}, column {exc.colno}{hint}{context}")
        return None


def check_text(where: str, field: str, value) -> None:
    if not isinstance(value, str):
        return
    if CITATION_MARKER.search(value):
        fail(where, f"{field} contains a citation marker left by an AI tool "
                    "(:contentReference[oaicite:...]) — it will print on the page")
    if MOJIBAKE.search(value):
        fail(where, f"{field} contains mojibake (Â£, Ã©, â) — UTF-8 text saved as Latin-1")


def check_manual_articles() -> None:
    path = REPO_ROOT / "manual_articles.json"
    data = load(path)
    if data is None:
        return
    if not isinstance(data, list):
        fail(path.name, "top level must be a list of articles, i.e. [ { ... } ]")
        return

    live = 0
    slugs: dict[str, int] = {}
    for index, entry in enumerate(data):
        where = f"{path.name}[{index}]"
        if not isinstance(entry, dict):
            fail(where, "entry is not an object")
            continue
        label = str(entry.get("slug") or entry.get("title") or f"entry {index}")[:48]
        where = f"{path.name} ({label})"

        # The block schema: headline/content instead of title/body. Entries in
        # that shape either vanish (no title) or print a Python list on the page.
        if entry.get("headline") and not entry.get("title"):
            fail(where, 'uses "headline" instead of "title" — this entry will not publish')
        if isinstance(entry.get("content"), list) or isinstance(entry.get("body"), list):
            fail(where, '"body"/"content" is a list of blocks; it must be plain text '
                        "with \\n\\n between paragraphs, or the raw structure prints on the page")

        if not entry.get("title"):
            fail(where, "missing title — this entry will be skipped silently")
        if not (entry.get("body") or entry.get("content")):
            fail(where, "missing body — this entry will be skipped silently")

        for field in ("title", "body", "excerpt"):
            check_text(where, field, entry.get(field))

        category = str(entry.get("category") or "").lower()
        if category and category not in VALID_CATEGORIES:
            note(where, f'category "{category}" is not recognised and will become "news"')

        image = str(entry.get("image_url") or "")
        if image and not image.startswith("http") and not (REPO_ROOT / image).is_file():
            fail(where, f"image_url points at a file that does not exist: {image}")

        if str(entry.get("right_to_reply") or "").lower().startswith("right to reply"):
            note(where, 'right_to_reply repeats the "Right to reply:" label the page already prints')

        slug = str(entry.get("slug") or "")
        if slug:
            if slug in slugs:
                fail(where, f"duplicate slug, also used by entry {slugs[slug]}")
            slugs[slug] = index

        if not entry.get("draft") and entry.get("enabled") is not False:
            live += 1

    note(path.name, f"{len(data)} entries, {live} would publish")


def check_adverts() -> None:
    path = REPO_ROOT / "adverts.json"
    data = load(path)
    if data is None:
        return
    if not isinstance(data, dict) or not isinstance(data.get("placements"), list):
        fail(path.name, 'must be an object with a "placements" list')
        return

    live = 0
    for index, ad in enumerate(data["placements"]):
        if not isinstance(ad, dict):
            fail(f"{path.name}[{index}]", "placement is not an object")
            continue
        where = f"{path.name} ({ad.get('id') or index})"
        if str(ad.get("id", "")).startswith("template-"):
            continue
        live += 1
        for field in ("id", "slot", "image", "url", "start", "end"):
            if not ad.get(field):
                fail(where, f"missing {field}")
        image = str(ad.get("image") or "")
        if image and not (REPO_ROOT / image.lstrip("/")).is_file():
            fail(where, f"image file does not exist: {image}")
        mobile = str(ad.get("image_mobile") or "")
        if mobile and not (REPO_ROOT / mobile.lstrip("/")).is_file():
            fail(where, f"image_mobile file does not exist: {mobile}")
        if "REPLACE" in str(ad.get("url") or ""):
            note(where, "url is still a placeholder, so the advert will not click through")
    note(path.name, f"{live} live placement(s)")


def check_simple(name: str, expect_list: bool = True, key: str | None = None) -> None:
    path = REPO_ROOT / name
    data = load(path)
    if data is None:
        return
    if key:
        if not isinstance(data, dict) or key not in data:
            fail(name, f'expected an object containing "{key}"')
            return
        data = data[key]
    if expect_list and not isinstance(data, (list, dict)):
        fail(name, "unexpected shape")
        return
    note(name, f"{len(data)} entries")


def check_ward_map() -> None:
    path = REPO_ROOT / "ward_areas.json"
    data = load(path)
    if data is None:
        return
    wards = (data or {}).get("wards")
    if not isinstance(wards, dict):
        fail(path.name, 'expected an object with a "wards" map')
        return
    areas_dir = REPO_ROOT / "articles" / "areas"
    known = {p.stem for p in areas_dir.glob("*.json")} if areas_dir.exists() else set()
    for ward, config in wards.items():
        for area in (config or {}).get("areas") or []:
            if known and area not in known:
                note(f"ward_areas.json ({ward})",
                     f'area "{area}" has no feed at articles/areas/{area}.json')
    note(path.name, f"{len(wards)} wards")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate hand-edited data files.")
    parser.add_argument("--warn-only", action="store_true",
                        help="report problems but exit 0")
    args = parser.parse_args()

    check_manual_articles()
    check_adverts()
    check_ward_map()
    check_simple("manual_events.json")
    check_simple("story_blocklist.json", key=None)
    check_simple("council_roster.json", key="councillors")

    for line in notes:
        print(f"  note   {line}")
    for line in problems:
        print(f"  ERROR  {line}", file=sys.stderr)

    if problems:
        print(f"\n{len(problems)} problem(s) found.", file=sys.stderr)
        return 0 if args.warn_only else 1
    print("\nAll data files valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
