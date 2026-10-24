"""A publication's name is never evidence that two stories are the same.

Regression for 23 Oct 2026: "Rochdale Times" and "Read More" were extracted as
named entities, so any two Rochdale Times articles shared an entity and one
shared action word ("reject") forced ongoing_story_match to a 0.78 merge. Live
records fused a garden-fence appeal, a car-wash refusal and an RBH homes plan;
a bomb-threat school closure merged with a shop opening.
Run: python -m pytest -q scraper/test_publisher_name_not_entity.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import story_identity as S  # noqa: E402

WHEN = "2026-10-22T09:00:00Z"


def rt(title, body, category="environment"):
    return {
        "source_name": "Rochdale Times",
        "source_url": "https://www.rochdaletimes.co.uk/" + title.lower().replace(" ", "-")[:40],
        "source_title": f"{title} - Rochdale Times",
        "source_summary": body[:140],
        "source_body_excerpt": body + " Read More Rochdale Times",
        "source_published_at": WHEN,
        "area": "rochdale",
        "category": category,
        "related_sources": [],
    }


FENCE = rt(
    "Inspector rules on garden fence rejected by council",
    "A homeowner faces having to tear down a garden fence in Littleborough after a "
    "Planning Inspector rejected her appeal. Rochdale Council refused retrospective permission.",
)
FALINGE = rt(
    "RBH unveils new homes plan for Lower Falinge",
    "RBH has submitted an outline planning application to build up to 270 homes for "
    "affordable or social rent in Lower Falinge. Earlier proposals were rejected by residents.",
)
TAKEAWAY = rt(
    "New takeaway would be bad for people's health",
    "Rochdale Council has rejected an application for a hot food takeaway, saying it "
    "would harm health near a school.",
)
BOMB = rt("School closes after bomb threat", "A Rochdale school closed after a bomb threat was received. Pupils were sent home and police attended.", "crime")
BOYES = rt("Finishing touches being applied as Boyes opens new store tomorrow", "Boyes opens its new Rochdale store tomorrow with staff applying finishing touches.", "business")


def test_publisher_name_and_link_text_are_not_entities():
    for item in (FENCE, FALINGE, TAKEAWAY):
        entities = S.named_entities(item)
        assert "rochdale times" not in entities
        assert "read more" not in entities


def test_unrelated_same_publisher_stories_do_not_merge():
    assert not S.same_story(FENCE, FALINGE)
    assert not S.same_story(TAKEAWAY, FENCE)
    assert not S.same_story(TAKEAWAY, FALINGE)
    assert not S.ongoing_story_match(FENCE, FALINGE)


def test_any_publisher_name_is_ignored_dynamically():
    a = dict(FENCE, source_name="Heywood Clarion", source_body_excerpt=FENCE["source_body_excerpt"] + " Heywood Clarion")
    b = dict(FALINGE, source_name="Heywood Clarion", source_body_excerpt=FALINGE["source_body_excerpt"] + " Heywood Clarion")
    assert "heywood clarion" not in S.named_entities(a)
    assert not S.same_story(a, b)


def test_same_plan_from_two_outlets_still_merges():
    other = {
        "source_name": "Roch Valley Radio",
        "source_url": "https://www.rochvalleyradio.com/news/rbh-lower-falinge-270-homes",
        "source_title": "RBH submits plans for up to 270 homes in Lower Falinge",
        "source_summary": "RBH has submitted plans for up to 270 new homes in Lower Falinge.",
        "source_body_excerpt": "RBH has submitted an outline planning application for up to 270 homes "
                               "for affordable or social rent across two sites in Lower Falinge.",
        "source_published_at": WHEN,
        "area": "rochdale",
        "category": "environment",
        "related_sources": [],
    }
    assert S.same_story(FALINGE, other)


def test_distinct_council_records_never_merge():
    # 24 Oct 2026: notices for different streets scored 0.80-0.94 and fused
    # 4-17 roadworks notices per story.
    def notice(title, record):
        return {"source_name": "Rochdale Borough Council",
                "source_url": f"https://www.rochdale.gov.uk/directory-record/{record}/x",
                "source_title": title, "source_summary": title, "source_published_at": WHEN,
                "area": "rochdale", "category": "traffic", "related_sources": []}
    joy = notice("Joy Street, roadworks in Rochdale from 2 November 2026", 2640)
    trafalgar = notice("Trafalgar Street, roadworks in Rochdale on 26 November 2026", 2638)
    assert not S.same_story(joy, trafalgar)
    assert not S.ongoing_story_match(joy, trafalgar)
    assert S.same_story(joy, dict(joy))
    men = dict(joy, source_name="Manchester Evening News",
               source_url="https://www.manchestereveningnews.co.uk/news/joy-street-roadworks")
    assert S.same_story(joy, men)
