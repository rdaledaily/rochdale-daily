"""Ward tags: the postcode rule, the area-and-headline rule, and the lookup
that feeds the postcode rule. Run: python -m pytest -q scraper/test_ward_tagging.py"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import editorial_contract as ec
import ward_postcode_evidence as wpe


def evidence(tmp_path, monkeypatch, entries):
    path = tmp_path / "ward_postcode_evidence.json"
    path.write_text(json.dumps(entries), encoding="utf-8")
    monkeypatch.setattr(ec, "POSTCODE_EVIDENCE_PATH", path)
    return path


HEYWOOD = {"district": "Rochdale", "ward": "North Heywood"}
LAKESIDE = {"district": "Rochdale", "ward": "Littleborough Lakeside"}
CENTRAL = {"district": "Rochdale", "ward": "Central Rochdale"}


def test_statutory_ward_names_match_the_sites_spelling():
    assert ec.canonical_ward("Balderstone & Kirkholt") == "Balderstone and Kirkholt"
    assert ec.canonical_ward("Wardle, Shore & West Littleborough") == "Wardle, Shore and West Littleborough"
    assert ec.canonical_ward("Milnrow and Newhey") == "Milnrow and Newhey"
    assert ec.canonical_ward("Higher Blackley") == ""
    assert all(ec.canonical_ward(ward) == ward for ward in ec.ROCHDALE_WARDS)


def test_a_venue_postcode_in_the_copy_decides_the_ward(tmp_path, monkeypatch):
    evidence(tmp_path, monkeypatch, {"OL101LW": HEYWOOD})
    story = {"title": "Free friendship group offers a place to meet people", "area": "heywood",
             "content_html": "<p>The group meets weekly.</p><p>The council gives the time as 1.30pm to 3.30pm at Heywood Library, LCpl Stephen Shaw MC Way, Heywood, OL10 1LW.</p>"}
    assert ec.story_postcodes(story) == ["OL101LW"]
    decision = ec.ward_decision(story)
    assert decision["wards"] == ["North Heywood"] and decision["status"] == "postcode-verified"


def test_a_postcode_not_looked_up_yet_decides_nothing(tmp_path, monkeypatch):
    evidence(tmp_path, monkeypatch, {})
    story = {"title": "Quiz night", "area": "heywood", "event_location": "Heywood Civic Centre, OL10 1LW"}
    assert ec.ward_decision(story)["wards"] == []


def test_a_correspondence_address_is_not_where_the_story_is(tmp_path, monkeypatch):
    evidence(tmp_path, monkeypatch, {"OL161XU": CENTRAL})
    story = {"title": "Wednesday deadline to comment on parking changes", "area": "rochdale",
             "content_html": "<p>Parking charges would change in three towns.</p><p>Objections should be sent in writing to Legal Services, Number One Riverside, Smith Street, Rochdale OL16 1XU.</p>"}
    assert ec.story_postcodes(story) == []
    assert ec.ward_decision(story)["wards"] == []


def test_round_ups_and_briefings_belong_to_no_ward(tmp_path, monkeypatch):
    evidence(tmp_path, monkeypatch, {"OL101LW": HEYWOOD, "OL150AQ": LAKESIDE, "OL161XU": CENTRAL})
    listing = {"title": "Halloween events across the borough", "area": "rochdale",
               "content_html": "<p>Here is what is on this Halloween.</p><p>Events at Heywood Library, OL10 1LW. Also at the lake, OL15 0AQ. And at Riverside, OL16 1XU.</p>"}
    assert ec.story_postcodes(listing) == []
    briefing = {"title": "Morning Briefing: Saturday 7 November 2026", "slug": "morning-briefing-7-november-2026", "area": "rochdale",
                "content_html": "<p>Today.</p><p>Bonfire at Littleborough Cricket Club, OL15 0AQ.</p>"}
    assert ec.story_postcodes(briefing) == []


def test_two_venues_are_two_wards_and_outside_the_borough_is_none(tmp_path, monkeypatch):
    evidence(tmp_path, monkeypatch, {"OL101LW": HEYWOOD, "OL150AQ": LAKESIDE, "M80AE": {"district": "Manchester", "ward": "Cheetham"}})
    two = {"title": "Free play sessions this week", "area": "rochdale",
           "content_html": "<p>Sessions run on Monday.</p><p>They are at Heywood Library, OL10 1LW, and at Hollingworth Lake visitor centre, OL15 0AQ.</p>"}
    assert ec.ward_decision(two)["wards"] == ["Littleborough Lakeside", "North Heywood"]
    away = {"title": "Magicians help organise dealers day", "area": "rochdale", "event_location": "Irish World Heritage Centre, M8 0AE"}
    assert ec.ward_decision(away)["wards"] == []


def test_area_tag_and_headline_agreeing_decide_the_ward():
    decision = ec.ward_decision({"title": "Castleton Sidings brings 191 homes", "excerpt": "", "area": "castleton"})
    assert decision["wards"] == ["Castleton"] and decision["status"] == "area-and-headline"
    assert ec.ward_decision({"title": "Kirkholt\u2019s Queen\u2019s Drive scheme promises 28 homes", "area": "kirkholt"})["wards"] == ["Balderstone and Kirkholt"]
    assert ec.ward_decision({"title": "Syke granted Conservation Area status", "area": "syke"})["wards"] == ["Healey"]
    both = ec.ward_decision({"title": "Bamford and Norden\u2019s 450-home allocation", "area": "norden"})
    assert both["wards"] == ["Bamford", "Norden"]


def test_neither_signal_alone_is_enough():
    # Filed under a place the headline does not name: a borough-wide story.
    assert ec.ward_decision({"title": "Rochdale achieves 21 gold awards at North West in Bloom", "area": "wardle"})["wards"] == []
    # The name without the area tag: a surname, a street, another Castleton.
    assert ec.ward_decision({"title": "Denis Healey biography launched", "area": "rochdale"})["wards"] == []
    assert ec.ward_decision({"title": "Castleton Road resurfacing begins", "area": "castleton"})["wards"] == []
    assert ec.ward_decision({"title": "Milnrow Road closed after collision", "area": "milnrow"})["wards"] == []
    assert ec.ward_decision({"title": "Milnrow road closure this weekend", "area": "milnrow"})["wards"] == ["Milnrow and Newhey"]
    assert ec.ward_decision({"title": "Hopwood Hall College partners with Rochdale AFC", "area": "hopwood"})["wards"] == []


def test_places_split_between_wards_are_never_guessed():
    for area, title in (("middleton", "Middleton market reopens"), ("heywood", "Heywood market reopens"), ("littleborough", "Littleborough market reopens")):
        assert ec.ward_decision({"title": title, "area": area})["wards"] == [], area
    places = ec.locality_wards()
    assert not {"middleton", "heywood", "littleborough", "rochdale"} & set(places)
    assert places["syke"] == "Healey" and places["alkrington"] == "South Middleton" and places["balderstone"] == "Balderstone and Kirkholt"
    assert set(places.values()) <= set(ec.ROCHDALE_WARDS)


def test_lookup_records_wards_and_asks_once():
    asked = []

    def fetch(batch):
        asked.append(list(batch))
        table = {"OL101LW": {"postcode": "OL10 1LW", "admin_district": "Rochdale", "admin_ward": "North Heywood", "codes": {"admin_ward": "E05014045"}},
                 "OL129LH": {"postcode": "OL12 9LH", "admin_district": "Rochdale", "admin_ward": "Wardle, Shore & West Littleborough", "codes": {}},
                 "M80AE": {"postcode": "M8 0AE", "admin_district": "Manchester", "admin_ward": "Cheetham", "codes": {}}}
        return [{"query": pc, "result": table.get(pc)} for pc in batch]

    stories = [{"title": "A", "event_location": "Heywood Civic, OL10 1LW"}, {"title": "B", "event_location": "Wardle Library, OL12 9LH"},
               {"title": "C", "event_location": "Manchester, M8 0AE"}, {"title": "D", "event_location": "Nowhere, OL99 9ZZ"}]
    cache = {}
    report = wpe.run(stories, cache, fetch, today="2026-11-13")
    assert report["looked_up"] == 4 and report["rochdale"] == 2 and not report["failed"] and not report["unmatched"]
    assert cache["OL129LH"]["ward"] == "Wardle, Shore and West Littleborough"
    assert cache["M80AE"]["district"] == "Manchester" and cache["OL999ZZ"] == {"found": False, "checked": "2026-11-13"}
    wpe.run(stories, cache, fetch, today="2026-11-14")
    assert len(asked) == 1


def test_lookup_failure_changes_nothing_and_unknown_wards_are_reported():
    def down(batch):
        raise OSError("network unreachable")

    cache = {}
    report = wpe.run([{"title": "A", "event_location": "Heywood Civic, OL10 1LW"}], cache, down)
    assert cache == {} and report["failed"] and report["looked_up"] == 0

    def renamed(batch):
        return [{"query": pc, "result": {"postcode": pc, "admin_district": "Rochdale", "admin_ward": "Heywood Central", "codes": {}}} for pc in batch]

    report = wpe.run([{"title": "A", "event_location": "Heywood Civic, OL10 1LW"}], cache, renamed)
    assert report["unmatched"] == ["Heywood Central"] and cache["OL101LW"]["ward"] == ""
