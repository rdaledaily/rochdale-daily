#!/usr/bin/env python3
"""Look up the ward of every full postcode that says where a story is.

Why this exists
---------------
ward_decision() has always had a postcode rule: a story naming a full postcode
takes the ward that postcode lies in. It read its answers from
ward_postcode_evidence.json, and nothing ever wrote that file, so the rule
never tagged a single story. This writes it.

Streets
-------
A short street named in a headline is placed the same way, with one more
check: the street's postcode and every postcode within 250 metres of it must
be in the same ward (run_streets). A street near a ward boundary is recorded
as such and never used. Answers go in ward_street_evidence.json.

What it does
------------
Collects the postcodes ward_decision would use (story_postcodes), asks
postcodes.io (free, no key, ONS data) about the ones not already on file, and
records each one's council district and ward. Postcodes outside the borough
and postcodes that do not exist are recorded too, so they are asked about once.

It runs inside normalise_public_theme, which every publishing lane calls just
before ward tags are stamped, and it never fails a run. With no network it
changes nothing and says so; the stories stay untagged until the next run. A Rochdale postcode whose
ward is not one of the twenty this site knows is reported as a warning, since
that means the ward list here is out of date.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from editorial_contract import (  # noqa: E402
    POSTCODE_EVIDENCE_PATH, STREET_CHECK_RADIUS_M, STREET_EVIDENCE_PATH, canonical_ward, story_postcodes, story_streets,
)

ROOT = Path(__file__).resolve().parent.parent
ARTICLES = ROOT / "articles.json"
API = "https://api.postcodes.io/postcodes"
BATCH = 100  # the service's limit for one bulk request
DOCS = {
    "purpose": "Which council ward each full postcode named in a story lies in. Written by scraper/ward_postcode_evidence.py from postcodes.io (ONS data); read by ward_decision in scraper/editorial_contract.py.",
    "do_not_edit": "Entries are looked up, not typed. Delete an entry to have it looked up again.",
}

STREET_DOCS = {
    "purpose": "Which ward each short street named in a headline lies in, and whether it is clear of a ward boundary. Written by scraper/ward_postcode_evidence.py from postcodes.io (ONS data); read by ward_decision in scraper/editorial_contract.py.",
    "single_ward": f"true only when every postcode within {STREET_CHECK_RADIUS_M} metres of the street's postcode is in the same ward. A street near a boundary is recorded but never used to tag a story.",
    "do_not_edit": "Entries are looked up, not typed. Delete an entry to have it looked up again.",
}
# One request per street. A first run has a few dozen to do; the cap keeps a
# slow service from holding up publication, and the rest follow next run.
STREETS_PER_RUN = 40

Fetch = Callable[[list[str]], list[dict[str, Any]]]
FetchNearest = Callable[[str], "list[dict[str, Any]] | None"]


def fetch_nearest(postcode: str) -> list[dict[str, Any]] | None:
    """Postcodes within STREET_CHECK_RADIUS_M of this one (itself included),
    or None when the service does not know the postcode."""
    request = urllib.request.Request(
        f"{API}/{postcode}/nearest?radius={STREET_CHECK_RADIUS_M}&limit=100",
        headers={"Accept": "application/json",
                 "User-Agent": "RochdaleDaily/1.0 (+https://rochdaledaily.co.uk; news@rochdaledaily.co.uk)"})
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            return (json.loads(response.read().decode("utf-8")) or {}).get("result") or []
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def street_entry(street: str, postcode: str, nearby: list[dict[str, Any]] | None, today: str) -> dict[str, Any]:
    if nearby is None:
        return {"street": street, "postcode": postcode, "found": False, "checked": today}
    own = next((row for row in nearby if str(row.get("postcode") or "").replace(" ", "").upper() == postcode), None)
    if own is None:
        # The answer must include the street's own postcode; without it there
        # is nothing to compare the neighbours against.
        return {"street": street, "postcode": postcode, "found": False, "checked": today}
    district = str(own.get("admin_district") or "")
    ward = canonical_ward(own.get("admin_ward")) if district == "Rochdale" else str(own.get("admin_ward") or "")
    around = sorted({(canonical_ward(row.get("admin_ward")) or str(row.get("admin_ward") or "?"))
                     if str(row.get("admin_district") or "") == "Rochdale" else str(row.get("admin_district") or "?")
                     for row in nearby})
    return {"street": street, "postcode": str(own.get("postcode") or postcode), "district": district, "ward": ward,
            "nearby_wards": around, "postcodes_checked": len(nearby), "radius_m": STREET_CHECK_RADIUS_M,
            "single_ward": bool(ward) and district == "Rochdale" and around == [ward], "checked": today}


def run_streets(articles: list[Any], cache: dict[str, Any], fetch: FetchNearest = fetch_nearest, today: str | None = None) -> dict[str, Any]:
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    needed: dict[str, dict[str, str]] = {}
    for article in articles:
        if isinstance(article, dict):
            for item in story_streets(article):
                needed.setdefault(item["street"].casefold(), item)
    missing = [key for key in sorted(needed) if not isinstance(cache.get(key), dict)]
    report: dict[str, Any] = {"in_stories": len(needed), "looked_up": 0, "failed": "", "waiting": 0}
    for key in missing[:STREETS_PER_RUN]:
        item = needed[key]
        try:
            nearby = fetch(item["postcode"])
        except (urllib.error.URLError, OSError, ValueError) as error:
            report["failed"] = f"{type(error).__name__}: {error}"[:200]
            break
        cache[key] = street_entry(item["street"], item["postcode"], nearby, today)
        report["looked_up"] += 1
    report["waiting"] = sum(1 for key in needed if not isinstance(cache.get(key), dict))
    usable = [v for k, v in cache.items() if not k.startswith("_") and isinstance(v, dict)]
    report["single_ward"] = sum(1 for v in usable if v.get("single_ward") is True)
    report["boundary"] = sum(1 for v in usable if v.get("single_ward") is False and v.get("ward"))
    return report


def fetch_bulk(postcodes: list[str]) -> list[dict[str, Any]]:
    request = urllib.request.Request(
        API, method="POST", data=json.dumps({"postcodes": postcodes}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "User-Agent": "RochdaleDaily/1.0 (+https://rochdaledaily.co.uk; news@rochdaledaily.co.uk)"})
    with urllib.request.urlopen(request, timeout=12) as response:
        return (json.loads(response.read().decode("utf-8")) or {}).get("result") or []


def entry_for(result: dict[str, Any] | None, today: str) -> dict[str, Any]:
    if not result:
        return {"found": False, "checked": today}
    district = str(result.get("admin_district") or "")
    named = str(result.get("admin_ward") or "")
    entry = {"postcode": str(result.get("postcode") or ""), "district": district,
             "ward": canonical_ward(named) if district == "Rochdale" else named,
             "ward_code": str((result.get("codes") or {}).get("admin_ward") or ""), "checked": today}
    if district == "Rochdale" and not entry["ward"]:
        entry["ward"] = ""
        entry["unmatched_ward"] = named
    return entry


def wanted(articles: list[Any]) -> list[str]:
    found: set[str] = set()
    for article in articles:
        if isinstance(article, dict):
            found.update(story_postcodes(article))
    return sorted(found)


def run(articles: list[Any], cache: dict[str, Any], fetch: Fetch = fetch_bulk, today: str | None = None) -> dict[str, Any]:
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    needed = wanted(articles)
    missing = [pc for pc in needed if not isinstance(cache.get(pc), dict)]
    report: dict[str, Any] = {"in_stories": len(needed), "looked_up": 0, "failed": "", "unmatched": []}
    for start in range(0, len(missing), BATCH):
        batch = missing[start:start + BATCH]
        try:
            rows = fetch(batch)
        except (urllib.error.URLError, OSError, ValueError) as error:
            report["failed"] = f"{type(error).__name__}: {error}"[:200]
            break
        answered = {str(row.get("query") or "").replace(" ", "").upper(): row.get("result") for row in rows if isinstance(row, dict)}
        for postcode in batch:
            if postcode not in answered:
                continue  # no answer is not "does not exist": ask again next run
            cache[postcode] = entry_for(answered[postcode], today)
            report["looked_up"] += 1
    report["unmatched"] = sorted({str(v.get("unmatched_ward")) for v in cache.values() if isinstance(v, dict) and v.get("unmatched_ward")})
    report["rochdale"] = sum(1 for k, v in cache.items() if not k.startswith("_") and isinstance(v, dict) and v.get("district") == "Rochdale" and v.get("ward"))
    return report


def refresh(root: Path = ROOT, fetch: Fetch = fetch_bulk, fetch_streets: FetchNearest = fetch_nearest) -> dict[str, Any]:
    """Bring the evidence file up to date for the stories under root, and say
    what happened. Used by every lane through normalise_public_theme, just
    before ward tags are stamped."""
    try:
        articles = json.loads((root / "articles.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        articles = []
    if isinstance(articles, dict):
        articles = articles.get("articles") or []
    try:
        cache = json.loads(POSTCODE_EVIDENCE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    if not isinstance(cache, dict):
        cache = {}
    before = json.dumps(cache, sort_keys=True)
    report = run(articles, cache, fetch)
    cache["_docs"] = DOCS
    if json.dumps(cache, sort_keys=True) != before:
        ordered = {"_docs": cache["_docs"], **{k: cache[k] for k in sorted(cache) if k != "_docs"}}
        POSTCODE_EVIDENCE_PATH.write_text(json.dumps(ordered, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Ward postcode evidence: {report['in_stories']} postcodes in stories, {report['looked_up']} looked up this run, "
          f"{report['rochdale']} on file inside the borough.")
    if report["failed"]:
        print(f"::warning title=Ward postcodes::Lookup did not complete ({report['failed']}); those stories stay untagged until the next run.")
    if report["unmatched"]:
        print("::warning title=Ward postcodes::Rochdale wards this site does not list: " + ", ".join(report["unmatched"]))
    report["streets"] = refresh_streets(articles, fetch_streets)
    return report


def refresh_streets(articles: list[Any], fetch: FetchNearest = fetch_nearest) -> dict[str, Any]:
    try:
        cache = json.loads(STREET_EVIDENCE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    if not isinstance(cache, dict):
        cache = {}
    before = json.dumps(cache, sort_keys=True)
    report = run_streets(articles, cache, fetch)
    cache["_docs"] = STREET_DOCS
    if json.dumps(cache, sort_keys=True) != before:
        ordered = {"_docs": cache["_docs"], **{k: cache[k] for k in sorted(cache) if k != "_docs"}}
        STREET_EVIDENCE_PATH.write_text(json.dumps(ordered, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Ward street evidence: {report['in_stories']} short streets named in stories, {report['looked_up']} checked this run, "
          f"{report['single_ward']} on file in one ward, {report['boundary']} on a ward boundary, {report['waiting']} still to check.")
    if report["failed"]:
        print(f"::warning title=Ward streets::Check did not complete ({report['failed']}); those stories stay untagged until the next run.")
    return report


def main() -> int:
    refresh()
    return 0


if __name__ == "__main__":
    sys.exit(main())
