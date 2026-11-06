"""Category misfiles the editor flagged on 4 Nov 2026, pinned on real copy."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from editorial_upgrade import deterministic_category  # noqa: E402


def test_police_appeal_for_wanted_man_is_crime():
    text = ("Police appeal for help finding Kibriya Ahmed linked to missing children. "
            "Ahmed is wanted for breaching a non-molestation order. Their disappearance "
            "raises concerns about their safety and wellbeing.")
    assert deterministic_category(text, "health") == "crime"


def test_sleep_out_for_homeless_is_community():
    text = ("Rochdale Sleep Out raises funds for homeless support. Participants slept "
            "rough to support homelessness services and mental health support.")
    assert deterministic_category(text, "health") == "community"


def test_leisure_centre_pool_closure_is_not_health():
    text = ("Rochdale Leisure Centre small pool closed for repairs. The leisure centre's "
            "fitness suite remains open.")
    assert deterministic_category(text, "health") == "community"


def test_guided_walk_from_station_is_community_not_transport():
    # Never "events": that category is reserved for the approved listings
    # source, and any other "events" story is deleted from the feed.
    text = ("Outdoor guided walk 'Stories We Tell: Rochdale' to explore themes of belonging. "
            "The walk starts at Rochdale Train Station, sharing storytelling about the town.")
    assert deterministic_category(text, "transport") == "community"


def test_rail_disruption_stays_transport():
    text = ("No trains between Rochdale and Manchester Victoria this week as replacement "
            "buses run from the station.")
    assert deterministic_category(text, "transport") == "transport"


def test_football_club_raffle_appeal_stays_sport():
    text = ("New grassroots football club Heywood Hurricanes FC appeals for raffle prizes "
            "to raise funds and keep football free; local businesses asked for donation.")
    assert deterministic_category(text, "sport") == "sport"


# 6 Nov 2026: headline rules in frontpage_pipeline. Full cases live in
# test_headline_category_rules.py; these pin them in the CI-run file.
def test_headline_rules_on_live_misfiles():
    import frontpage_pipeline as fp
    cases = {
        "Resident escapes fire at Lonsdale Court sheltered housing in Middleton": "news",
        "Banned driver leads police on high-speed chase through Rochdale": "crime",
        "Rochdale Council awards contract for Queen's Park SEND improvement project": "business",
        "Rochdale and Bury see significant increases in driving test pass rates": "transport",
        "Inquest Jury Clears Police Following Fatal High-Speed Chase in Rochdale": "",
        "Moorland blaze near Watergrove": "",
    }
    for title, expected in cases.items():
        assert fp.headline_category_rule(title) == expected, title


# 6 Nov 2026: events stories from outside the box office are kept, and the
# headline files What's On news as events and festival road closures as traffic.
def test_whats_on_news_is_events_and_closures_are_traffic():
    import frontpage_pipeline as fp
    cases = {
        "Cinderella panto set to enchant audiences at Middleton Arena this Christmas": "events",
        "Mark Winstanley returns to stage after MS diagnosis for Rochdale comedy show": "events",
        "Middleton prepares for Christmas lights switch-on event": "events",
        "Road closures announced for Heywood Christmas Festival on 14 November 2026": "traffic",
    }
    for title, expected in cases.items():
        assert fp.headline_category_rule(title) == expected, title


def test_events_story_from_outside_box_office_is_kept():
    import frontpage_pipeline as fp
    story = {"id": "x1", "slug": "panto", "title": "Cinderella panto at Middleton Arena",
             "category": "events", "source_url": "https://www.manchestereveningnews.co.uk/x"}
    original = fp.save_event_dates
    fp.save_event_dates = lambda dates: None
    try:
        kept, stats = fp.clean_and_integrate_events([story], [])
    finally:
        fp.save_event_dates = original
    assert [a["slug"] for a in kept] == ["panto"]
    assert stats["events_kept_other_source"] == 1


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"ok {_name}")
