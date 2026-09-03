#!/usr/bin/env python3
"""Inspection registers as primary-source news: Ofsted now, CQC when keyed.

Why registers
-------------
A register covers every provider in the borough at once, as facts reported to
the state rather than marketing. Ofsted alone lists 441 Rochdale providers, and
when this module was written its date-sorted listing carried reports published
THAT DAY. No other outlet reads these systematically; this is coverage the
paper can own.

Ofsted
------
reports.ofsted.gov.uk is fully crawlable (robots.txt disallows nothing but its
subscribe endpoints, verified 3 September 2026) and its search supports a
local-authority filter -- Rochdale is code 354 -- sorted newest report first.
Each fresh report becomes ONE candidate whose source_url is the provider's
report page; the pipeline fetches that page itself and grounds the rewrite on
it, exactly as it does for any other source. Nothing is invented here: this
module only notices that a report exists.

The safeguarding rule, which is absolute: Ofsted itself withholds the names and
addresses of children's homes and childminders ("We can't publish the name and
address..."), publishing them only under a bare URN. Anything Ofsted has
anonymised is skipped entirely -- never a candidate, never a lead, not even
with the URN. If the regulator won't name them, neither will the paper.

CQC
---
The Care Quality Commission syndication API covers every care home, GP surgery
and clinic in the borough, but its gateway now requires a (free) subscription
key and answers nothing without one -- verified 3 September 2026. The collector
therefore activates only when CQC_SUBSCRIPTION_KEY is set, using the changes
feed to spot locations with fresh activity and their detail records for the
rating. Until the key exists it stays quietly dark.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from html import unescape
from typing import Any, Callable

OFSTED_BASE = "https://reports.ofsted.gov.uk"
OFSTED_LA_CODE = os.getenv("OFSTED_LOCAL_AUTHORITY", "354")  # Rochdale
OFSTED_SEARCH = (
    f"{OFSTED_BASE}/search?local_authority%5B0%5D={OFSTED_LA_CODE}"
    "&status%5B0%5D=1&rows=40&sort=date&order=desc&start=0"
)

CQC_BASE = "https://api.service.cqc.org.uk/public/v1"
CQC_SUBSCRIPTION_KEY = os.getenv("CQC_SUBSCRIPTION_KEY", "").strip()

# Only a report newer than this is news; the register keeps decades.
REGISTER_FRESH_DAYS = int(os.getenv("REGISTER_FRESH_DAYS", "10"))

# Ordered most-specific first, "rochdale" deliberately LAST: nearly every
# address in the borough ends ", ROCHDALE" as the postal town, so checking
# rochdale first would file a Wardle nursery under rochdale every time.
BOROUGH_TOWNS = (
    "littleborough", "smallbridge", "castleton", "middleton", "firgrove",
    "heywood", "milnrow", "newhey", "wardle", "norden", "bamford",
    "rochdale",
)

_ANONYMISED_RE = re.compile(
    r"we can'?t publish the name", re.I
)
_URN_ONLY_NAME_RE = re.compile(r"^(?:SC|EY|RP)?\d{5,8}$")

_RESULT_LI_RE = re.compile(
    r"<li[^>]*>(?P<body>.*?<a[^>]+href=\"(?P<href>/provider/[^\"]+)\".*?)</li>",
    re.I | re.S,
)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_CATEGORY_RE = re.compile(r"Category:\s*(?P<cat>[^<]{3,60}?)(?:Latest|URN|Address|<)", re.I)
_LATEST_RE = re.compile(r"Latest report:\s*(?P<date>\d{1,2}\s+\w+\s+\d{4})", re.I)
_URN_RE = re.compile(r"URN:\s*(?P<urn>[A-Z]{0,2}\d{5,8})", re.I)
_NAME_RE = re.compile(r"<a[^>]+href=\"/provider/[^\"]+\"[^>]*>(?P<name>.*?)</a>", re.I | re.S)


def _plain(value: str) -> str:
    return _WS_RE.sub(" ", unescape(_TAG_RE.sub(" ", str(value or "")))).strip()


def _parse_report_date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value.strip(), "%d %B %Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def ofsted_category_to_paper(category: str) -> str:
    lowered = category.lower()
    if any(word in lowered for word in ("childcare", "childminder", "nursery")):
        return "education"
    if any(word in lowered for word in ("school", "college", "learning", "academy", "sixth")):
        return "education"
    return "education"


def detect_town(text: str) -> str:
    lowered = str(text or "").lower()
    for town in BOROUGH_TOWNS:
        if town in lowered:
            return town
    return "rochdale"


def parse_ofsted_listing(html: str, now: datetime) -> list[dict[str, Any]]:
    """Fresh, NAMED reports from the date-sorted Rochdale listing.

    Anything Ofsted has anonymised is dropped before it becomes data. The
    listing is newest-first, so parsing stops at the first stale entry.
    """
    fresh_cutoff = now - timedelta(days=REGISTER_FRESH_DAYS)
    entries: list[dict[str, Any]] = []
    for match in _RESULT_LI_RE.finditer(html or ""):
        body = match.group("body")
        text = _plain(body)
        if not _LATEST_RE.search(text):
            continue  # navigation furniture, not a result row
        date_match = _LATEST_RE.search(text)
        published = _parse_report_date(date_match.group("date")) if date_match else None
        if published is None:
            continue
        if published < fresh_cutoff:
            break  # newest-first: everything after this is older still

        # The safeguarding gate, before anything else is kept.
        name_match = _NAME_RE.search(body)
        name = _plain(name_match.group("name")) if name_match else ""
        if _ANONYMISED_RE.search(text) or not name or _URN_ONLY_NAME_RE.match(name):
            continue

        category_match = _CATEGORY_RE.search(text)
        urn_match = _URN_RE.search(text)
        entries.append({
            "name": name,
            "urn": urn_match.group("urn") if urn_match else "",
            "category": _plain(category_match.group("cat")) if category_match else "",
            "report_date": published.strftime("%Y-%m-%d"),
            "url": OFSTED_BASE + match.group("href"),
            "town": detect_town(text),
        })
    return entries


def ofsted_candidates(
    fetch: Callable[..., Any],
    now: datetime | None = None,
    seen_urns: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Candidate records for fresh named Ofsted reports in the borough.

    Returned as plain dicts so this module stays importable without the
    pipeline; scraper.py lifts them into Candidate objects. source_url is the
    provider's report page -- the pipeline fetches and grounds on it, so the
    story is written from the report itself, not from this listing.
    """
    now = now or datetime.now(timezone.utc)
    seen = seen_urns or set()
    response = fetch(OFSTED_SEARCH, timeout=20)
    status = int(getattr(response, "status_code", 0) or 0)
    if status != 200:
        raise RuntimeError(f"Ofsted search returned {status}")
    records = []
    for entry in parse_ofsted_listing(response.text or "", now):
        if entry["urn"] and entry["urn"] in seen:
            continue
        provider_kind = entry["category"] or "provider"
        records.append({
            "source_name": "Ofsted",
            "source_url": entry["url"],
            "source_title": (
                f"Ofsted publishes inspection report for {entry['name']}"
            )[:160],
            "source_summary": (
                f"Ofsted has published a new inspection report for {entry['name']} "
                f"({provider_kind}, {entry['town'].title()}), dated {entry['report_date']}. "
                "The report sets out the inspection's findings and any rating awarded."
            )[:400],
            "source_published_at": entry["report_date"] + "T09:00:00Z",
            "area": entry["town"],
            "category": "education",
            "source_kind": "inspection_register",
            "register_urn": entry["urn"],
        })
    return records


