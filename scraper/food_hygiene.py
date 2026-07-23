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


# How many businesses to name in one roundup. Rochdale publishes a low rating
# every few months, so the standing list is short, but this bounds the article
# if a large batch of inspections is published at once.
ROUNDUP_MAX_LISTED = 30

_NUMBER_WORDS = {
    1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six",
    7: "Seven", 8: "Eight", 9: "Nine", 10: "Ten",
}

# The FSA's own category labels are database values, not English. "Retailers -
# other" cannot follow "a" in a sentence, so the ones that read badly are given
# a plain-English equivalent. Anything not listed is used as published.
_TYPE_PROSE = {
    "retailers - other": "retailer",
    "retailers - supermarkets/hypermarkets": "supermarket",
    "restaurant/cafe/canteen": "restaurant, cafe or canteen",
    "takeaway/sandwich shop": "takeaway or sandwich shop",
    "other catering premises": "catering business",
    "pub/bar/nightclub": "pub, bar or nightclub",
    "manufacturers/packers": "food manufacturer",
    "distributors/transporters": "food distributor",
    "hotel/bed & breakfast/guest house": "hotel or guest house",
    "school/college/university": "school, college or university",
    "hospitals/childcare/caring premises": "care or childcare premises",
    "mobile caterer": "mobile caterer",
    "farmers/growers": "farm or growing business",
    "importers/exporters": "food importer or exporter",
}


def _type_prose(raw: str) -> str:
    value = str(raw or "").strip().lower()
    return _TYPE_PROSE.get(value, value or "food business")


def _count_phrase(count: int, rating: int, meaning: str) -> str:
    word = _NUMBER_WORDS.get(count, str(count))
    verb = "is" if count == 1 else "are"
    return f"{word} {verb} rated {rating}, where {meaning}"


def fetch_current_low_ratings(
    get: Callable[..., Any],
    *,
    max_rating: int = 1,
    authority_id: int | None = None,
) -> list[dict[str, Any]]:
    """Every establishment in the borough currently holding a low rating.

    Unlike fetch_recent_low_ratings this applies no date cutoff. A rating stands
    until the business is re-inspected, so a 0 published last December is still
    that business's current rating today - which is the fact a reader wants and
    the reason the eight-day window produced almost nothing. Rochdale publishes
    a low rating every few months, not every week.

    Sorted worst first, then most recently inspected.
    """
    if authority_id is None:
        authority_id = find_authority_id(get)
    if authority_id is None:
        return []

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
            if rating_date is None:
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

    records.sort(key=lambda r: (r["rating"], -r["rating_date"].timestamp()))
    return records


def roundup_article_fields(
    records: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, str]:
    """One article listing the businesses currently holding a low rating.

    A single low rating is barely a story six times a year. The standing list
    is: it names businesses, gives their addresses and inspection dates, and
    can be republished each month from the same source.

    Every sentence restates a published FSA fact. The inspection findings
    themselves are not in the API - only the score - so nothing is said about
    what an inspector saw.
    """
    now = now or datetime.now(timezone.utc)
    as_at = now.strftime("%-d %B %Y")
    total = len(records)

    if not total:
        title = f"No Rochdale food business currently holds a hygiene rating below 2"
        summary = (
            "No food business in the Rochdale borough currently holds a food "
            f"hygiene rating of 0 or 1, according to Food Standards Agency "
            f"records checked on {as_at}."
        )
        body = (
            "No food business in the Rochdale borough is currently listed with "
            "a food hygiene rating of 0 or 1. "
            f"Food Standards Agency records were checked on {as_at}. "
            "Ratings range from 0, where urgent improvement is necessary, to 5, "
            "meaning hygiene standards are very good. "
            "Ratings change when a business is re-inspected, so this list is "
            "accurate only as at the date it was checked."
        )
        return {"title": title, "summary": summary, "body": body}

    zeros = sum(1 for r in records if r["rating"] == 0)
    ones = total - zeros
    listed = records[:ROUNDUP_MAX_LISTED]

    counts = []
    if zeros:
        counts.append(_count_phrase(zeros, 0, "urgent improvement is necessary"))
    if ones:
        counts.append(_count_phrase(ones, 1, "major improvement is necessary"))
    counts_sentence = "; ".join(
        phrase if index == 0 else phrase[0].lower() + phrase[1:]
        for index, phrase in enumerate(counts)
    ) + "."

    title = (
        f"{total} Rochdale food business{'es' if total != 1 else ''} "
        f"currently rated 0 or 1 for hygiene"
    )

    opener = _NUMBER_WORDS.get(total, str(total))
    plural = "es" if total != 1 else ""
    holds = "hold" if total != 1 else "holds"
    summary = (
        f"{opener} food business{plural} in the Rochdale "
        f"borough currently {holds} a food hygiene rating of 0 or 1, according to "
        f"Food Standards Agency records checked on {as_at}. "
        + counts_sentence
    )

    lines = []
    for record in listed:
        date_text = record["rating_date"].strftime("%-d %B %Y")
        business_type = _type_prose(record.get("business_type"))
        lines.append(
            f"{record['name']}, a {business_type} at {record['address']}, "
            f"was rated {record['rating']} following an inspection on {date_text}."
        )

    remainder = ""
    if total > len(listed):
        remainder = (
            f" A further {total - len(listed)} business"
            f"{'es' if total - len(listed) != 1 else ''} in the borough also "
            f"hold a rating of 0 or 1; the full list is on the Food Standards "
            f"Agency website."
        )

    body = (
        f"{opener} food business{plural} in the Rochdale "
        f"borough currently {holds} a food hygiene rating of 0 or 1. "
        f"Food Standards Agency records were checked on {as_at}. "
        + counts_sentence + " "
        + " ".join(lines)
        + remainder
        + " Under the national Food Hygiene Rating Scheme, ratings range from 0, "
        "where urgent improvement is necessary, to 5, meaning hygiene standards "
        "are very good. The rating reflects the standards found on the date of "
        "the inspection and does not reflect the quality of the food. "
        "Businesses have the right to appeal a rating, to publish a reply "
        "alongside it, and to request a re-inspection once improvements have "
        "been made, so a rating listed here may since have changed. "
        "Each business's current rating is on the Food Standards Agency website."
    )

    return {"title": title, "summary": summary, "body": body}


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
