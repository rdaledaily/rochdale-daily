"""Food Standards Agency hygiene-rating collector for Rochdale Daily.

Primary-data journalism: new low food hygiene ratings in the borough, read
directly from the FSA's official open API (api.ratings.food.gov.uk), which is
published for reuse. No scraping, no robots questions, no rewriting of other
outlets' work.

Editorial rules encoded here:
  * Only ratings at or below FOOD_HYGIENE_MAX_RATING (default 2) become
    stories. A 0, 1 or 2 rating is genuinely newsworthy; publishing every
    routine 4 and 5 would flood the feed.
  * Only ratings issued within the lookback window (default 8 days, so
    consecutive runs overlap rather than gap).
  * The prose states only what the FSA publishes: the overall rating, the
    inspection date, the business name and address, and the FHRS link. The
    component sub-scores are deliberately NOT interpreted in prose - they are
    demerit-style numbers that are easy to misstate.
  * Every article carries the scheme's fairness sentence: businesses can
    appeal, reply, and request a re-inspection. That sentence is a fact about
    the FHRS scheme, stated in every piece.

This module has no third-party dependencies. Network access is injected as a
callable so the tests never touch the internet.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

API_BASE = "https://api.ratings.food.gov.uk"
API_HEADERS = {"x-api-version": "2", "accept": "application/json"}
AUTHORITY_NAME = "Rochdale"
PAGE_SIZE = 500
MAX_PAGES = 20

RATING_DESCRIPTIONS = {
    0: "urgent improvement necessary",
    1: "major improvement necessary",
    2: "improvement necessary",
    3: "generally satisfactory",
    4: "good",
    5: "very good",
}


def _get_json(get: Callable[..., Any], url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = get(url, params=params or {}, headers=API_HEADERS, timeout=20)
    response.raise_for_status()
    return response.json()


def find_authority_id(get: Callable[..., Any], name: str = AUTHORITY_NAME) -> int | None:
    """Look up the FSA authority id for the borough by name at run time.

    Looked up rather than hard-coded so an upstream renumbering can never
    silently attach another authority's businesses to Rochdale stories.
    """
    payload = _get_json(get, f"{API_BASE}/Authorities/basic")
    wanted = name.strip().lower()
    for authority in payload.get("authorities", []):
        if str(authority.get("Name", "")).strip().lower() == wanted:
            return int(authority["LocalAuthorityId"])
    return None


def _parse_rating_date(raw: Any) -> datetime | None:
    try:
        value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _address(establishment: dict[str, Any]) -> str:
    parts = [
        _clean(establishment.get(f"AddressLine{index}"))
        for index in range(1, 5)
    ]
    parts.append(_clean(establishment.get("PostCode")))
    return ", ".join(part for part in parts if part)


def fetch_recent_low_ratings(
    get: Callable[..., Any],
    *,
    days: int = 8,
    max_rating: int = 2,
    authority_id: int | None = None,
) -> list[dict[str, Any]]:
    """Return normalised records for recent low ratings in the borough.

    Non-numeric rating values ("AwaitingInspection", "Exempt",
    "AwaitingPublication") are never stories and are skipped.
    """
    if authority_id is None:
        authority_id = find_authority_id(get)
    if authority_id is None:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    records: list[dict[str, Any]] = []

    for page in range(1, MAX_PAGES + 1):
        payload = _get_json(
            get,
            f"{API_BASE}/Establishments",
            {
                "localAuthorityId": authority_id,
                "pageNumber": page,
                "pageSize": PAGE_SIZE,
            },
        )
        establishments = payload.get("establishments", [])
        for establishment in establishments:
            raw_rating = _clean(establishment.get("RatingValue"))
            if not raw_rating.isdigit():
                continue
            rating = int(raw_rating)
            if rating > max_rating:
                continue
            rating_date = _parse_rating_date(establishment.get("RatingDate"))
            if rating_date is None or rating_date < cutoff:
                continue
            fhrs_id = establishment.get("FHRSID")
            if not fhrs_id:
                continue
            records.append({
                "fhrs_id": int(fhrs_id),
                "name": _clean(establishment.get("BusinessName")),
                "business_type": _clean(establishment.get("BusinessType")),
                "address": _address(establishment),
                "rating": rating,
                "rating_date": rating_date,
                "url": f"https://ratings.food.gov.uk/business/{int(fhrs_id)}",
            })
        if len(establishments) < PAGE_SIZE:
            break

    records.sort(key=lambda record: (record["rating"], record["rating_date"]))
    return records


def rating_article_fields(record: dict[str, Any]) -> dict[str, str]:
    """Deterministic title, summary and body for one low-rating record.

    Every sentence is a restatement of published FSA facts. No adjectives, no
    speculation about causes, no description of conditions - the inspection
    findings themselves are not in the API and must never be invented.
    """
    name = record["name"]
    rating = int(record["rating"])
    date_text = record["rating_date"].strftime("%-d %B %Y")
    meaning = RATING_DESCRIPTIONS.get(rating, "")
    business_type = record.get("business_type") or "food business"

    title = f"{name} given {rating} out of 5 food hygiene rating"

    summary = (
        f"{name}, a {business_type.lower()} at {record['address']}, received "
        f"a food hygiene rating of {rating} out of 5 following a Food "
        f"Standards Agency inspection on {date_text}."
    )

    body = (
        f"{name} has been given a food hygiene rating of {rating} out of 5. "
        f"The rating was published by the Food Standards Agency after an "
        f"inspection on {date_text}. "
        f"The business is listed as a {business_type.lower()} at "
        f"{record['address']}. "
        f"Under the national Food Hygiene Rating Scheme, a rating of "
        f"{rating} means {meaning}. Ratings range from 0, where urgent "
        f"improvement is necessary, to 5, meaning hygiene standards are "
        f"very good. "
        f"Businesses have the right to appeal a rating, to publish a "
        f"reply alongside it, and to request a re-inspection once "
        f"improvements have been made, so the published rating may change. "
        f"The full listing is available on the Food Standards Agency "
        f"website."
    )

    return {"title": title, "summary": summary, "body": body}
