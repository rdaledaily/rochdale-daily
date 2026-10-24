"""House headline style: sentence case, names kept, editors and events untouched.

Every case here is a real headline from 24 Oct 2026, including the ones that
went wrong while this was built. Run: python -m pytest -q scraper/test_headline_style.py
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import headline_style as H  # noqa: E402

CASES = [
    ("Rochdale AFC Draw 2-2 with Grimsby Town in League Two Match",
     "Rochdale AFC drew with Grimsby Town in League Two on Tuesday.",
     "Rochdale AFC draw 2-2 with Grimsby Town in League Two match"),
    ("Office of Rail and Road Rejects Proposal for Extra Rochdale to London Train Services",
     "The rail regulator, the Office of Rail and Road, said the extra services were rejected.",
     "Office of Rail and Road rejects proposal for extra Rochdale to London train services"),
    ("Rochdale AFC to Face Bolton in Midweek Cup Tie",
     "Dale will travel to face Bolton Wanderers. The tie is on Tuesday.",
     "Rochdale AFC to face Bolton in midweek cup tie"),
    ("Nine-Year-Old Guitar Virtuoso Adrian Abraham from Middleton on Verge of World Record",
     "Nine-year-old Adrian Abraham from Middleton is close to a world record on guitar.",
     "Nine-year-old guitar virtuoso Adrian Abraham from Middleton on verge of world record"),
    ("Temporary Road Closures on Trafalgar Street and Joy Street in Rochdale",
     "Temporary road closures are planned. Motorists should plan ahead.",
     "Temporary road closures on Trafalgar Street and Joy Street in Rochdale"),
    ("Rochdale Unemployment Claimants Increase to 8,775 in September 2026",
     "In September the number rose. The claimant count is from the ONS.",
     "Rochdale unemployment claimants increase to 8,775 in September 2026"),
    ("Rochdale's Music Heritage Celebrated in New Album 'Kenion Street'",
     "A new album celebrates the town's music heritage.",
     "Rochdale's music heritage celebrated in new album 'Kenion Street'"),
    ("Rochdale-London Train Service Proposal Rejected by Regulator",
     "The regulator rejected the plan.",
     "Rochdale-London train service proposal rejected by regulator"),
    ("Mother and Baby Found Safe After Police Search in Rochdale",
     "A mother and baby were found safe after a police search, Greater Manchester Police said.",
     "Mother and baby found safe after police search in Rochdale"),
]


def test_real_headlines():
    for title, body, expected in CASES:
        assert H.sentence_case(title, body) == expected, (title, H.sentence_case(title, body))


def test_idempotent_and_never_adds_capitals():
    for title, body, expected in CASES:
        assert H.sentence_case(expected, body) == expected


def test_sentence_case_headlines_left_alone():
    editor = "Christine found after incredible community effort"
    assert H.sentence_case(editor, "") == editor


def test_editors_and_events_never_restyled():
    assert not H.should_restyle({"manual_article": True, "publication_route": "ai-grounded-rewrite"})
    assert not H.should_restyle({"publication_route": "editorial"})
    assert not H.should_restyle({"event_start_at": "2026-11-07T16:00:00Z", "publication_route": "ai-grounded-rewrite"})
    assert not H.should_restyle({"category": "events"})
    assert H.should_restyle({"publication_route": "ai-grounded-rewrite", "category": "sport"})


def test_title_tag_drops_suffix_only_when_too_long():
    assert H.title_tag("Bolton cup tie") == "Bolton cup tie | Rochdale Daily"
    long = "Rochdale AFC draw 2-2 with Grimsby Town in League Two match"
    assert H.title_tag(long) == long


def test_restyle_feed():
    rows = [
        {"title": "Rochdale AFC to Face Bolton in Midweek Cup Tie", "publication_route": "ai-grounded-rewrite",
         "content_html": "<p>Dale will face Bolton Wanderers.</p>", "category": "sport"},
        {"title": "Littleborough Cricket Club Bonfire 2026", "event_start_at": "2026-11-07T16:00:00Z",
         "category": "events"},
        {"title": "Birtle View Nursery Opens", "manual_article": True},
    ]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "articles.json"
        path.write_text(json.dumps(rows), encoding="utf-8")
        assert H.restyle_feed(path) == 1
        out = json.loads(path.read_text(encoding="utf-8"))
        assert out[0]["title"] == "Rochdale AFC to face Bolton in midweek cup tie"
        assert out[1]["title"] == "Littleborough Cricket Club Bonfire 2026"
        assert out[2]["title"] == "Birtle View Nursery Opens"
        assert H.restyle_feed(path) == 0


def test_road_and_code_identifiers_stay_whole():
    assert H.sentence_case("Delays Expected After M62 Crash Near Rochdale", "") == \
        "Delays expected after M62 crash near Rochdale"
    assert H.sentence_case("Roadworks Planned on the A58 Through Littleborough Next Week", "") == \
        "Roadworks planned on the A58 through Littleborough next week"
    assert H.sentence_case("Overnight Closure of A627(M) Slip Road Near Rochdale", "") == \
        "Overnight closure of A627(M) slip road near Rochdale"
    assert H.sentence_case("Plans for 17-Storey Tower Next to Historic Pub Rejected", "") == \
        "Plans for 17-storey tower next to historic pub rejected"
    assert H.sentence_case("Rochdale AFC Draw 2-2 with Grimsby Town in League Two Match",
                           "Rochdale drew with Grimsby Town in League Two.") == \
        "Rochdale AFC draw 2-2 with Grimsby Town in League Two match"


def test_titles_and_saints_keep_capitals():
    assert H.sentence_case("Upcoming Services and Events at St Luke's Church, Deeplish", "") == \
        "Upcoming services and events at St Luke's Church, Deeplish"
