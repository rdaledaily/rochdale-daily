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
from datetime import datetime, timezone
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

        corrections = entry.get("corrections")
        if corrections is not None:
            if not isinstance(corrections, list):
                fail(where, '"corrections" must be a list of {"date", "note"} objects — '
                            "any other shape is silently ignored")
            else:
                for c_index, item in enumerate(corrections):
                    c_where = f"{where} corrections[{c_index}]"
                    if isinstance(item, str):
                        check_text(c_where, "note", item)
                        note(c_where, "correction has no date; the page will say "
                                      '"This article has been amended" without one')
                        continue
                    if not isinstance(item, dict):
                        fail(c_where, "entry must be an object or a string — it will be dropped")
                        continue
                    text = str(item.get("note") or item.get("text") or "").strip()
                    if not text:
                        fail(c_where, 'missing "note" — this correction will be dropped silently')
                    check_text(c_where, "note", text)
                    date = str(item.get("date") or "").strip()
                    if date and not re.match(r"^\d{4}-\d{2}-\d{2}", date):
                        fail(c_where, f'date "{date}" is not YYYY-MM-DD — it will sort as '
                                      "undated and print no date on the page")

        slug = str(entry.get("slug") or "")
        if slug:
            if slug in slugs:
                fail(where, f"duplicate slug, also used by entry {slugs[slug]}")
            slugs[slug] = index

        if not entry.get("draft") and entry.get("enabled") is not False:
            live += 1

    note(path.name, f"{len(data)} entries, {live} would publish")


def advert_is_live(ad: dict, today: str | None = None) -> bool:
    """True when today falls inside the placement's booked date range."""
    stamp = today or datetime.now(timezone.utc).date().isoformat()
    start = str(ad.get("start") or "")[:10]
    end = str(ad.get("end") or "")[:10]
    if start and stamp < start:
        return False
    if end and stamp > end:
        return False
    return bool(start or end)


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
        url = str(ad.get("url") or "")
        if "REPLACE" in url.upper() or "example.com" in url:
            # A placeholder in a booking that is not running yet is housekeeping.
            # A placeholder in a booking that is live is a paying advertiser whose
            # advert goes nowhere, which is what happened to NEB Electrical from
            # 1 August 2026 onwards. That is a failure, not a note.
            if advert_is_live(ad):
                fail(where, f"live advert has a placeholder click-through: {url}")
            else:
                note(where, "url is still a placeholder (booking is not live)")
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


def check_card_aliases() -> None:
    """assets/img/cards/aliases.json: editor-curated phrase groups.

    The pipeline deliberately ignores a malformed file so a typo cannot stop
    publication; this is where that typo gets reported instead. Every image
    base listed must exist in the cards library, and every group needs at
    least one phrase, otherwise the group silently matches nothing.
    """
    cards_dir = REPO_ROOT / "assets" / "img" / "cards"
    path = cards_dir / "aliases.json"
    if not path.exists():
        return
    data = load(path)
    if data is None:
        return
    if not isinstance(data, dict):
        fail(path.name, "expected an object of alias groups")
        return
    import re as _re
    stems = set()
    for p in cards_dir.iterdir():
        if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
            stem = _re.sub(r"[^a-z0-9]+", "_", _re.sub(r"-\d+$", "", p.stem).lower()).strip("_")
            stems.add(stem)
    groups = 0
    for name, spec in data.items():
        where = f"{path.name} ({name})"
        if not isinstance(spec, dict):
            fail(where, "group must be an object with images and phrases")
            continue
        groups += 1
        images = spec.get("images") or []
        phrases = spec.get("phrases") or []
        if not images:
            fail(where, "group lists no images, so it can never match")
        for base in images:
            key = _re.sub(r"[^a-z0-9]+", "_", str(base).lower()).strip("_")
            if key not in stems:
                fail(where, f'image "{base}" matches no file in assets/img/cards/')
        if not phrases:
            note(where, "group has no phrases; only the group name itself will match")
    note(path.name, f"{groups} alias group(s)")


def check_live_updates(name: str = "feel-good-live.json") -> None:
    """Live coverage feeds are hand-edited mid-event, under time pressure —
    exactly when a stray comma is most likely and least affordable. The page
    JS catches a bad file and keeps showing the last good render, so like
    manual_articles.json the failure is silent: a green commit and an update
    that never appears."""
    from datetime import datetime, timezone

    path = REPO_ROOT / name
    if not path.exists():
        return
    data = load(path)
    if data is None:
        return
    if not isinstance(data, dict):
        fail(name, 'top level must be an object: { "title": ..., "status": ..., "updates": [ ... ] }')
        return

    status = str(data.get("status") or "").lower()
    if status and status not in {"upcoming", "live", "ended"}:
        note(name, f'status "{status}" is not upcoming/live/ended; the page will treat it as ended')

    updates = data.get("updates")
    if not isinstance(updates, list):
        fail(name, '"updates" must be a list')
        return
    now = datetime.now(timezone.utc)
    for index, item in enumerate(updates):
        where = f"{name}[{index}]"
        if not isinstance(item, dict):
            fail(where, "update is not an object")
            continue
        if item.get("draft"):
            continue  # inline template — the page skips it too
        if not str(item.get("body") or "").strip():
            fail(where, 'missing "body" — this update will render empty')
        for field in ("title", "body"):
            check_text(where, field, item.get(field))
        time_value = str(item.get("time") or "").strip()
        if time_value:
            try:
                parsed = datetime.fromisoformat(time_value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    note(where, f'time "{time_value}" has no timezone; it will be read as UTC, '
                                "which is an hour behind UK time in August")
                elif (parsed - now).total_seconds() > 3600:
                    note(where, f'time "{time_value}" is in the future')
            except ValueError:
                fail(where, f'time "{time_value}" is not an ISO timestamp '
                            '(use e.g. "2026-08-08T14:30:00+01:00")')
        else:
            note(where, "update has no time; it will show without a timestamp")
    note(name, f"{len(updates)} update(s), status {status or 'unset'}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate hand-edited data files.")
    parser.add_argument("--warn-only", action="store_true",
                        help="report problems but exit 0")
    args = parser.parse_args()

    check_manual_articles()
    check_adverts()
    check_card_aliases()
    check_ward_map()
    check_live_updates()
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
