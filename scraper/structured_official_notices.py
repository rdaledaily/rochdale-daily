"""Deterministic council-roadworks source review.

Only accepts the labelled council directory record for a single road notice.
Unlike an LLM summary, all text and its citation are built directly from
explicit, captured fields. This is deliberately NOT a generic news verifier.
"""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape
import re
from urllib.parse import urlparse

from claim_evidence import is_primary, evidence_issues

AREA = ("Rochdale", "Middleton", "Heywood", "Littleborough", "Milnrow", "Newhey")
STREET = re.compile(
    r"^(?P<road>[A-Za-z0-9'’ \-]{4,90}\b(?:Road|Drive|Street|Lane|Avenue|Way|Close|Crescent|Place|Fold|Terrace)),\s*"
    r"(?P<kind>roadworks|temporary prohibition of waiting)\b", re.I,
)
HEAD = re.compile(
    r"^(.*?)\s+\|\s+Rochdale Borough Council\b", re.I | re.S
)
FIELDS = (
    "Area", "Expected start and finish", "Reason", "Restriction and location",
    "Alternative route", "Organised by", "Directions", "Get directions",
    "View roadworks on a map", "Was this page helpful?",
)


def extract_field(text: str, field: str) -> str:
    labels = [re.escape(x) for x in FIELDS if x != field]
    expression = r"\b" + re.escape(field) + r"\s+(.+?)(?=\s+(?:" + "|".join(labels) + r")\b|$)"
    match = re.search(expression, text, re.I | re.S)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()


def verified_notice(article: dict) -> bool:
    """Modify article only when *every* required council record check succeeds.

    Returns False and leaves the draft untouched for regular, stricter review
    if the record is incomplete, ambiguous, stale or not on a trusted council
    directory URL. There are no model-produced facts in this route.
    """
    url = str(article.get("source_url") or "")
    parsed = urlparse(url)
    if not (is_primary(url) and parsed.hostname in ("www.rochdale.gov.uk", "rochdale.gov.uk")
            and parsed.path.startswith("/directory-record/")
            and str(article.get("source_kind") or "").lower() == "primary_data"
            and str(article.get("category") or "").lower() in ("traffic", "transport")):
        return False
    sources = article.get("evidence_sources") or []
    if len(sources) != 1 or sources[0].get("url") != url:
        return False
    captured = re.sub(r"\s+", " ", str(sources[0].get("captured_text") or "")).strip()
    match = HEAD.search(captured)
    if not match:
        return False
    title = match.group(1).strip()
    kind = STREET.match(title)
    if not kind:
        return False
    road_name = kind.group("road")
    area = extract_field(captured, "Area")
    # The labelled Area and the title describe the *same* road restriction.
    # Reject an official record whose title says Middleton but Area says
    # Rochdale (or whose location is missing/ambiguous), rather than issuing
    # a contradiction under an incorrectly certified primary-source banner.
    title_areas = {
        match.casefold()
        for match in re.findall(
            r"\bin\s+(Rochdale|Middleton|Heywood|Littleborough|Milnrow|Newhey)\b",
            title, flags=re.I,
        )
    }
    if len(title_areas) != 1 or area.casefold() not in title_areas:
        return False
    timing = extract_field(captured, "Expected start and finish")
    reason = extract_field(captured, "Reason")
    restriction = extract_field(captured, "Restriction and location")
    alternative = extract_field(captured, "Alternative route")
    organiser = extract_field(captured, "Organised by")
    if (
        area not in AREA or not timing or not reason or not restriction
        or organiser != "Rochdale Borough Council"
        or len(timing) > 200 or len(reason) > 280
        or not 25 <= len(restriction) <= 500
        or len(alternative) > 220
        or road_name.lower() not in title.lower()
        or road_name.lower() not in restriction.lower()
        or not re.search(r"\b20\d\d\b", timing)
    ):
        return False

    # Use only the council's actual field values. No invented purpose,
    # diversions, penalties, promises, times or neighbouring roadworks.
    safe = lambda s: escape(s, quote=True)
    p1 = (
        f"Rochdale Borough Council has published a traffic notice for "
        f"<strong>{safe(road_name)}</strong> in {safe(area)}. "
        f"The council lists the expected start and finish as "
        f"<strong>{safe(timing)}</strong>."
    )
    p2 = (
        f"The council gives the reason as {safe(reason)} "
        f"The notice describes the affected area as follows: {safe(restriction)}"
    )
    p3 = (
        f"The published alternative route is {safe(alternative)} "
        if alternative else
        "The council notice does not list a separate alternative route. "
    )
    p3 += (
        "These are the details in the council's current published record, "
        "rather than confirmation that work has started or finished. "
        f"Readers travelling through the area can check the "
        f'<a href="{safe(url)}" rel="noopener noreferrer">original Rochdale '
        "Borough Council notice</a> for any subsequent amendments."
    )
    headline = title[0].upper() + title[1:]
    claims = []
    for label, value in (
        ("Council roadworks notice", title),
        ("Scheduled restriction timing", timing),
        ("Reason for works", "Reason " + reason),
        ("Restriction location", restriction),
        ("Council alternative route", alternative),
    ):
        if not value:
            continue
        # Verbatim anchored extracts are all present in the captured official text.
        if len(value) < 25 or value.casefold() not in captured.casefold():
            return False
        claims.append({
            "claim": label + ": " + value[:220],
            "source_url": url,
            "supporting_excerpt": value,
        })
    if len(claims) < 4:
        return False

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    revised = dict(article)
    revised.update({
        "title": headline,
        "excerpt": (
            f"Rochdale Borough Council lists work affecting {road_name} in {area}; "
            f"expected timings: {timing}."
        ),
        "content_html": "\n".join(f"<p>{p}</p>" for p in (p1, p2, p3)),
        "source_names": ["Rochdale Borough Council"],
        "source_urls": [url],
        "source_count": 1,
        "verified_claims": claims,
        "source_review_verified": True,
        "primary_source_verified": True,
        "verification_method": "structured-official-directory-record",
        "verification_source_type": "primary",
        "verification_reasons": [],
        "publication_route": "official-record-grounded-rewrite",
        # The initial draft's source timestamp is not when we first publish.
        "first_published_at": now,
        "published_at": now,
        "last_updated_at": now,
    })
    if evidence_issues(revised):
        return False
    article.update(revised)
    return True
