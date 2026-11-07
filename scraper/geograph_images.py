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
        if row["title"] and row["page_url"] and row["thumb"]:
            items.append(row)
    return items


def full_size(thumb: str) -> str:
    """Geograph thumbnails end _<w>x<h>.jpg; the 640px original drops it."""
    return re.sub(r"_\d+x\d+(\.jpe?g)$", r"\1", thumb, flags=re.I)


def title_matches(subject: str, title: str) -> bool:
    words = [w for w in re.findall(r"[a-z0-9]+", subject.casefold().replace("’", "'")) if w not in {"the", "and", "of", "s"}]
    low = title.casefold().replace("’", "'")
    return bool(words) and all(re.search(r"\b" + re.escape(w) + r"\b", low) for w in words)


def search(subject: str, article: dict[str, Any], timeout: int = 10) -> list[dict[str, str]]:
    """Geograph photos of the named place near the story's town, best first."""
    key = api_key()
    if not key or not subject:
        return []
    import requests
    lat, lon = TOWN_CENTRES[town_for(article)]
    params = {"key": key, "text": subject, "location": f"{lat},{lon}", "distance": GEOGRAPH_RADIUS_KM,
              "perpage": 30, "format": "RSS2.0"}
    response = requests.get(API + "?" + urlencode(params), headers={"User-Agent": USER_AGENT}, timeout=timeout)
    response.raise_for_status()
    return [row for row in parse_rss(response.text) if title_matches(subject, row["title"])]


def as_commons_page(row: dict[str, str], town: str) -> dict[str, Any]:
    """The shape image_hierarchy.acceptable() checks, so a cached Geograph
    match is re-checked exactly like a Commons one."""
    return {"title": "File:" + row["title"], "imageinfo": [{"mime": "image/jpeg", "extmetadata": {
        "LicenseShortName": {"value": LICENCE}, "ImageDescription": {"value": row["title"]},
        "Categories": {"value": town.title() + "|Rochdale"}}}]}
