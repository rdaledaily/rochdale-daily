#!/usr/bin/env python3
"""Street and building photographs from Geograph, the CC-licensed photo
archive that covers almost every street in Britain.

Why this exists
---------------
Measured 7 Nov 2026: 56 of 170 stories on beige cards name a street or
building, but Wikimedia Commons holds only part of Geograph's archive, so
most of those searches find nothing. Geograph's own API covers the rest.

How a photo is accepted
-----------------------
* searched by the place name, within GEOGRAPH_RADIUS_KM of the centre of the
  story's town (so "Jubilee Park" for a Middleton story never finds Bolton's);
* every word of the place name must be in the photo's title;
* Geograph photos are CC BY-SA 2.0: credited to the photographer with the
  licence and a link to the photo page, as Geograph's terms require.

The key
-------
Needs a free Geograph API key in the GEOGRAPH_API_KEY environment variable
(https://www.geograph.org.uk/get-api-key.php). Without it every search
returns nothing and the pipeline carries on exactly as before.
"""
from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import urlencode

API = "https://api.geograph.org.uk/syndicator.php"
USER_AGENT = "RochdaleDailyEditorialImages/1.0 (news@rochdaledaily.co.uk)"
LICENCE = "CC BY-SA 2.0"
LICENCE_URL = "https://creativecommons.org/licenses/by-sa/2.0/"
GEOGRAPH_RADIUS_KM = float(os.getenv("GEOGRAPH_RADIUS_KM", "4"))

# Town centres (latitude, longitude). A story's area slug is matched to the
# first town it names; anything else searches around Rochdale town centre.
TOWN_CENTRES = {
    "rochdale": (53.6158, -2.1561), "middleton": (53.5520, -2.2010), "heywood": (53.5930, -2.2190),
    "littleborough": (53.6440, -2.0950), "milnrow": (53.6080, -2.1110), "newhey": (53.5980, -2.0960),
    "whitworth": (53.6560, -2.1770), "wardle": (53.6470, -2.1330), "norden": (53.6280, -2.2050),
    "bamford": (53.6150, -2.2050), "castleton": (53.5900, -2.1800), "smallbridge": (53.6300, -2.1250),
    "kirkholt": (53.5990, -2.1680), "balderstone": (53.6040, -2.1440), "spotland": (53.6210, -2.1800),
    "deeplish": (53.6040, -2.1540), "healey": (53.6340, -2.1640), "syke": (53.6290, -2.1480),
}


def api_key() -> str:
    return os.getenv("GEOGRAPH_API_KEY", "").strip()


def town_for(article: dict[str, Any]) -> str:
    area = str(article.get("area") or "").casefold()
    for word in re.findall(r"[a-z]+", area):
        if word in TOWN_CENTRES:
            return word
    return "rochdale"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_rss(text: str) -> list[dict[str, str]]:
    """Items from Geograph's RSS 2.0 feed: title, photo page, photographer and
    an image URL (thumbnail; the 640px original is derived from it)."""
    items = []
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return items
    for item in root.iter():
        if _local(item.tag) != "item":
            continue
        row = {"title": "", "page_url": "", "author": "", "thumb": ""}
        for child in item:
            name = _local(child.tag)
            value = (child.text or "").strip()
            if name == "title":
                row["title"] = value
            elif name == "link":
                row["page_url"] = value
            elif name in {"creator", "author"} and value:
                row["author"] = re.sub(r"^.*\((.+)\)$", r"\1", value)
            elif child.get("url") and re.search(r"\.jpe?g", child.get("url", ""), re.I):
                row["thumb"] = row["thumb"] or child.get("url", "")
            elif name == "description" and not row["thumb"]:
                found = re.search(r'src="([^"]+\.jpe?g)"', value, re.I)
                row["thumb"] = found.group(1) if found else ""
        if row["title"] and row["page_url"]:
            items.append(row)  # an item with no image link is counted, then skipped by search()
    return items


def full_size(thumb: str) -> str:
    """Geograph thumbnails end _<w>x<h>.jpg; the 640px original drops it."""
    return re.sub(r"_\d+x\d+(\.jpe?g)$", r"\1", thumb, flags=re.I)


_STREET_TYPES = frozenset("road street lane avenue way drive close crescent terrace brow row".split())


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", text.casefold().replace("’", "'").replace("'", ""))]


