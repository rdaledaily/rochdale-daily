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


# --- One story per NEW low rating (12 Nov 2026) ---

from food_hygiene import (
    empty_state,
    plan_single_ratings,
    postcode_area,
    rating_key,
    rating_source_url,
    single_rating_story,
)
from story_identity import _records_match, keyed_record_identity, same_story
from frontpage_pipeline import records_match

SR_NOW = datetime(2026, 11, 12, 21, 0, tzinfo=timezone.utc)


def sr_rec(fhrs, name, address, rating=1, inspected=datetime(2026, 10, 1, tzinfo=timezone.utc)):
    return {"fhrs_id": fhrs, "name": name, "business_type": "Takeaway/sandwich shop",
            "address": address, "rating": rating, "rating_date": inspected}


OLD = sr_rec(1, "Old Grill", "1 Drake Street, Rochdale, OL16 1RE", inspected=datetime(2026, 6, 1, tzinfo=timezone.utc))
SPICE = sr_rec(2, "Spice Corner", "12 Yorkshire Street, Rochdale, OL16 1JU")
WOK = sr_rec(3, "Golden Wok", "4 Market Place, Heywood, OL10 1LL", rating=0)


def baselined(records):
    state = empty_state()
    offer, report = plan_single_ratings(records, state, set(), SR_NOW - timedelta(days=1))
    assert offer == [] and report["status"] == "baseline taken"
    return state


def test_first_run_takes_baseline_and_publishes_nothing():
    state = empty_state()
    offer, report = plan_single_ratings([OLD, SPICE], state, set(), SR_NOW)
    assert offer == []
    assert report["baseline_size"] == 2
    assert set(state["baseline"]) == {rating_key(OLD), rating_key(SPICE)}


def test_new_rating_is_offered_even_though_inspection_is_weeks_old():
    # The bug: SPICE was inspected 6 weeks before SR_NOW. An inspection-date
    # window would never see it; the baseline diff does.
    state = baselined([OLD])
    offer, report = plan_single_ratings([OLD, SPICE], state, set(), SR_NOW)
    assert [r["name"] for r in offer] == ["Spice Corner"]
    assert report["new"] == 1


def test_offered_but_unpublished_is_offered_again():
    # The selection cap can drop a candidate: offering is not publishing.
    state = baselined([OLD])
    plan_single_ratings([OLD, SPICE], state, set(), SR_NOW)
    offer, _ = plan_single_ratings([OLD, SPICE], state, set(), SR_NOW + timedelta(hours=1))
    assert [r["name"] for r in offer] == ["Spice Corner"]


def test_published_rating_is_never_offered_again():
    state = baselined([OLD])
    plan_single_ratings([OLD, SPICE], state, set(), SR_NOW)
    published = {rating_source_url(SPICE)}
    offer, report = plan_single_ratings([OLD, SPICE], state, published, SR_NOW + timedelta(hours=1))
    assert offer == [] and report["newly_published"] == 1
    offer, _ = plan_single_ratings([OLD, SPICE], state, set(), SR_NOW + timedelta(days=30))
    assert offer == []  # remembered in state, even after it leaves articles.json


def test_unpublished_rating_expires_after_14_days_and_is_named():
    state = baselined([OLD])
    plan_single_ratings([OLD, SPICE], state, set(), SR_NOW)
    offer, report = plan_single_ratings([OLD, SPICE], state, set(), SR_NOW + timedelta(days=15))
    assert offer == []
    assert report["newly_expired"] and "Spice Corner" in report["newly_expired"][0]


def test_rerated_before_publication_is_withdrawn():
    state = baselined([OLD])
    plan_single_ratings([OLD, SPICE], state, set(), SR_NOW)
    offer, _ = plan_single_ratings([OLD], state, set(), SR_NOW + timedelta(hours=1))
    assert offer == [] and state["pending"] == {}


def test_new_low_rating_for_a_baselined_business_is_a_new_story():
    state = baselined([SPICE])
    worse = sr_rec(2, "Spice Corner", SPICE["address"], rating=0, inspected=datetime(2026, 11, 1, tzinfo=timezone.utc))
    offer, _ = plan_single_ratings([worse], state, set(), SR_NOW)
    assert offer and offer[0]["rating"] == 0


def test_no_data_run_changes_nothing():
    state = baselined([OLD])
    before = repr(state)
    offer, report = plan_single_ratings([], state, set(), SR_NOW)
    assert offer == [] and report["status"] == "no data this run" and repr(state) == before


def test_story_states_only_published_facts_and_ends_on_right_of_reply():
    story = single_rating_story(SPICE, borough_low_count=66, checked_at=SR_NOW)
    text = " ".join(story["paragraphs"])
    assert story["title"] == "Spice Corner rated 1 out of 5 for food hygiene"
    assert "1 October 2026" in text and "12 November 2026" in text  # UK dates
    assert "major improvement is necessary" in text
    assert "66 food businesses" in text
    assert "https://ratings.food.gov.uk/business/2" in text
    assert story["paragraphs"][-1].startswith("Right of reply:")
    for banned in ("dirty", "filthy", "shocking", "inspectors found", "we wish"):
        assert banned not in text.lower()


def sr_article(record):
    story = single_rating_story(record, borough_low_count=66, checked_at=SR_NOW)
    return {"title": story["title"], "excerpt": story["excerpt"],
            "content_html": " ".join(story["paragraphs"]), "source_url": rating_source_url(record),
            "category": "health", "area": "rochdale", "published_at": "2026-11-12T21:00:00Z",
            "source_kind": "food_hygiene_rating"}


def test_two_businesses_are_never_one_story():
    # Measured before the fix: same_story(Spice Corner, Golden Wok) was True.
    a, b = sr_article(SPICE), sr_article(WOK)
    assert keyed_record_identity(a) and keyed_record_identity(b)
    assert not same_story(a, b)
    assert not _records_match(a, b)
    assert not records_match(a, b)


def test_same_rating_record_is_one_story():
    assert same_story(sr_article(SPICE), sr_article(SPICE))


def test_ordinary_stories_are_unaffected():
    plain = {"title": "Bus lane cameras switched on", "source_url": "https://example.org/x"}
    assert keyed_record_identity(plain) == ""


def test_postcode_area():
    assert postcode_area("4 Market Place, OL10 1LL") == "heywood"
    assert postcode_area("Unit 3, M24 4EL") == "middleton"
    assert postcode_area("Todmorden Road, OL15 9EG") == "littleborough"
    assert postcode_area("12 Yorkshire Street, OL16 1JU") == ""


if __name__ == "__main__":
    # CI runs this file as a script (`python scraper/test_food_hygiene.py`).
    # Without this block none of the tests above executed there.
    import sys
    tests = [(name, fn) for name, fn in sorted(globals().items()) if name.startswith("test_") and callable(fn)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
        except Exception as exc:  # report every failure, then exit non-zero
            failed += 1
            print(f"FAIL {name}: {exc!r}")
    print(f"{len(tests) - failed}/{len(tests)} food hygiene tests passed")
    sys.exit(1 if failed else 0)
