#!/usr/bin/env python3
"""Build the place-photo library from Wikimedia Commons.

Why this exists
---------------
Generated gradient cards are safe and free but they make the paper look like a
database. Real photographs are what make it read like a newspaper. The pipeline
already prefers a photograph over a gradient - what was missing was supply, so
this fills ``assets/img/places/`` in bulk instead of one drag-and-drop at a time.

Source and licensing
--------------------
Wikimedia Commons, which mirrors the whole Geograph Britain and Ireland archive
(8m+ CC BY-SA 2.0 photographs, one for every square kilometre of the country)
alongside other freely licensed material.

Only licences that permit commercial use are accepted - CC0, public domain,
CC BY and CC BY-SA. Anything NonCommercial or NoDerivatives is rejected
outright, because this is a commercial publication and a card is a derivative
work.

Note on ShareAlike: overlaying a headline on a CC BY-SA photograph makes the
resulting card a derivative, so the card itself carries CC BY-SA. That permits
commercial use and does not affect the article text - it only means someone
else may reuse the card image. If that is unwanted, restrict ACCEPTED_LICENCES
to the CC0/PD/CC-BY entries and accept thinner coverage.

Usage
-----
    python scraper/fetch_place_photos.py              # dry run, changes nothing
    python scraper/fetch_place_photos.py --download   # actually fetch and write

A dry run prints what it would fetch, with the photographer and licence for
each, so the whole set can be reviewed before anything lands in the repository.
Existing files are never overwritten: a photograph placed by hand always wins.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from io import BytesIO
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from PIL import Image, ImageOps

API = "https://commons.wikimedia.org/w/api.php"
UA = "RochdaleDaily/1.0 (https://rochdaledaily.co.uk; news@rochdaledaily.co.uk)"

PLACES_DIR = Path("assets/img/places")
CREDITS_PATH = PLACES_DIR / "credits.json"

WIDTH, HEIGHT = 1200, 675
FETCH_WIDTH = 1800          # ask for something larger than the crop
MIN_SOURCE_WIDTH = 900      # below this the crop gets soft
CANDIDATES_PER_PLACE = 12   # how many search hits to consider

# Substrings that mark a licence as usable commercially. Matched against the
# Commons ``LicenseShortName`` field, lowercased.
ACCEPTED_LICENCES = (
    "cc0", "public domain", "pd-", "cc by 2.0", "cc by 3.0", "cc by 4.0",
    "cc by-sa 2.0", "cc by-sa 3.0", "cc by-sa 4.0",
)
REJECTED_MARKERS = ("nc", "noncommercial", "nd", "noderiv", "fair use", "non-free")

# Filename fragments that are usually maps, diagrams, coats of arms or logos
# rather than photographs of a place.
SKIP_FRAGMENTS = (
    "map", "diagram", "logo", "coat of arms", "arms of", "chart", "plan of",
    "svg", "seal of", "flag of", "sign", "plaque", "graph",
)

TOPICS_DIR = Path("assets/img/topics")
TOPICS_CREDITS_PATH = TOPICS_DIR / "credits.json"

# (Commons search phrase, category slug)
#
# Topic photographs are the answer to the complaint that every card looked the
# same: an area photograph is a picture of the right town and tells the reader
# nothing about the story, so a rugby report, a driving test and a helicopter
# sighting all arrived behind the same streetscape. A pitch, a road and a school
# at least belong to their stories.
#
# Several phrases share a category on purpose. Four photographs from one search
# tend to be four angles on the same subject; four searches give genuinely
# different pictures, which is what stops the front page repeating itself.
TOPICS: list[tuple[str, str]] = [
    ("Spotland Stadium Rochdale", "sport"),
    ("Crown Oil Arena Rochdale AFC", "sport"),
    ("Rochdale Hornets rugby league", "sport"),
    ("football pitch Greater Manchester", "sport"),
    ("Rochdale Town Hall council chamber", "politics"),
    ("Number One Riverside Rochdale", "politics"),
    ("Rochdale Town Hall exterior", "politics"),
    ("Manchester Road Rochdale traffic", "traffic"),
    ("M62 motorway Greater Manchester", "traffic"),
    ("roadworks Greater Manchester street", "traffic"),
    ("Rochdale railway station platform", "transport"),
    ("Metrolink tram Rochdale", "transport"),
    ("bus station Rochdale interchange", "transport"),
    ("Rochdale Infirmary hospital", "health"),
    ("NHS hospital Greater Manchester building", "health"),
    ("Hopwood Hall College Rochdale", "education"),
    ("school building Rochdale", "education"),
    ("Rochdale Sixth Form College", "education"),
    ("Rochdale Exchange Shopping Centre", "business"),
    ("Kingsway Business Park Rochdale", "business"),
    ("Drake Street Rochdale shops", "business"),
    ("Hollingworth Lake Littleborough", "environment"),
    ("Healey Dell nature reserve", "environment"),
    ("Watergrove Reservoir Wardle", "environment"),
    ("Rochdale Canal towpath", "environment"),
    ("Falinge Park Rochdale", "community"),
    ("Rochdale town centre pedestrians", "community"),
    ("Queen's Park Heywood", "community"),
    ("Touchstones Rochdale arts centre", "events"),
    ("Rochdale Pioneers Museum", "events"),
    ("Middleton Arena", "events"),
    ("Rochdale town centre street scene", "news"),
    ("Rochdale skyline Greater Manchester", "news"),
]

AREAS_DIR = Path("assets/img/areas")
AREAS_CREDITS_PATH = AREAS_DIR / "credits.json"

# (Commons search phrase, area slug)
#
# Area photographs are the universal fallback: every story carries an area, and
# unmatched areas climb their parent chain to "rochdale". A single rochdale.jpg
# therefore gives every card on the site a photographic background, which no
# amount of place-level coverage can do - places only match when a story names
# a specific landmark, and most stories do not.
#
# Search phrases are disambiguated on purpose. "Castleton" and "Bamford" are far
# better known as Derbyshire villages, and "Middleton" exists in a dozen
# counties; searching the bare name returns the wrong county's scenery.
AREAS: list[tuple[str, str]] = [
    ("Rochdale town centre Greater Manchester", "rochdale"),
    ("Heywood Greater Manchester", "heywood"),
    ("Middleton Greater Manchester town", "middleton"),
    ("Littleborough Greater Manchester", "littleborough"),
    ("Milnrow Greater Manchester", "milnrow"),
    ("Castleton Rochdale Greater Manchester", "castleton"),
    ("Norden Rochdale", "norden"),
    ("Bamford Rochdale Greater Manchester", "bamford"),
    ("Wardle Greater Manchester", "wardle"),
    ("Newhey Greater Manchester", "newhey"),
    ("Smallbridge Rochdale", "smallbridge"),
    ("Spotland Rochdale", "spotland"),
    ("Falinge Rochdale", "falinge"),
    ("Healey Rochdale", "healey"),
    ("Alkrington Middleton", "alkrington"),
    ("Darnhill Heywood", "darnhill"),
    ("Hopwood Greater Manchester", "hopwood"),
    ("Kirkholt Rochdale", "kirkholt"),
    ("Wardleworth Rochdale", "wardleworth"),
    ("Whitworth Lancashire", "whitworth"),
]

# (Commons search phrase, filename slug)
#
# Slugs follow the pipeline's matching rule: the specific thing first and the
# town last, because phrases are shortened from the end only. ``town_hall_rochdale``
# matches "town hall"; ``rochdale_town_hall`` would not.
PLACES: list[tuple[str, str]] = [
    ("Rochdale Town Hall", "town_hall_rochdale"),
    ("Touchstones Rochdale", "touchstones_rochdale"),
    ("Number One Riverside Rochdale", "number_one_riverside"),
    ("Drake Street Rochdale", "drake_street"),
    ("Yorkshire Street Rochdale", "yorkshire_street"),
    ("Rochdale Exchange Shopping Centre", "exchange_shopping_centre"),
    ("Rochdale railway station", "railway_station_rochdale"),
    ("Rochdale Interchange", "interchange_rochdale"),
    ("Rochdale Infirmary", "infirmary_rochdale"),
    ("Crown Oil Arena Rochdale", "crown_oil_arena"),
    ("Spotland Stadium", "spotland_stadium"),
    ("Rochdale Canal", "rochdale_canal"),
    ("Rochdale Cenotaph", "cenotaph_rochdale"),
    ("Rochdale Sixth Form College", "sixth_form_college_rochdale"),
    ("Hopwood Hall College", "hopwood_hall_college"),
    ("Falinge Park Rochdale", "falinge_park"),
    ("Springfield Park Rochdale", "springfield_park"),
    ("Broadfield Park Rochdale", "broadfield_park"),
    ("Manchester Road Rochdale", "manchester_road_rochdale"),
    ("Oldham Road Rochdale", "oldham_road_rochdale"),
    ("Bury Road Rochdale", "bury_road_rochdale"),
    ("Edenfield Road Rochdale", "edenfield_road"),
    ("Whitworth Road Rochdale", "whitworth_road"),
    ("Milnrow Road Rochdale", "milnrow_road"),
    ("Kingsway Business Park Rochdale", "kingsway_business_park"),
    ("Hollingworth Lake", "hollingworth_lake"),
    ("Healey Dell", "healey_dell"),
    ("Watergrove Reservoir", "watergrove_reservoir"),
    ("Blackstone Edge", "blackstone_edge"),
    ("Ashworth Valley", "ashworth_valley"),
    ("Littleborough railway station", "railway_station_littleborough"),
    ("Littleborough Cheshire", "littleborough_centre"),
    ("Smithy Bridge railway station", "railway_station_smithy_bridge"),
    ("Milnrow tram stop", "tram_stop_milnrow"),
    ("Newhey tram stop", "tram_stop_newhey"),
    ("Castleton railway station Greater Manchester", "railway_station_castleton"),
    ("Heywood Civic Centre", "civic_centre_heywood"),
    ("Queen's Park Heywood", "queens_park_heywood"),
    ("Heywood Greater Manchester", "heywood_centre"),
    ("Middleton Arena", "middleton_arena"),
    ("Middleton Gardens Greater Manchester", "middleton_gardens"),
    ("St Leonard's Church Middleton", "st_leonards_church_middleton"),
    ("Alkrington Middleton", "alkrington"),
    ("Norden Rochdale", "norden_village"),
    ("Bamford Rochdale", "bamford_village"),
    ("Wardle Greater Manchester", "wardle_village"),
    ("Rochdale Pioneers Museum", "pioneers_museum_rochdale"),
]


def get_json(params: dict) -> dict | None:
    url = f"{API}?{urlencode(params)}"
    request = Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as error:  # noqa: BLE001 - any failure just skips this place
        print(f"    ! request failed: {error}")
        return None


def strip_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def licence_ok(licence: str) -> bool:
    lowered = licence.lower()
    # Check rejections first: "CC BY-NC-SA 2.0" contains an accepted substring.
    for marker in REJECTED_MARKERS:
        if re.search(rf"\b{re.escape(marker)}\b", lowered):
            return False
    return any(token in lowered for token in ACCEPTED_LICENCES)


def looks_like_a_photograph(title: str) -> bool:
    lowered = title.lower()
    return not any(fragment in lowered for fragment in SKIP_FRAGMENTS)


def search(place: str) -> list[dict]:
    """Candidate images for a place, best first."""
    data = get_json({
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "generator": "search",
        "gsrsearch": f'{place} filetype:bitmap',
        "gsrnamespace": "6",
        "gsrlimit": str(CANDIDATES_PER_PLACE),
        "prop": "imageinfo",
        "iiprop": "url|size|extmetadata",
        "iiurlwidth": str(FETCH_WIDTH),
    })
    if not data:
        return []
    return data.get("query", {}).get("pages", []) or []


def choose_many(pages: list[dict], wanted: int) -> list[tuple[str, str, str, str]]:
    """The best usable candidates, strongest first."""
    scored = []
    for page in pages:
        picked = _score(page)
        if picked:
            scored.append(picked)
    scored.sort(key=lambda row: -row[0])
    seen: set[str] = set()
    out = []
    for _score_value, url, title, artist, licence in scored:
        if title in seen:
            continue
        seen.add(title)
        out.append((url, title, artist, licence))
        if len(out) >= wanted:
            break
    return out


def _score(page: dict):
    title = page.get("title", "")
    if not looks_like_a_photograph(title):
        return None
    info = (page.get("imageinfo") or [{}])[0]
    meta = info.get("extmetadata") or {}
    licence = strip_html((meta.get("LicenseShortName") or {}).get("value", ""))
    if not licence_ok(licence):
        return None
    width = int(info.get("width") or 0)
    height = int(info.get("height") or 0)
    if width < MIN_SOURCE_WIDTH:
        return None
    if height and width / height < 1.15:
        return None
    url = info.get("thumburl") or info.get("url")
    if not url:
        return None
    artist = strip_html((meta.get("Artist") or {}).get("value", "")) or "Unknown"
    score = width * (2 if "geograph" in title.lower() else 1)
    return (score, url, title, artist, licence)


def choose(pages: list[dict]) -> tuple[str, str, str, str] | None:
    """Pick the best usable candidate.

    Returns (download_url, page_title, artist, licence) or None.
    """
    best = None
    for page in pages:
        title = page.get("title", "")
        if not looks_like_a_photograph(title):
            continue
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        licence = strip_html((meta.get("LicenseShortName") or {}).get("value", ""))
        if not licence_ok(licence):
            continue
        width = int(info.get("width") or 0)
        height = int(info.get("height") or 0)
        if width < MIN_SOURCE_WIDTH:
            continue
        # Landscape crops to 16:9 without throwing away most of the frame.
        if height and width / height < 1.15:
            continue
        url = info.get("thumburl") or info.get("url")
        if not url:
            continue
        artist = strip_html((meta.get("Artist") or {}).get("value", "")) or "Unknown"
        score = width * (2 if "geograph" in title.lower() else 1)
        if best is None or score > best[0]:
            best = (score, url, title, artist, licence)
    if best is None:
        return None
    return best[1], best[2], best[3], best[4]


def download_and_crop(url: str, destination: Path) -> bool:
    request = Request(url, headers={"User-Agent": UA})
    try:
        with urlopen(request, timeout=60) as response:
            raw = response.read()
    except Exception as error:  # noqa: BLE001
        print(f"    ! download failed: {error}")
        return False

    # Decode straight from memory. An earlier version staged the bytes in a
    # .tmp file beside the destination and only created the directory
    # afterwards, so the very first download failed with FileNotFoundError on a
    # repository where assets/img/places did not exist yet - which is every
    # repository, the first time this is run.
    try:
        image = ImageOps.exif_transpose(Image.open(BytesIO(raw))).convert("RGB")
        cropped = ImageOps.fit(image, (WIDTH, HEIGHT), method=Image.Resampling.LANCZOS)
        destination.parent.mkdir(parents=True, exist_ok=True)
        cropped.save(destination, "JPEG", quality=88, optimize=True)
        return True
    except Exception as error:  # noqa: BLE001
        print(f"    ! could not process image: {error}")
        return False


def load_credits(path: Path = CREDITS_PATH) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true",
                        help="actually fetch and write files (default is a dry run)")
    parser.add_argument("--only", default="",
                        help="substring filter, e.g. --only heywood")
    parser.add_argument("--delay", type=float, default=1.0,
                        help="seconds between requests, to stay a polite client")
    args = parser.parse_args()

    # Both catalogues, every run. This used to sit behind an --areas flag, and a
    # run with the flag left off looked identical to a successful one: every
    # place was already present, so nothing was fetched and nothing committed.
    # A switch whose "off" position silently does nothing is a trap, and areas
    # are the important half - they are the fallback that gives EVERY card a
    # photograph, where places only match stories naming a specific landmark.
    # The number is how many photographs to keep per name. One is right for a
    # place: there is only one town hall. Areas and topics need a pool, because
    # they are fallbacks applied to dozens of stories, and a single photograph
    # repeated across a front page is what made the site look broken.
    targets = [
        ("places", PLACES, PLACES_DIR, CREDITS_PATH, 1),
        ("areas", AREAS, AREAS_DIR, AREAS_CREDITS_PATH, 6),
        ("topics", TOPICS, TOPICS_DIR, TOPICS_CREDITS_PATH, 3),
    ]

    total_found = total_skipped = total_written = 0

    for noun, catalogue, target_dir, credits_path, per_name in targets:
        wanted = [(q, s) for q, s in catalogue if args.only.lower() in (q + s).lower()]
        if not wanted:
            continue

        if args.download:
            target_dir.mkdir(parents=True, exist_ok=True)
        credits = load_credits(credits_path)

        print(f"\n=== {noun.upper()} — {len(wanted)} to check "
              f"({'fetching' if args.download else 'dry run'}) ===\n")

        found, skipped, written = run_catalogue(
            wanted, target_dir, credits, args, per_name
        )

        if args.download and written:
            credits_path.parent.mkdir(parents=True, exist_ok=True)
            credits_path.write_text(
                json.dumps(dict(sorted(credits.items())), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

        print(f"\n  {noun}: {found} usable, {skipped} already present, {written} written")
        total_found += found
        total_skipped += skipped
        total_written += written

    print(f"\nTOTAL — {total_found} usable, {total_skipped} already present, "
          f"{total_written} written")
    if not args.download and total_found:
        print("Dry run only. Re-run with --download to fetch these.")
    return 0


def run_catalogue(wanted, target_dir, credits, args, per_name=1):
    """Fetch one catalogue.

    Entries are grouped by slug first, because several search phrases may feed
    the same name - four searches for "sport" give four genuinely different
    photographs where four results from one search are usually four angles on
    the same subject.
    """
    from collections import OrderedDict

    grouped: "OrderedDict[str, list[str]]" = OrderedDict()
    for query, slug in wanted:
        grouped.setdefault(slug, []).append(query)

    found = skipped = written = 0

    for slug, queries in grouped.items():
        existing = sorted(target_dir.glob(f"{slug}-*")) + sorted(target_dir.glob(f"{slug}.*"))
        existing = [p for p in existing if p.suffix.lower() in
                    (".jpg", ".jpeg", ".png", ".webp")]
        if len(existing) >= per_name:
            print(f"  = {slug:<26} {len(existing)} already present, left alone")
            skipped += 1
            continue

        need = per_name - len(existing)
        candidates: list[tuple[str, str, str, str]] = []
        seen_titles = {p.stem for p in existing}

        for query in queries:
            if len(candidates) >= need:
                break
            pages = search(query)
            time.sleep(args.delay)
            for pick in choose_many(pages, need - len(candidates)):
                if pick[1] in seen_titles:
                    continue
                seen_titles.add(pick[1])
                candidates.append(pick)

        if not candidates:
            print(f"  ? {slug:<26} nothing suitable")
            continue

        found += len(candidates)
        index = len(existing)
        for url, _title, artist, licence in candidates:
            index += 1
            # A single photograph keeps the bare name so existing files and
            # credits stay valid; pools are numbered.
            name = f"{slug}.jpg" if per_name == 1 else f"{slug}-{index:02d}.jpg"
            credit = f"{artist} / {licence} via Wikimedia Commons"
            print(f"  + {name:<30} {artist[:26]:<26} {licence}")

            if not args.download:
                continue
            if download_and_crop(url, target_dir / name):
                # The card renders "Photo: " itself, so the stored credit must
                # not repeat it or the line reads "Photo: Photo: ...".
                credits[Path(name).stem] = credit
                written += 1
                time.sleep(args.delay)

    return found, skipped, written


if __name__ == "__main__":
    sys.exit(main())