def title_matches(subject: str, title: str) -> bool:
    """The place name appears in the photo title in order, with at most one
    extra word inside it ("St Andrew's Church" finds "St Andrew's Parish
    Church"), and a park, mill or church is not a road of the same name.

    Measured 7 Nov 2026 (first 33 matches): any-order word matching took
    "Norden Road" to "Edenfield Road, Norden", "Rochdale House" to "Craig Lee
    House ... Rochdale" and "Queen's Park" to "Queen's Park Road"."""
    want = [w for w in _words(subject) if w not in {"the", "of", "and"}]
    have = _words(title)
    if not want:
        return False
    for start in range(len(have)):
        if have[start] != want[0]:
            continue
        i, j, skipped = start, 0, 0
        while i < len(have) and j < len(want):
            if have[i] == want[j]:
                j += 1
            elif j and skipped == 0:
                skipped = 1
            else:
                break
            i += 1
        if j == len(want):
            following = have[i] if i < len(have) else ""
            if following in _STREET_TYPES and want[-1] not in _STREET_TYPES:
                continue
            return True
    return False


# Version of the search: a cached result from an older version is searched
# again. 2: the first live run (7 Nov 2026) returned no photo for 118 places.
# 3: expand=1, so replies carry image links. 4: the place name must appear in
# order in the photo title (title_matches). 5: a known street is searched
# around its own postcode, not the town centre (street_centre).
SEARCH_VERSION = 5
# What the last reply looked like, with the key removed: written to the
# Commons cache as "__geograph_probe__" so a run's log of Geograph is visible.
LAST_REPLY: dict[str, Any] = {}


# --------------------------------------------------------------------------
# Where a street is (8 Nov 2026)
# --------------------------------------------------------------------------
# rochdale_streets.json lists every street in OL11, OL12 and OL16 with one
# postcode per postcode sector it runs through (from the full Crystalroof
# postcode lists). A street story's Geograph search is centred on that
# street, within STREET_RADIUS_KM, instead of 4 km round the town centre, so
# "Halifax Road" finds Rochdale's Halifax Road. Where a name runs through
# several sectors, the one nearest the story's town is used. Postcode
# coordinates come from postcodes.io (free, no key). Streets outside those
# three districts, or a failed lookup, search round the town centre as before.
STREET_RADIUS_KM = float(os.getenv("GEOGRAPH_STREET_RADIUS_KM", "0.8"))
STREETS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rochdale_streets.json")
_STREETS: dict[str, Any] | None = None
_POSTCODE_CACHE: dict[str, tuple[float, float] | None] = {}


def streets() -> dict[str, Any]:
    global _STREETS
    if _STREETS is None:
        try:
            import json
            with open(STREETS_FILE, encoding="utf-8") as fh:
                _STREETS = json.load(fh).get("streets", {})
        except (OSError, ValueError):
            _STREETS = {}
    return _STREETS


def postcode_location(postcode: str, timeout: int = 8) -> tuple[float, float] | None:
    if postcode in _POSTCODE_CACHE:
        return _POSTCODE_CACHE[postcode]
    loc = None
    try:
        import requests
        r = requests.get("https://api.postcodes.io/postcodes/" + postcode.replace(" ", ""),
                         headers={"User-Agent": USER_AGENT}, timeout=timeout)
        if r.ok:
            res = (r.json() or {}).get("result") or {}
            if res.get("latitude") is not None and res.get("longitude") is not None:
                loc = (float(res["latitude"]), float(res["longitude"]))
    except Exception:
        loc = None
    _POSTCODE_CACHE[postcode] = loc
    return loc


