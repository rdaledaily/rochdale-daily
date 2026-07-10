from selection_policy import (
    ROCHDALE_WARDS,
    balanced_select,
    is_job_or_career_post,
    ward_for_item,
)

assert is_job_or_career_post(
    "Council careers: apply now for three full-time vacancies"
)
assert is_job_or_career_post(
    {"title": "Join our team", "source_url": "https://example.org/careers"}
)
assert is_job_or_career_post(
    "New apprenticeship opportunities are now open"
)
assert not is_job_or_career_post(
    "Factory closure could put 100 existing jobs at risk"
)
assert not is_job_or_career_post(
    "Council approves investment in a new business park"
)

assert ward_for_item({
    "title": "Residents in East Middleton invited to meeting",
    "area": "middleton",
}) == "East Middleton"
assert ward_for_item({
    "title": "Kirkholt road closure announced",
    "area": "kirkholt",
}) == "Balderstone and Kirkholt"
assert ward_for_item({
    "title": "General update for Middleton",
    "area": "middleton",
}) == ""

items = [
    {
        "story_key": "crime-1",
        "title": "Police update in East Middleton",
        "source_name": "GMP",
        "source_url": "https://example.org/crime-1",
        "category": "crime",
        "area": "middleton",
    },
    {
        "story_key": "sport-1",
        "title": "Rochdale AFC match report",
        "source_name": "Rochdale AFC",
        "source_url": "https://example.org/sport-1",
        "category": "sport",
        "area": "rochdale",
    },
    {
        "story_key": "traffic-1",
        "title": "Road closure in Kirkholt",
        "source_name": "Council",
        "source_url": "https://example.org/traffic-1",
        "category": "traffic",
        "area": "kirkholt",
    },
    {
        "story_key": "health-1",
        "title": "Health clinic opens in Healey ward",
        "source_name": "NHS",
        "source_url": "https://example.org/health-1",
        "category": "health",
        "area": "healey",
    },
    {
        "story_key": "vacancy-1",
        "title": "Vacancy: apply now",
        "source_name": "Council",
        "source_url": "https://example.org/jobs/vacancy-1",
        "category": "business",
        "area": "rochdale",
    },
]

selected, diagnostics = balanced_select(
    items,
    limit=10,
    max_per_source=2,
    max_per_category=3,
)

assert len(selected) == 4
assert all("vacancy" not in item["story_key"] for item in selected)
assert {"crime", "sport", "traffic", "health"} <= set(
    diagnostics["selected_categories"]
)
assert {
    "East Middleton",
    "Balderstone and Kirkholt",
    "Healey",
} <= set(diagnostics["selected_wards"])
assert len(ROCHDALE_WARDS) == 20

print("Selection policy regression tests passed.")

# ---------------------------------------------------------------------------
# Classified listings are advertising, not news. Live examples that published:
# a Milkstone Road rental, a "£1,285 pcm" pair of properties, and pet
# adoption posts. Market/housing NEWS must never be caught.
# ---------------------------------------------------------------------------
from selection_policy import is_classified_listing_post

assert is_classified_listing_post(
    "Three-bedroom terraced house available for rent on Milkstone Road. "
    "A three-bedroom terraced house on Milkstone Road in Rochdale is now "
    "available for rent at £1,295 per month."
)
assert is_classified_listing_post(
    "Two properties in Rochdale available for rent at £1,285 pcm."
)
assert is_classified_listing_post(
    "Adorable labrador puppies for sale in Heywood, ready to leave now."
)
assert is_classified_listing_post(
    "Ragamuffins available for adoption: kittens looking for forever homes."
)
assert is_classified_listing_post("", "https://example.com/property-for-sale/rochdale/123")

assert not is_classified_listing_post(
    "Average private rents in Rochdale rose 9% in a year, new figures show."
)
assert not is_classified_listing_post(
    "Rochdale council approves plan to build 200 new affordable homes in Kirkholt."
)
assert not is_classified_listing_post(
    "Fire crews rescued a dog from a house fire on Milkstone Road."
)
print("Classified-listing filter tests passed.")
