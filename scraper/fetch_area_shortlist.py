#!/usr/bin/env python3
"""Fetch candidate photographs for each Rochdale ward, for review.

This does not touch the site. It writes candidates to assets/img/review/ and
builds a contact sheet, review.html, showing every candidate with the search
that found it, the photographer and the licence. You look through it and copy
whatever you want into assets/img/cards/ yourself. Nothing is applied to a
story automatically - that is the whole point.

Searches use the landmarks from each ward rather than the ward name. Wikimedia
Commons has photographs of churches, stations, parks and pubs; it has nothing
filed under an abstract ward name, so "Kirkholt" returns nothing useful while
"Kirkholt Community Park" might.

Only licences permitting commercial use are accepted: CC0, public domain, CC BY
and CC BY-SA. Anything NonCommercial or NoDerivatives is rejected.

    python scraper/fetch_area_shortlist.py             # dry run, lists what it finds
    python scraper/fetch_area_shortlist.py --download  # write the images and sheet
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

REVIEW_DIR = Path("assets/img/review")
SHEET = REVIEW_DIR / "review.html"

WIDTH, HEIGHT = 1200, 675
FETCH_WIDTH = 1800
MIN_SOURCE_WIDTH = 800
CANDIDATES_PER_AREA = 3

ACCEPTED = ("cc0", "public domain", "pd-", "cc by 2.0", "cc by 3.0", "cc by 4.0",
            "cc by-sa 2.0", "cc by-sa 3.0", "cc by-sa 4.0")
REJECTED = ("nc", "noncommercial", "nd", "noderiv", "fair use", "non-free")

SKIP = ("map", "diagram", "logo", "coat of arms", "arms of", "chart", "plan of",
        "svg", "seal of", "flag of", "graph")

# Every search is pinned to Greater Manchester. Castleton and Bamford are far
# better known as Derbyshire villages, Middleton exists in a dozen counties, and
# Langley and Norden both have namesakes elsewhere - the unqualified name
# returns the wrong county's scenery.
QUALIFIER = "Rochdale Greater Manchester"

# (slug, ward name, landmarks to search)
AREAS: list[tuple[str, str, list[str]]] = [
    # A borough-wide image, for the 87 of 130 stories filed simply as
    # "rochdale" rather than to a ward. Deliberately wider views than
    # rochdale_town_centre, which is the shopping streets.
    ("rochdale_generic", "Rochdale", ["Rochdale skyline", "Rochdale panorama",
     "Rochdale Town Hall", "Rochdale Canal", "Rochdale from Blackstone Edge",
     "Rochdale viewed from the Pennines", "Broadfield Park Rochdale"]),
    ("kirkholt_balderstone", "Kirkholt", ["Kirkholt Community Primary School", "Oldham Road", "Kirkholt Community Park"]),
    ("bamford", "Bamford", ["Bamford Academy", "St Michael's Church, Bamford", "Bury Road", "The Grapes"]),
    ("castleton", "Castleton", ["Castleton railway station", "Manchester Road", "Stakehill Industrial Estate", "St Edward's Church of England Primary School", "St Martin's Church, Castleton", "Mayfield Rugby Club"]),
    ("rochdale_town_centre", "Rochdale Town Centre", ["Rochdale Town Hall", "Number One Riverside", "Rochdale Riverside", "Rochdale Exchange Shopping Centre", "Rochdale Interchange", "Rochdale Town Centre tram stop"]),
    ("boarshaw", "Boarshaw", ["Oldham Road", "Alkrington Woods", "Cardinal Langley Roman Catholic High School"]),
    ("healey_shawclough", "Healey", ["Thrum Hall Methodist Shawclough", "Shawclough Primary School", "Healey Dell Nature Reserve", "Christ Church Healey", "The Talbot Head Pub", "Healey Dell Tearooms"]),
    ("hopwood", "Hopwood", ["Hopwood Hall College, Middleton Campus", "Rochdale Sixth Form College", "Hopwood Hall", "Rochdale Road", "Kingsway Business Park", "Kingsway Business Park tram stop"]),
    ("kingsway_newbold", "Kingsway", ["Kingsway Business Park", "Kingsway Retail Park", "Kingsway Business Park tram stop", "Newbold tram stop"]),
    ("littleborough_smithy_bridge", "Littleborough", ["Hollingworth Lake Country Park", "Littleborough railway station", "Smithy Bridge railway station", "Church Street", "Halifax Road", "Littleborough Sports Club"]),
    ("milkstone_deeplish", "Milkstone", ["Milkstone Road", "Neeli Mosque", "Deeplish Primary Academy", "Deeplish"]),
    ("milnrow_newhey", "Milnrow", ["Milnrow tram stop", "Newhey tram stop", "Dale Street", "Huddersfield Road", "Milnrow Parish Church of England Primary School", "Newhey"]),
    ("norden", "Norden", ["Edenfield Road", "Norden Community Primary School", "The Norden Arms", "The Brown Cow", "Stocco"]),
    ("north_heywood", "North Heywood", ["York Street", "Queen's Park, Heywood", "Heywood Sports Village", "Heywood Civil", "Heywood Memorial"]),
    ("middleton_town_centre", "Middleton Town Centre", ["Middleton Bus Station", "Middleton Shopping Centre", "St Leonard's Church, Middleton", "Long Street"]),
    ("smallbridge_firgrove", "Smallbridge", ["Halifax Road", "Smallbridge Church of England Primary School", "Firgrove"]),
    ("alkrington_mills_hill", "Alkrington", ["Mills Hill railway station", "Alkrington Woods Nature Reserve", "Mills Hill"]),
    ("spotland_falinge", "Spotland", ["Crown Oil Arena", "Falinge Park High School", "Hebron Pentecostal Church", "Edenfield Road", "Hollingworth Lake Campsite", "Spotland Mill"]),
    ("wardle_shore", "Wardle", ["Wardle Academy", "Ramsden Road"]),
    ("darnhill", "Darnhill", ["Manchester Road", "Hareshill Business Park", "Holy Family Roman Catholic and Church of England College"]),
    ("langley", "Langley", ["Bowlee Community Park", "Windermere Road"]),]


def get_json(params: dict):
    request = Request(f"{API}?{urlencode(params)}",
                      headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as error:  # noqa: BLE001
        print(f"      ! {error}")
        return None


def strip_html(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))).strip()


def licence_ok(licence: str) -> bool:
    low = licence.lower()
    for bad in REJECTED:
        if re.search(rf"\b{re.escape(bad)}\b", low):
            return False
    return any(good in low for good in ACCEPTED)


def is_photo(title: str) -> bool:
    low = title.lower()
    return not any(word in low for word in SKIP)


def search(phrase: str) -> list[dict]:
    data = get_json({
        "action": "query", "format": "json", "formatversion": "2",
        "generator": "search", "gsrsearch": f"{phrase} filetype:bitmap",
        "gsrnamespace": "6", "gsrlimit": "8",
        "prop": "imageinfo", "iiprop": "url|size|extmetadata",
        "iiurlwidth": str(FETCH_WIDTH),
    })
    return (data or {}).get("query", {}).get("pages", []) or []


def usable(page: dict):
    title = page.get("title", "")
    if not is_photo(title):
        return None
    info = (page.get("imageinfo") or [{}])[0]
    meta = info.get("extmetadata") or {}
    licence = strip_html((meta.get("LicenseShortName") or {}).get("value", ""))
    if not licence_ok(licence):
        return None
    width, height = int(info.get("width") or 0), int(info.get("height") or 0)
    if width < MIN_SOURCE_WIDTH or (height and width / height < 1.1):
        return None
    url = info.get("thumburl") or info.get("url")
    if not url:
        return None
    artist = strip_html((meta.get("Artist") or {}).get("value", "")) or "Unknown"
    return {"url": url, "title": title, "artist": artist, "licence": licence, "width": width}


def download(url: str, destination: Path) -> bool:
    try:
        with urlopen(Request(url, headers={"User-Agent": UA}), timeout=60) as response:
            raw = response.read()
        image = ImageOps.exif_transpose(Image.open(BytesIO(raw))).convert("RGB")
        destination.parent.mkdir(parents=True, exist_ok=True)
        ImageOps.fit(image, (WIDTH, HEIGHT), method=Image.Resampling.LANCZOS).save(
            destination, "JPEG", quality=88, optimize=True)
        return True
    except Exception as error:  # noqa: BLE001
        print(f"      ! {error}")
        return False


def build_sheet(found: dict) -> str:
    blocks = []
    for slug, entries in found.items():
        cards = "".join(
            f'<figure><img src="{html.escape(e["file"])}" loading="lazy">'
            f'<figcaption><b>{html.escape(e["file"])}</b><br>'
            f'found via &ldquo;{html.escape(e["via"])}&rdquo;<br>'
            f'{html.escape(e["artist"])} &middot; {html.escape(e["licence"])}'
            f'</figcaption></figure>' for e in entries)
        if not cards:
            cards = '<p class="none">Nothing usable found for this ward.</p>'
        blocks.append(f'<section><h2>{html.escape(slug)}</h2><div class="row">{cards}</div></section>')
    return f"""<!DOCTYPE html>
