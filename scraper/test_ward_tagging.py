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


# ------------------------------------------------------------------ streets
def street_files(tmp_path, monkeypatch, streets, checked):
    listed = tmp_path / "rochdale_streets.json"
    listed.write_text(json.dumps({"streets": streets}), encoding="utf-8")
    on_file = tmp_path / "ward_street_evidence.json"
    on_file.write_text(json.dumps(checked), encoding="utf-8")
    monkeypatch.setattr(ec, "STREETS_PATH", listed)
    monkeypatch.setattr(ec, "STREET_EVIDENCE_PATH", on_file)
    monkeypatch.setattr(wpe, "STREET_EVIDENCE_PATH", on_file)
    return on_file


LISTED = {"joy street": {"name": "Joy Street", "postcodes": ["OL12 0BY"]},
          "trafalgar street": {"name": "Trafalgar Street", "postcodes": ["OL16 2EB"]},
          "manchester road": {"name": "Manchester Road", "postcodes": ["OL11 2SP", "OL11 3AA", "OL11 4HA"]},
          "church street": {"name": "Church Street", "postcodes": ["OL16 3QS"]}}
JOY = {"street": "Joy Street", "district": "Rochdale", "ward": "Central Rochdale", "nearby_wards": ["Central Rochdale"], "single_ward": True}
EDGE = {"street": "Trafalgar Street", "district": "Rochdale", "ward": "Central Rochdale",
        "nearby_wards": ["Central Rochdale", "Smallbridge and Firgrove"], "single_ward": False}


def test_a_short_street_in_the_headline_decides_the_ward(tmp_path, monkeypatch):
    street_files(tmp_path, monkeypatch, LISTED, {"joy street": JOY})
    story = {"title": "Joy Street roadworks scheduled from 2 November 2026", "area": "rochdale"}
    assert ec.story_streets(story) == [{"street": "Joy Street", "postcode": "OL120BY"}]
    decision = ec.ward_decision(story)
    assert decision["wards"] == ["Central Rochdale"] and decision["status"] == "street-verified"
    # Leading words are not part of the name.
    assert ec.story_streets({"title": "Police On Joy Street after reports of a disturbance", "area": "rochdale"})[0]["street"] == "Joy Street"


def test_long_roads_boundary_streets_and_unchecked_streets_decide_nothing(tmp_path, monkeypatch):
    street_files(tmp_path, monkeypatch, LISTED, {"joy street": JOY, "trafalgar street": EDGE})
    # Listed in three postcode sectors: runs through several wards. It is
    # still reported, with nothing to check, so it can block a tag.
    assert ec.story_streets({"title": "Manchester Road closed after collision", "area": "rochdale"}) == [{"street": "Manchester Road", "postcode": ""}]
    assert ec.ward_decision({"title": "Manchester Road closed after collision", "area": "rochdale"})["wards"] == []
    # Checked, and found to sit on a ward boundary.
    assert ec.ward_decision({"title": "Trafalgar Street, roadworks in Rochdale", "area": "rochdale"})["wards"] == []
    # Named with a street that is settled and one that is not: left alone.
    assert ec.ward_decision({"title": "Joy Street and Trafalgar Street to close", "area": "rochdale"})["wards"] == []
    # Listed but not checked yet.
    assert ec.ward_decision({"title": "Church Street resurfacing begins", "area": "rochdale"})["wards"] == []


def test_streets_are_not_read_from_the_body_or_from_towns_the_list_does_not_cover(tmp_path, monkeypatch):
    street_files(tmp_path, monkeypatch, LISTED, {"joy street": JOY})
    assert ec.story_streets({"title": "Man charged after burglary", "area": "rochdale", "content_html": "<p>He was arrested on Joy Street.</p>"}) == []
    assert ec.story_streets({"title": "Joy Street roadworks begin", "area": "heywood"}) == []
    assert ec.story_streets({"title": "Joy Street, Middleton, to close for a week", "area": "rochdale"}) == []
    briefing = {"title": "Morning Briefing", "slug": "morning-briefing-14-november-2026", "excerpt": "Joy Street roadworks and more", "area": "rochdale"}
    assert ec.story_streets(briefing) == []


def test_a_place_or_postcode_still_outranks_a_street(tmp_path, monkeypatch):
    street_files(tmp_path, monkeypatch, LISTED, {"joy street": JOY})
    decision = ec.ward_decision({"title": "Joy Street residents in Castleton call for crossing", "area": "castleton"})
    assert decision["wards"] == ["Castleton"] and decision["status"] == "explicit-ward"


def near(postcode, ward, district="Rochdale"):
    return {"postcode": postcode, "admin_district": district, "admin_ward": ward}


