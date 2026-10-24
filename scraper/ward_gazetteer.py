"""Offline street / place / township lookup for Rochdale borough wards.

The data comes from ward_gazetteer.json, which build_ward_gazetteer.py writes
from OpenStreetMap street and place locations, each assigned to its council
ward by the ONS postcode directory (via postcodes.io). Nothing here touches the
network: every pipeline lane reads the same committed file, so a story's ward
cannot change between runs unless the data does.

Rules, deliberately conservative:
* a street counts only when every mapped section of it lies in ONE ward
  (Manchester Road crosses several wards, so it never decides a ward);
* a place name must be used as a place ("in Belfield", "Syke residents"),
  because Belfield, Hamer, Birch, Langley and Rhodes are also surnames;
* a town name alone (Heywood, Middleton, Littleborough) gives a TOWNSHIP,
  never a ward, because each town spans several wards;
* "Rochdale" alone is the borough's name as often as the town's, so it gives
  neither.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GAZETTEER_PATH = ROOT / "ward_gazetteer.json"

# The council's own grouping (mirrors generate_ward_pages.TOWNSHIPS).
TOWNSHIPS = {
    "Rochdale": ("Balderstone and Kirkholt", "Bamford", "Castleton", "Central Rochdale", "Healey",
                 "Kingsway", "Milkstone and Deeplish", "Norden", "Smallbridge and Firgrove",
                 "Spotland and Falinge"),
    "Heywood": ("North Heywood", "West Heywood", "Hopwood Hall"),
    "Middleton": ("East Middleton", "North Middleton", "South Middleton", "West Middleton"),
    "Pennines": ("Littleborough Lakeside", "Milnrow and Newhey", "Wardle, Shore and West Littleborough"),
}
WARD_TOWNSHIP = {ward: township for township, wards in TOWNSHIPS.items() for ward in wards}

# Town names that identify a township but not a ward.
TOWN_TOWNSHIP = {
    "Heywood": "Heywood",
    "Middleton": "Middleton",
    "Littleborough": "Pennines",
    "Milnrow": "Pennines",
    "Newhey": "Pennines",
}

# Street names this common occur in almost every northern town, so a unique
# Rochdale match still needs the story to place itself in that ward's township.
GENERIC_STREET_FIRST_WORDS = {
    "albert", "bridge", "chapel", "church", "east", "george", "green", "high", "john",
    "king", "main", "market", "mill", "new", "north", "park", "princess", "queen",
    "railway", "school", "south", "station", "union", "victoria", "west", "york",
}

PLACE_NOUNS = r"(?:residents?|community|park|school|village|estate|centre|library|church|mosque|road|area|neighbourhood)"
PLACE_PREP = r"(?:in|at|across|around|near|from|through|to)"
ROAD_AFTER = r"(?!\s+(?:Road|Street|Lane|Avenue|Drive|Close|Way|Brow|Terrace|Crescent|Grove|Place|Fold|Gardens|Square|Walk|Parade|Row|Hall|House|Mill|Farm)\b)"


@lru_cache(maxsize=4)
def _load(path_text: str) -> dict:
    try:
        data = json.loads(Path(path_text).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"streets": {}, "places": {}}
    if not isinstance(data, dict):
        return {"streets": {}, "places": {}}
    data.setdefault("streets", {})
    data.setdefault("places", {})
    return data


def gazetteer(path: Path | None = None) -> dict:
    return _load(str(path or GAZETTEER_PATH))


@lru_cache(maxsize=4)
def _street_regex(path_text: str):
    unique = {name: wards[0] for name, wards in _load(path_text)["streets"].items()
              if isinstance(wards, list) and len(wards) == 1 and len(name) >= 6}
    if not unique:
        return None, {}
    names = sorted(unique, key=len, reverse=True)
    # Case-sensitive on purpose: "Will Place" in "...will place..." is a sentence,
    # not an address.
    pattern = re.compile(r"(?<![\w-])(" + "|".join(re.escape(n) for n in names) + r")(?![\w-])")
    return pattern, unique


def streets_in(text: str, path: Path | None = None) -> list[tuple[str, str]]:
    """(street, ward) for every single-ward street named in the text."""
    pattern, unique = _street_regex(str(path or GAZETTEER_PATH))
    if pattern is None:
        return []
    found = []
    for match in pattern.finditer(text or ""):
        name = match.group(1)
        if (name, unique[name]) not in found:
            found.append((name, unique[name]))
    return found


def places_in(text: str, path: Path | None = None) -> list[tuple[str, str]]:
    """(place, ward) for single-ward places used as places in the text."""
    found = []
    for name, wards in gazetteer(path)["places"].items():
        if not isinstance(wards, list) or len(wards) != 1 or name in TOWN_TOWNSHIP or name == "Rochdale":
            continue
        n = re.escape(name)
        pattern = (r"\b" + PLACE_PREP + r"\s+" + n + r"\b" + ROAD_AFTER
                   + r"|\b" + n + r"\s+" + PLACE_NOUNS + r"\b")
        if re.search(pattern, text or "", re.I) and (name, wards[0]) not in found:
            found.append((name, wards[0]))
    return found


def township_in(text: str) -> str:
    """A township only when exactly one is named as a place."""
    named = set()
    for town, township in TOWN_TOWNSHIP.items():
        if re.search(r"\b" + re.escape(town) + r"\b" + ROAD_AFTER, text or ""):
            named.add(township)
    return named.pop() if len(named) == 1 else ""


def place_in_text(text: str, path: Path | None = None) -> str:
    """A borough place named in a headline, for an illustrative file image."""
    for name, _ in places_in(text, path):
        return name
    for town in ("Littleborough", "Heywood", "Middleton", "Milnrow", "Newhey"):
        if re.search(r"\b" + town + r"\b" + ROAD_AFTER, text or ""):
            return town
    return ""


def generic_street(name: str) -> bool:
    """"Church Street" or "Albert Road" is generic; "Albert Royds Street" is not."""
    words = name.split()
    return len(words) == 2 and words[0].casefold() in GENERIC_STREET_FIRST_WORDS