<html lang="en-GB"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Ward photo candidates</title>
<style>
 body{{margin:0;padding:24px;background:#11151d;color:#e8ecf2;
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif}}
 h1{{font-size:20px}} p.lede{{color:#8b93a3;font-size:14px;max-width:70ch}}
 section{{margin:28px 0;border-top:1px solid #2a2f3a;padding-top:14px}}
 h2{{font-size:15px;color:#22d3ee;font-family:ui-monospace,Menlo,monospace}}
 .row{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}}
 figure{{margin:0;background:#151a24;border:1px solid #2a2f3a;border-radius:8px;overflow:hidden}}
 figure img{{width:100%;display:block}}
 figcaption{{padding:9px 11px;font-size:11px;color:#8b93a3;line-height:1.5}}
 figcaption b{{color:#e8ecf2;font-family:ui-monospace,Menlo,monospace;font-size:11px}}
 .none{{color:#8b93a3;font-size:13px}}
</style></head><body>
<h1>Ward photo candidates</h1>
<p class="lede">Every image below is licensed for commercial use and cropped to the
card size. Nothing here is used by the site. To use one, copy it into
<code>assets/img/cards/</code> and rename it to the article slug, then add its
credit line to that folder&rsquo;s <code>credits.json</code>.</p>
{''.join(blocks)}
</body></html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--only", default="")
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()

    wanted = [a for a in AREAS if args.only.lower() in (a[0] + a[1]).lower()]
    print(f"{'FETCHING' if args.download else 'DRY RUN'} — {len(wanted)} wards\n")

    found: dict[str, list[dict]] = {}
    total = 0

    for slug, name, landmarks in wanted:
        print(f"  {slug}")
        picks: list[dict] = []
        seen: set[str] = set()
        # The ward name itself is tried last, and only if the landmarks failed.
        for phrase in landmarks + [name]:
            if len(picks) >= CANDIDATES_PER_AREA:
                break
            query = phrase if "rochdale" in phrase.lower() else f"{phrase} {QUALIFIER}"
            for page in search(query):
                if len(picks) >= CANDIDATES_PER_AREA:
                    break
                candidate = usable(page)
                if not candidate or candidate["title"] in seen:
                    continue
                seen.add(candidate["title"])
                candidate["via"] = phrase
                picks.append(candidate)
            time.sleep(args.delay)

        found[slug] = []
        for index, candidate in enumerate(picks, 1):
            filename = f"{slug}-{index}.jpg"
            print(f"      {filename:<34} {candidate['artist'][:24]:<24} "
                  f"{candidate['licence']}   via \"{candidate['via']}\"")
            entry = {"file": filename, "via": candidate["via"],
                     "artist": candidate["artist"], "licence": candidate["licence"]}
            if args.download and download(candidate["url"], REVIEW_DIR / filename):
                found[slug].append(entry)
                total += 1
                time.sleep(args.delay)
            elif not args.download:
                found[slug].append(entry)

        if not picks:
            print("      nothing usable found")

    if args.download:
        REVIEW_DIR.mkdir(parents=True, exist_ok=True)
        SHEET.write_text(build_sheet(found), encoding="utf-8")
        print(f"\n{total} images written to {REVIEW_DIR}/")
        print(f"Open {SHEET} to review them.")
    else:
        print("\nDry run. Re-run with --download to fetch these and build the contact sheet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