# ---------------------------------------------------------------------------
# CQC -- active only when the free subscription key exists.
# ---------------------------------------------------------------------------


def cqc_headers() -> dict[str, str]:
    return {"Ocp-Apim-Subscription-Key": CQC_SUBSCRIPTION_KEY}


def cqc_candidates(
    fetch: Callable[..., Any],
    now: datetime | None = None,
    seen_reports: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Fresh CQC inspection reports for borough locations. Needs the key."""
    if not CQC_SUBSCRIPTION_KEY:
        return []
    now = now or datetime.now(timezone.utc)
    seen = seen_reports or set()
    start = (now - timedelta(days=REGISTER_FRESH_DAYS)).strftime("%Y-%m-%dT00:00:00Z")
    end = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    response = fetch(
        f"{CQC_BASE}/changes/location?startTimestamp={start}&endTimestamp={end}",
        headers=cqc_headers(),
        timeout=20,
    )
    if int(getattr(response, "status_code", 0) or 0) != 200:
        raise RuntimeError(f"CQC changes returned {getattr(response, 'status_code', '?')}")
    changed = (response.json() or {}).get("changes", []) or []

    records: list[dict[str, Any]] = []
    for location_id in changed[:200]:
        detail_response = fetch(
            f"{CQC_BASE}/locations/{location_id}", headers=cqc_headers(), timeout=20
        )
        if int(getattr(detail_response, "status_code", 0) or 0) != 200:
            continue
        detail = detail_response.json() or {}
        if str(detail.get("localAuthority") or "").strip().lower() != "rochdale":
            continue
        name = str(detail.get("name") or "").strip()
        if not name:
            continue
        reports = detail.get("reports") or []
        newest = ""
        for report in reports:
            date = str(report.get("firstVisitDate") or report.get("reportDate") or "")
            newest = max(newest, date)
        if not newest or newest < (now - timedelta(days=REGISTER_FRESH_DAYS)).strftime("%Y-%m-%d"):
            continue
        key = f"{location_id}:{newest}"
        if key in seen:
            continue
        rating = str(((detail.get("currentRatings") or {}).get("overall") or {}).get("rating") or "")
        town = detect_town(f"{detail.get('postalAddressTownCity', '')} {name}")
        summary = (
            f"The Care Quality Commission has published a new inspection report for "
            f"{name}, {str(detail.get('postalAddressTownCity') or 'Rochdale')}"
            + (f", rated {rating}" if rating else "")
            + f", dated {newest}."
        )
        records.append({
            "source_name": "Care Quality Commission",
            "source_url": f"https://www.cqc.org.uk/location/{location_id}",
            "source_title": (
                f"CQC publishes inspection report for {name}"
                + (f" — rated {rating}" if rating else "")
            )[:160],
            "source_summary": summary[:400],
            "source_published_at": newest + "T09:00:00Z",
            "area": town,
            "category": "health",
            "source_kind": "inspection_register",
            "register_urn": key,
        })
    return records


# ---------------------------------------------------------------------------
# Shared state, so a report is offered once, not on every run forever.
# ---------------------------------------------------------------------------


def load_state(path) -> set[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return set(data.get("seen", []))
    except Exception:
        return set()


def save_state(path, seen: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"seen": sorted(seen)[-2000:]}
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)
