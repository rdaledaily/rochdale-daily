#!/usr/bin/env python3
"""Tests for the inspection register watch.

Run: PYTHONPATH=scraper python scraper/test_register_watch.py

The line that must never move: providers Ofsted itself anonymises -- children's
homes and childminders published under a bare URN -- are never emitted, not as
a candidate, not as a lead, not even as the URN. Most of this file guards that
line. No network is touched.
"""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import register_watch as rw

FAILURES: list[str] = []
NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)


def check(condition: bool, label: str) -> None:
    if condition:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}")
        FAILURES.append(label)


def section(title: str) -> None:
    print(f"\n{title}")


def li(name_html: str, category: str, latest: str, urn: str, extra: str = "") -> str:
    return (
        f'<li class="search-result">'
        f'<a href="/provider/16/{urn}">{name_html}</a>'
        f"<p>Category: {category}</p>{extra}"
        f"<p>Latest report: {latest}</p><p>URN: {urn}</p></li>"
    )


LISTING = "<ol>" + "".join([
    li("Little Sparks Wardle", "Childcare on Non-Domestic Premises",
       "02 September 2026", "2579245",
       "<p>415 Birch Road, Wardle, ROCHDALE, OL12 9LH</p>"),
    li("Rochdale Training Association Limited", "Independent Learning Provider",
       "01 September 2026", "2579300",
       "<p>Fishwick Street, ROCHDALE, OL16 5NA</p>"),
    # Anonymised children's home: Ofsted withholds the name. Must vanish.
    li("SC456419", "Children's Home", "03 September 2026", "SC456419",
       "<p>We can't publish the name and address of this Children's Home</p>"),
    # Anonymised childminder, same rule.
    li("2591511", "Childminder", "03 September 2026", "2591511",
       "<p>We can't publish the name and address of this Childminder</p>"),
    # Stale: newest-first listing means parsing may stop here.
    li("Tiddlywinks Nursery School (Heywood) Ltd", "Childcare on Non-Domestic Premises",
       "04 August 2026", "2579999",
       "<p>Taylor Street, Heywood, Rochdale, OL10 1EF</p>"),
]) + "</ol>"


class FakeResponse:
    def __init__(self, status: int, text: str = "", payload=None) -> None:
        self.status_code = status
        self.text = text
        self._payload = payload

    def json(self):
        return self._payload


def fake_fetch_factory(routes):
    calls = []

    def fetch(url, **kwargs):
        calls.append(url)
        for fragment, reply in routes.items():
            if fragment in url:
                return reply
        return FakeResponse(404)

    fetch.calls = calls
    return fetch


# --------------------------------------------------------------------------
section("The safeguarding gate is absolute")
# --------------------------------------------------------------------------

entries = rw.parse_ofsted_listing(LISTING, NOW)
names = [e["name"] for e in entries]
check("Little Sparks Wardle" in names, "a named nursery report is kept")
check("Rochdale Training Association Limited" in names, "a named training provider is kept")
check(
    all("SC456419" not in str(e) for e in entries),
    "the anonymised children's home leaves no trace, URN included",
)
check(
    all("2591511" not in str(e) for e in entries),
    "the anonymised childminder leaves no trace, URN included",
)
check(len(entries) == 2, f"exactly the two named fresh reports survive (got {len(entries)})")

# --------------------------------------------------------------------------
section("Freshness and fields")
# --------------------------------------------------------------------------

check(all(e["report_date"] >= "2026-09-01" for e in entries), "stale reports are not entries")
sparks = next(e for e in entries if e["name"] == "Little Sparks Wardle")
check(sparks["town"] == "wardle", "town detected from the address")
check(sparks["url"].startswith("https://reports.ofsted.gov.uk/provider/"), "url points at the report page")
check(sparks["urn"] == "2579245", "URN captured for named providers")

# --------------------------------------------------------------------------
section("Candidates ground on the report page, not on this module")
# --------------------------------------------------------------------------

fetch = fake_fetch_factory({"reports.ofsted.gov.uk": FakeResponse(200, LISTING)})
records = rw.ofsted_candidates(fetch, now=NOW)
check(len(records) == 2, "two candidates emitted")
first = records[0]
check(first["source_name"] == "Ofsted", "attributed to Ofsted")
check(first["source_url"].startswith("https://reports.ofsted.gov.uk/provider/"),
      "source_url is the provider report page for the pipeline to fetch")
check(first["category"] == "education", "filed as education")
check("inspection report" in first["source_title"], "title states what happened, nothing more")
check(first["source_kind"] == "inspection_register", "kind marks the register route")

seen = {"2579245"}
again = rw.ofsted_candidates(fetch, now=NOW, seen_urns=seen)
check(len(again) == 1, "a URN already seen is not offered again")

failing = fake_fetch_factory({"reports.ofsted.gov.uk": FakeResponse(503)})
try:
    rw.ofsted_candidates(failing, now=NOW)
    check(False, "a failing register raises for the caller's warning path")
except RuntimeError:
    check(True, "a failing register raises for the caller's warning path")

# --------------------------------------------------------------------------
section("CQC stays dark without its key, works with it")
# --------------------------------------------------------------------------

rw.CQC_SUBSCRIPTION_KEY = ""
check(rw.cqc_candidates(fake_fetch_factory({}), now=NOW) == [], "no key -> no requests, no error")

rw.CQC_SUBSCRIPTION_KEY = "test-key"
cqc_routes = {
    "/changes/location": FakeResponse(200, payload={"changes": ["1-101", "1-202"]}),
    "/locations/1-101": FakeResponse(200, payload={
        "name": "Springhill Care Home",
        "localAuthority": "Rochdale",
        "postalAddressTownCity": "Rochdale",
        "currentRatings": {"overall": {"rating": "Requires improvement"}},
        "reports": [{"reportDate": NOW.strftime("%Y-%m-%d")}],
    }),
    "/locations/1-202": FakeResponse(200, payload={
        "name": "Elsewhere Lodge",
        "localAuthority": "Bury",
        "reports": [{"reportDate": NOW.strftime("%Y-%m-%d")}],
    }),
}
cqc_fetch = fake_fetch_factory(cqc_routes)
cqc_records = rw.cqc_candidates(cqc_fetch, now=NOW)
check(len(cqc_records) == 1, "only the Rochdale location becomes a candidate")
check(cqc_records and "Springhill Care Home" in cqc_records[0]["source_title"], "named in the title")
check(cqc_records and "Requires improvement" in cqc_records[0]["source_title"], "rating carried when present")
check(cqc_records and cqc_records[0]["category"] == "health", "filed as health")
check(
    all("Ocp-Apim-Subscription-Key" not in str(r) for r in cqc_records),
    "the key never leaks into a record",
)
rw.CQC_SUBSCRIPTION_KEY = ""

# --------------------------------------------------------------------------
section("State round-trips")
# --------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as tmp:
    state_path = Path(tmp) / "reports" / "register_state.json"
    rw.save_state(state_path, {"b", "a"})
    check(rw.load_state(state_path) == {"a", "b"}, "seen set survives a round trip")
    check(rw.load_state(Path(tmp) / "missing.json") == set(), "missing state is an empty set")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED:")
    for name in FAILURES:
        print(f"  - {name}")
    raise SystemExit(1)
print("all register watch tests passed")