def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    import math
    dlat, dlon = math.radians(b[0] - a[0]), math.radians(b[1] - a[1])
    h = math.sin(dlat / 2) ** 2 + math.cos(math.radians(a[0])) * math.cos(math.radians(b[0])) * math.sin(dlon / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def street_centre(subject: str, article: dict[str, Any]) -> tuple[float, float, str] | None:
    """(lat, lon, postcode) on the named street nearest the story's town, or
    None when the street is not listed or no postcode could be located."""
    rec = streets().get(re.sub(r"\s+", " ", subject.strip()).casefold())
    if not rec:
        return None
    town = TOWN_CENTRES[town_for(article)]
    best = None
    for pc in rec.get("postcodes", []):
        loc = postcode_location(pc)
        if loc and (best is None or _km(loc, town) < _km(best[:2], town)):
            best = (loc[0], loc[1], pc)
    return best


def search(subject: str, article: dict[str, Any], timeout: int = 10) -> list[dict[str, str]]:
    """Geograph photos of the named place near the story's town, best first."""
    key = api_key()
    if not key or not subject:
        return []
    import requests
    centre = street_centre(subject, article)
    if centre:
        (lat, lon), radius = centre[:2], STREET_RADIUS_KM
    else:
        (lat, lon), radius = TOWN_CENTRES[town_for(article)], GEOGRAPH_RADIUS_KM
    params = {"key": key, "text": subject, "location": f"{lat},{lon}", "distance": radius,
              "perpage": 30, "format": "RSS2.0",
              # Geograph's API page: expand=1 "includes the thumbnail as HTML
              # in the description". Without it the RSS reply carries no image
              # link at all, which is why the first run (7 Nov 2026) found
              # nothing for 118 places.
              "expand": 1}
    response = requests.get(API + "?" + urlencode(params), headers={"User-Agent": USER_AGENT}, timeout=timeout)
    rows = parse_rss(response.text) if response.ok else []
    LAST_REPLY.clear()
    LAST_REPLY.update({
        "subject": subject, "http": response.status_code,
        "centre": ("street " + centre[2]) if centre else "town " + town_for(article), "radius_km": radius,
        "content_type": response.headers.get("content-type", ""),
        "items_in_reply": len(rows), "items_with_image": sum(1 for r in rows if r["thumb"]),
        "first_titles": [r["title"] for r in rows[:5]],
        "head": response.text[:400].replace(key, "[key]"),
        "first_item": (re.search(r"<item>.*?</item>", response.text, re.S) or re.search(r"$", ""))
                      .group(0)[:900].replace(key, "[key]"),
    })
    response.raise_for_status()
    return [row for row in rows if row["thumb"] and title_matches(subject, row["title"])]


def as_commons_page(row: dict[str, str], town: str) -> dict[str, Any]:
    """The shape image_hierarchy.acceptable() checks, so a cached Geograph
    match is re-checked exactly like a Commons one."""
    return {"title": "File:" + row["title"], "imageinfo": [{"mime": "image/jpeg", "extmetadata": {
        "LicenseShortName": {"value": LICENCE}, "ImageDescription": {"value": row["title"]},
        "Categories": {"value": town.title() + "|Rochdale"}}}]}


# --------------------------------------------------------------------------
# Town photos for stories that name no place (editor's decision, 7 Nov 2026)
# --------------------------------------------------------------------------
# About 84 live and 400 archived stories name no street or building. They get
# a general Geograph photo of their own town, varied (no photo on more than
# TOWN_PHOTO_MAX_USES stories), captioned as a file photo of the town. Never
# on crime, police, sensitive or sponsored stories (image_hierarchy).
TOWN_POOL_VERSION = 1
TOWN_PHOTO_MAX_USES = 2
TOWN_RADIUS_KM = float(os.getenv("GEOGRAPH_TOWN_RADIUS_KM", "1.5"))
_ADDRESS_RE = re.compile(r"^\s*\d|\b\d+\s*(?:to|-|&)\s*\d+\b|\bno\.?\s*\d|\b(?:flat|apartment|bungalow|semi|garden of)\b",
                         re.I)
_SCENE_RE = re.compile(r"\b(?:church|chapel|park|hall|mill|canal|station|market|square|centre|street|road|lane|"
                       r"bridge|library|museum|memorial|war memorial|reservoir|lake|clough|moor|view|town|village|"
                       r"precinct|high street|viaduct|cenotaph|gardens?|fold|brow|cottages|pub|inn|arms|hotel)\b", re.I)


def suitable_town_photo(title: str, town: str) -> bool:
    """A street scene, landmark or view, not a numbered private house, and
    about this town or a recognisable kind of place."""
    if not title or _ADDRESS_RE.search(title):
        return False
    return bool(re.search(r"\b" + re.escape(town) + r"\b", title, re.I) or _SCENE_RE.search(title))


def town_pool(town: str, timeout: int = 15) -> list[dict[str, str]]:
    """Up to 100 Geograph photos within TOWN_RADIUS_KM of the town centre that
    are suitable town photos (empty without a key)."""
    key = api_key()
    if not key:
        return []
    import requests
    lat, lon = TOWN_CENTRES.get(town, TOWN_CENTRES["rochdale"])
    params = {"key": key, "location": f"{lat},{lon}", "distance": TOWN_RADIUS_KM, "perpage": 100,
              "format": "RSS2.0", "expand": 1}
    response = requests.get(API + "?" + urlencode(params), headers={"User-Agent": USER_AGENT}, timeout=timeout)
    response.raise_for_status()
    return [row for row in parse_rss(response.text) if row["thumb"] and suitable_town_photo(row["title"], town)]


def pick_town_photo(pool: list[dict[str, str]], used_by: dict[str, list[str]], slug: str) -> dict[str, str] | None:
    """The story's photo from the pool: the one it already has, else the first
    with room, starting from a position fixed by the slug so neighbouring
    stories spread across the pool."""
    if not pool:
        return None
    for row in pool:
        if slug in used_by.get(row["page_url"], []):
            return row
    import hashlib
    start = int(hashlib.sha256(slug.encode()).hexdigest()[:8], 16) % len(pool)
    for offset in range(len(pool)):
        row = pool[(start + offset) % len(pool)]
        if len(used_by.get(row["page_url"], [])) < TOWN_PHOTO_MAX_USES:
            return row
    return None
