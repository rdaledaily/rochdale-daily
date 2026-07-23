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

    temporary = destination.with_suffix(".tmp")
    temporary.write_bytes(raw)
    try:
        image = ImageOps.exif_transpose(Image.open(temporary)).convert("RGB")
        cropped = ImageOps.fit(image, (WIDTH, HEIGHT), method=Image.Resampling.LANCZOS)
        destination.parent.mkdir(parents=True, exist_ok=True)
        cropped.save(destination, "JPEG", quality=88, optimize=True)
        return True
    except Exception as error:  # noqa: BLE001
        print(f"    ! could not process image: {error}")
        return False
    finally:
        temporary.unlink(missing_ok=True)


def load_credits() -> dict:
    try:
        data = json.loads(CREDITS_PATH.read_text(encoding="utf-8"))
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

    credits = load_credits()
    wanted = [(q, s) for q, s in PLACES if args.only.lower() in (q + s).lower()]

    print(f"{'FETCHING' if args.download else 'DRY RUN'} — {len(wanted)} places\n")

    found = skipped = written = 0
    for query, slug in wanted:
        existing = [p for p in PLACES_DIR.glob(f"{slug}.*")] if PLACES_DIR.is_dir() else []
        if existing:
            # A photograph already here was chosen deliberately. Never clobber it.
            print(f"  = {slug:<34} already present, left alone")
            skipped += 1
            continue

        pages = search(query)
        time.sleep(args.delay)
        picked = choose(pages)
        if picked is None:
            print(f"  ? {slug:<34} nothing suitable for \"{query}\"")
            continue

        url, title, artist, licence = picked
        found += 1
        credit = f"{artist} / {licence} via Wikimedia Commons"
        print(f"  + {slug:<34} {artist[:28]:<28} {licence}")

        if not args.download:
            continue

        if download_and_crop(url, PLACES_DIR / f"{slug}.jpg"):
            # The card renders "Photo: " itself, so the stored credit must not
            # repeat it or the line reads "Photo: Photo: ...".
            credits[slug] = credit
            written += 1
            time.sleep(args.delay)

    if args.download and written:
        CREDITS_PATH.parent.mkdir(parents=True, exist_ok=True)
        CREDITS_PATH.write_text(
            json.dumps(dict(sorted(credits.items())), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    print(f"\n{found} usable, {skipped} already present, {written} written")
    if not args.download and found:
        print("Dry run only. Re-run with --download to fetch these.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
