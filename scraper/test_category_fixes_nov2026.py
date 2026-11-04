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


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"ok {_name}")
