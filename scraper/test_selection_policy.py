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
