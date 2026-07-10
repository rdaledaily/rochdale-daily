"""Tests for the FSA food hygiene collector. No network access: the API is
replaced with a fixture that mimics api.ratings.food.gov.uk responses."""

from datetime import datetime, timedelta, timezone

from food_hygiene import (
    fetch_recent_low_ratings,
    find_authority_id,
    rating_article_fields,
)

NOW = datetime.now(timezone.utc)


def iso(days_ago: int) -> str:
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT00:00:00")


AUTHORITIES_PAYLOAD = {
    "authorities": [
        {"Name": "Rochford", "LocalAuthorityId": 999},
        {"Name": "Rochdale", "LocalAuthorityId": 424},
    ]
}

ESTABLISHMENTS_PAYLOAD = {
    "establishments": [
        {   # New 1-rating inside the window -> story.
            "FHRSID": 111, "BusinessName": "Spice Corner",
            "BusinessType": "Takeaway/sandwich shop",
            "AddressLine1": "12 Yorkshire Street", "AddressLine2": "Rochdale",
            "PostCode": "OL16 1JU",
            "RatingValue": "1", "RatingDate": iso(3),
        },
        {   # New 5-rating -> above threshold, no story.
            "FHRSID": 222, "BusinessName": "The Baum",
            "BusinessType": "Pub/bar/nightclub",
            "AddressLine1": "33 Toad Lane", "AddressLine2": "Rochdale",
            "PostCode": "OL12 0NU",
            "RatingValue": "5", "RatingDate": iso(2),
        },
        {   # Old 0-rating outside the window -> no story.
            "FHRSID": 333, "BusinessName": "Stale Example",
            "BusinessType": "Restaurant/Cafe/Canteen",
            "AddressLine1": "1 Old Road", "PostCode": "OL11 1AA",
            "RatingValue": "0", "RatingDate": iso(60),
        },
        {   # Awaiting inspection -> never a story.
            "FHRSID": 444, "BusinessName": "Brand New Cafe",
            "BusinessType": "Restaurant/Cafe/Canteen",
            "AddressLine1": "2 New Road", "PostCode": "OL11 2BB",
            "RatingValue": "AwaitingInspection", "RatingDate": iso(1),
        },
        {   # New 0-rating inside the window -> story, sorted first.
            "FHRSID": 555, "BusinessName": "Corner Grill",
            "BusinessType": "Takeaway/sandwich shop",
            "AddressLine1": "8 Whitworth Road", "AddressLine2": "Rochdale",
            "PostCode": "OL12 0JG",
            "RatingValue": "0", "RatingDate": iso(5),
        },
    ]
}


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def fake_get(url, params=None, headers=None, timeout=None):
    assert headers and headers.get("x-api-version") == "2", (
        "the FSA API requires the x-api-version: 2 header on every request"
    )
    if url.endswith("/Authorities/basic"):
        return FakeResponse(AUTHORITIES_PAYLOAD)
    if url.endswith("/Establishments"):
        assert params["localAuthorityId"] == 424, params
        return FakeResponse(ESTABLISHMENTS_PAYLOAD)
    raise AssertionError(f"unexpected URL {url}")


# Authority lookup matches the exact name, not the Rochford prefix-cousin.
assert find_authority_id(fake_get) == 424

records = fetch_recent_low_ratings(fake_get, days=8, max_rating=2)
assert [r["fhrs_id"] for r in records] == [555, 111], records
assert records[0]["rating"] == 0 and records[1]["rating"] == 1
assert records[0]["url"] == "https://ratings.food.gov.uk/business/555"
assert "Whitworth Road, Rochdale, OL12 0JG" in records[0]["address"]

fields = rating_article_fields(records[1])
assert fields["title"] == "Spice Corner given 1 out of 5 food hygiene rating"
assert "major improvement necessary" in fields["body"]
assert "right to appeal" in fields["body"]
assert "12 Yorkshire Street, Rochdale, OL16 1JU" in fields["summary"]
# Nothing in the prose invents inspection findings.
for banned in ("dirty", "filthy", "unsafe", "pest", "mice", "shocking"):
    assert banned not in fields["body"].lower()

print("Food hygiene collector tests passed.")
