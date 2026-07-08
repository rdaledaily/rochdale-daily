from locality_rules import AREA_KEYWORDS, detect_area, is_local

CASES = [
    (
        False,
        "Queen Elizabeth II favoured Kate Middleton's wedding over Princess Diana's",
        "BBC News",
        "",
        "Kate Middleton is a person, not the town of Middleton",
    ),
    (
        False,
        "Ella Langley achieves Billboard milestone",
        "Music News",
        "",
        "Ella Langley is a person and Langley is not an accepted locality",
    ),
    (
        False,
        "Actor David Wardle wins television award",
        "Entertainment News",
        "",
        "Wardle used as a surname must not count",
    ),
    (
        False,
        "Historian Bill Heywood receives national award",
        "National News",
        "",
        "Heywood used as a surname must not count",
    ),
    (
        True,
        "Police have closed a road in Middleton after a collision",
        "Regional News",
        "",
        "Explicit geographical wording",
    ),
    (
        True,
        "Middleton residents are invited to a council meeting",
        "Regional News",
        "",
        "Place followed by residents",
    ),
    (
        True,
        "Flood warning issued for Wardle village",
        "Environment Agency",
        "",
        "Place followed by village",
    ),
    (
        True,
        "Heywood pub announces reopening date",
        "Regional News",
        "",
        "Place followed by pub",
    ),
    (
        True,
        "Ella Langley will perform at Rochdale Town Hall",
        "Events Listing",
        "",
        "The event has an explicit Rochdale location",
    ),
    (
        True,
        "Service update",
        "Rochdale Borough Council",
        "https://www.rochdale.gov.uk/news/example",
        "Trusted local first-party source",
    ),
    (
        False,
        "Local council update",
        "Rochdale Times",
        "https://www.rochdaletimes.co.uk/example",
        "Explicitly denied source",
    ),
]

for expected, text, source_name, source_url, reason in CASES:
    actual = is_local(text, source_name, source_url)
    assert actual is expected, (
        f"{reason}: expected {expected}, got {actual} for {text!r}"
    )

assert detect_area(
    "Middleton residents are invited to a council meeting"
) == "middleton"

# Person names must produce no area.
assert detect_area(
    "Queen Elizabeth II favoured Kate Middleton's wedding"
) == ""
assert detect_area(
    "Ella Langley achieves Billboard milestone"
) == ""
assert detect_area(
    "Actor David Wardle wins television award"
) == ""
assert detect_area(
    "Historian Bill Heywood receives national award"
) == ""

# An untrusted caller cannot force a non-local story into Rochdale.
assert detect_area(
    "Queen Elizabeth II favoured Kate Middleton's wedding",
    fallback="rochdale",
    source_name="BBC News",
) == ""

# A verified local first-party source may use an explicit fallback.
assert detect_area(
    "Service update",
    fallback="rochdale",
    source_name="Rochdale Borough Council",
    source_url="https://www.rochdale.gov.uk/news/example",
) == "rochdale"

assert detect_area(
    "Ella Langley will perform at Rochdale Town Hall"
) == "rochdale"

assert "langley" not in AREA_KEYWORDS

print(f"Locality regression tests passed: {len(CASES)} classification cases plus area tests.")

assert not is_local(
    "Local news update",
    "Rochdale Online",
    "https://www.rochdaleonline.co.uk/news/example",
)
