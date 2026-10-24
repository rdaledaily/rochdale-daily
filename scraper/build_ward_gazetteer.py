#!/usr/bin/env python3
"""Build ward_gazetteer.json and ward_postcode_evidence.json.

Runs in GitHub Actions (the newsroom sandbox cannot reach these services).

1. OpenStreetMap (Overpass): every named street section and every named
   village / neighbourhood / hamlet / locality inside Rochdale borough, with a
   representative point for each.
2. postcodes.io (ONS Postcode Directory, OGL): the council ward of the nearest
   postcode to each point. A name keeps every ward its sections fall in, so a
   street that crosses wards is recorded as such and never decides a ward.
3. Every full postcode printed in a published article is looked up directly and
   cached for ward_decision's postcode-verified step.

No fallback data: if a service fails or the borough cannot be found, the build
stops with a named reason and the previous committed files stay as they are.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scraper"))
from selection_policy import ROCHDALE_WARDS  # noqa: E402

UA = {"User-Agent": "RochdaleDailyWardGazetteer/1.0 (news@rochdaledaily.co.uk)"}
OVERPASS = ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter")
POSTCODES = "https://api.postcodes.io/postcodes"
POSTCODE_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\b", re.I)

QUERY = """[out:json][timeout:240];
area["boundary"="administrative"]["admin_level"="8"]["name"="Rochdale"]->.b;
(
  way["highway"]["name"]["highway"!~"^(proposed|construction|platform|bus_stop)$"](area.b);
  node["place"~"^(suburb|neighbourhood|quarter|village|hamlet|locality|isolated_dwelling)$"]["name"](area.b);
);
out tags center;"""


def ward_name(raw: str) -> str:
    """Map an ONS ward label onto the site's ward list ("&" vs "and", commas)."""
    key = re.sub(r"[^a-z]", "", str(raw or "").casefold().replace("&", "and"))
    for ward in ROCHDALE_WARDS:
        if re.sub(r"[^a-z]", "", ward.casefold()) == key:
            return ward
    return ""


def overpass() -> list[dict]:
    last = ""
    for url in OVERPASS:
        try:
            response = requests.post(url, data={"data": QUERY}, headers=UA, timeout=300)
            response.raise_for_status()
            return response.json().get("elements", [])
        except (requests.RequestException, ValueError) as exc:
            last = f"{url}: {type(exc).__name__} {exc}"
            time.sleep(5)
    raise SystemExit("Overpass unavailable - " + last)


def reverse(points: list[tuple[float, float]]) -> list[dict | None]:
    out: list[dict | None] = []
    for start in range(0, len(points), 100):
        chunk = points[start:start + 100]
        body = {"geolocations": [{"longitude": lon, "latitude": lat, "radius": 300, "limit": 1} for lat, lon in chunk]}
        for attempt in range(4):
            try:
                response = requests.post(POSTCODES, json=body, headers=UA, timeout=60)
                response.raise_for_status()
                results = response.json().get("result") or []
                break
            except (requests.RequestException, ValueError):
                if attempt == 3:
                    raise SystemExit("postcodes.io reverse geocoding failed repeatedly")
                time.sleep(3 * (attempt + 1))
        for item in results:
            hits = (item or {}).get("result") or []
            out.append(hits[0] if hits else None)
        time.sleep(0.2)
    return out


def lookup_postcodes(codes: list[str]) -> dict:
    found = {}
    for start in range(0, len(codes), 100):
        chunk = codes[start:start + 100]
        response = requests.post(POSTCODES, json={"postcodes": chunk}, headers=UA, timeout=60)
        response.raise_for_status()
        for item in response.json().get("result") or []:
            hit = (item or {}).get("result")
            if hit:
                key = hit["postcode"].replace(" ", "").upper()
                found[key] = {
                    "postcode": hit["postcode"],
                    "district": hit.get("admin_district"),
                    "ward": ward_name(hit.get("admin_ward")) or hit.get("admin_ward"),
                    "ons_ward": hit.get("admin_ward"),
                    "ward_code": (hit.get("codes") or {}).get("admin_ward"),
                }
        time.sleep(0.2)
    return found


def article_postcodes(root: Path) -> list[str]:
    codes = set()
    for path in (root / "articles").glob("*.html"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for outward, inward in POSTCODE_RE.findall(text):
            codes.add((outward + inward).upper())
    return sorted(codes)


def build(root: Path) -> dict:
    elements = overpass()
    named = [e for e in elements if (e.get("tags") or {}).get("name") and (e.get("center") or "lat" in e)]
    if len(named) < 1000:
        raise SystemExit(f"Only {len(named)} named features found for Rochdale borough - boundary query is wrong; not writing")
    points = [((e.get("center") or e)["lat"], (e.get("center") or e)["lon"]) for e in named]
    hits = reverse(points)
    streets: dict[str, Counter] = defaultdict(Counter)
    places: dict[str, Counter] = defaultdict(Counter)
    unmatched = Counter()
    outside = 0
    for element, hit in zip(named, hits):
        if not hit:
            continue
        if hit.get("admin_district") != "Rochdale":
            outside += 1
            continue
        ward = ward_name(hit.get("admin_ward"))
        if not ward:
            unmatched[hit.get("admin_ward")] += 1
            continue
        name = element["tags"]["name"].strip()
        (places if element["type"] == "node" else streets)[name][ward] += 1
    wards_seen = {w for c in list(streets.values()) + list(places.values()) for w in c}
    if unmatched or len(wards_seen) < len(ROCHDALE_WARDS):
        raise SystemExit(f"Ward names do not line up with the site's 20 wards: unmatched={dict(unmatched)} "
                         f"missing={sorted(set(ROCHDALE_WARDS) - wards_seen)}")
    return {
        "_docs": "Built by scraper/build_ward_gazetteer.py. Street and place points from OpenStreetMap "
                 "(ODbL, (c) OpenStreetMap contributors); wards from the ONS Postcode Directory via "
                 "postcodes.io (OGL). A name listing more than one ward never decides a ward on its own.",
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "counts": {
            "named_features": len(named), "outside_borough_points": outside,
            "streets": len(streets), "single_ward_streets": sum(1 for c in streets.values() if len(c) == 1),
            "places": len(places), "single_ward_places": sum(1 for c in places.values() if len(c) == 1),
        },
        "streets": {name: sorted(c) for name, c in sorted(streets.items())},
        "places": {name: sorted(c) for name, c in sorted(places.items())},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--postcodes-only", action="store_true")
    args = parser.parse_args()
    root = args.root
    if not args.postcodes_only:
        data = build(root)
        (root / "ward_gazetteer.json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print("Gazetteer:", json.dumps(data["counts"]))
    cache_path = root / "ward_postcode_evidence.json"
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    wanted = [code for code in article_postcodes(root) if code not in cache]
    if wanted:
        cache.update(lookup_postcodes(wanted))
    cache_path.write_text(json.dumps(dict(sorted(cache.items())), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    rochdale = sum(1 for v in cache.values() if v.get("district") == "Rochdale")
    print(f"Postcodes: {len(cache)} cached, {rochdale} in Rochdale borough, {len(wanted)} looked up this run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