def test_street_check_needs_every_nearby_postcode_in_the_same_ward(tmp_path, monkeypatch):
    on_file = street_files(tmp_path, monkeypatch, LISTED, {})
    stories = [{"title": "Joy Street roadworks", "area": "rochdale"}, {"title": "Trafalgar Street roadworks", "area": "rochdale"},
               {"title": "Church Street resurfacing", "area": "rochdale"}]
    asked = []

    def fetch(postcode):
        asked.append(postcode)
        return {"OL120BY": [near("OL12 0BY", "Central Rochdale"), near("OL12 0BZ", "Central Rochdale")],
                "OL162EB": [near("OL16 2EB", "Central Rochdale"), near("OL16 2EA", "Smallbridge & Firgrove")],
                "OL163QS": None}[postcode]

    cache = {}
    report = wpe.run_streets(stories, cache, fetch, today="2026-11-14")
    assert report["looked_up"] == 3 and report["single_ward"] == 1 and report["boundary"] == 1 and report["waiting"] == 0
    assert cache["joy street"]["single_ward"] is True and cache["joy street"]["ward"] == "Central Rochdale"
    assert cache["trafalgar street"]["single_ward"] is False
    assert cache["trafalgar street"]["nearby_wards"] == ["Central Rochdale", "Smallbridge and Firgrove"]
    assert cache["church street"]["found"] is False
    wpe.run_streets(stories, cache, fetch, today="2026-11-15")
    assert len(asked) == 3  # asked once
    # A neighbour outside the borough is a boundary too.
    assert wpe.street_entry("X Street", "OL120BY", [near("OL12 0BY", "Healey"), near("OL12 8ZZ", "Facit and Shawforth", "Rossendale")], "2026-11-14")["single_ward"] is False
    # An answer that leaves out the street's own postcode proves nothing.
    assert wpe.street_entry("X Street", "OL120BY", [near("OL12 0BZ", "Healey")], "2026-11-14")["found"] is False
    assert json.loads(on_file.read_text()) == {}


def test_street_check_failure_changes_nothing_and_is_capped(tmp_path, monkeypatch):
    names = [f"Test{chr(65 + i // 26)}{chr(97 + i % 26)} Street" for i in range(60)]
    many = {name.casefold(): {"name": name, "postcodes": [f"OL12 {i % 10}A{chr(65 + i % 26)}"]} for i, name in enumerate(names)}
    street_files(tmp_path, monkeypatch, many, {})
    stories = [{"title": f"{name} roadworks", "area": "rochdale"} for name in names]

    def down(postcode):
        raise OSError("network unreachable")

    cache = {}
    report = wpe.run_streets(stories, cache, down)
    assert cache == {} and report["failed"] and report["waiting"] == 60
    report = wpe.run_streets(stories, cache, lambda pc: None)
    assert report["looked_up"] == wpe.STREETS_PER_RUN and report["waiting"] == 60 - wpe.STREETS_PER_RUN


def test_a_settled_street_beside_a_long_or_unlisted_road_is_not_enough(tmp_path, monkeypatch):
    # Review, 14 Nov 2026: the long road was dropped before the "every street
    # settled" check, so Joy Street alone placed the whole story.
    street_files(tmp_path, monkeypatch, LISTED, {"joy street": JOY})
    mixed = {"title": "Joy Street and Manchester Road roadworks from Monday", "area": "rochdale"}
    assert ec.story_streets(mixed) == [{"street": "Joy Street", "postcode": "OL120BY"}, {"street": "Manchester Road", "postcode": ""}]
    assert ec.ward_decision(mixed)["wards"] == []
    unlisted = {"title": "Joy Street and Gorrels Way to close for resurfacing", "area": "rochdale"}
    assert {"street": "Gorrels Way", "postcode": ""} in ec.story_streets(unlisted)
    assert ec.ward_decision(unlisted)["wards"] == []
    # Evidence left on file for a road that later turns out to be long is ignored.
    stale = dict(JOY, street="Manchester Road")
    street_files(tmp_path, monkeypatch, LISTED, {"joy street": JOY, "manchester road": stale})
    assert ec.ward_decision(mixed)["wards"] == []
    assert ec.ward_decision({"title": "Manchester Road closed", "area": "rochdale"})["wards"] == []
    # Joy Street on its own is still placed, and only checkable streets are looked up.
    assert ec.ward_decision({"title": "Joy Street roadworks", "area": "rochdale"})["wards"] == ["Central Rochdale"]
    asked = []
    wpe.run_streets([mixed, unlisted], {}, lambda pc: asked.append(pc) or None)
    assert asked == ["OL120BY"]
    # The reviewer's own example, and a road named after a town the list does not cover.
    assert ec.ward_decision({"title": "Joy Street and Halifax Road roadworks", "area": "rochdale"})["wards"] == []
    assert ec.story_streets({"title": "Joy Street roadworks in Middleton", "area": "rochdale"}) == []
