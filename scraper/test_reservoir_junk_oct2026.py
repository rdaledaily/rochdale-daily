"""Junk kept out of the candidate reservoir (19 Oct 2026).

Every record below is taken from newsroom_candidates.json on 19 Oct 2026.
Before this change the reservoir was saved before the editorial blocklist ran,
so these leads sat in it for 96 hours and the candidate autopsy counted them
as "would publish". The real stories at the bottom must keep getting through.

Run from the repository root:  python scraper/test_reservoir_junk_oct2026.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
os.chdir(ROOT)  # story_blocklist.json is resolved relative to the repo root

import run_fast_local_pipeline as lane  # noqa: E402
from story_blocklist import is_stream_spam_title, load_blocklist  # noqa: E402

GOOGLE = "https://news.google.com/rss/articles/CBMi1AJBVV95cUxOTkg2bDJBTzhF"


def lead(title, url, name, *, summary="", body="", kind="article", publisher=""):
    return SimpleNamespace(
        source_title=title,
        source_url=url,
        source_name=name,
        source_summary=summary or title,
        source_body_excerpt=body or title,
        source_kind=kind,
        publisher_home_url=publisher,
    )


JUNK = {
    # A source named only in non-Latin script is denied outright (24 Oct 2026,
    # after pirate-stream spam from a hijacked Japanese council host).
    "denied source": [
        lead("Hartlepool United vs Rochdale head-to-head record, results and stats | All Football",
             "https://m.dongqiudi.com/article/1", "懂球帝"),
    ],
    "denied publisher host": [
        lead(">[!WATCHLIVE]4K!]Rochdale vs Crewe 𝐋𝐈𝐕𝐄 ＯＮ Ｔｖ Ｃｈａｎｎｅｌ 17 october 2026 - Universidad de Córdoba (UCO)",
             GOOGLE, "Universidad de Córdoba (UCO)", publisher="https://www.uco.es"),
        lead("+✨+Streaming/TV:Crewe vs Rochdale en direct Live - Universidad de Córdoba (UCO)",
             GOOGLE, "Universidad de Córdoba (UCO)", publisher="https://www.uco.es"),
    ],
    "editorial blocklist or stream spam": [
        lead("Service updates Live train times, planned disruption and events Breadcrumb Home",
             "https://www.northernrailway.co.uk/travel/service-updates", "Northern live service updates", kind="live"),
        lead("Rochdale Valiant: News and Media", "https://www.rochdalevaliant.uk/", "Rochdale Valiant"),
    ],
    "share/print utility page": [
        lead("Email a friend — Lisa Riley opens new Peacocks store at Rochdale Riverside - Roch Valley Radio",
             "https://www.rochvalleyradio.com/news-features/email-friend/1040", "Roch Valley Radio",
             body="Lisa Riley opens new Peacocks store at Rochdale Riverside To email a friend with a link, "
                  "complete the form below and choose Submit. Required fields are marked *."),
    ],
    "static non-news page": [
        lead("Contact Estates and Asset Management - Rochdale Borough Council - Rochdale Borough Council",
             "https://www.rochdale.gov.uk/contact-us/estates-asset-management-team-contact-details",
             "Rochdale Borough Council",
             summary="Estates and Asset Management contact details. Estates and Asset Management Team contact details."),
    ],
    "page carries only the site name": [
        lead("Rochdale Borough Council", "https://publicaccess.rochdale.gov.uk/online-applications/",
             "Rochdale Borough Council"),
    ],
}

REAL_STORIES = [
    lead("Lisa Riley opens new Peacocks store at Rochdale Riverside",
         "https://www.rochvalleyradio.com/news/local-news/lisa-riley-opens-new-peacocks-store", "Roch Valley Radio Local News"),
    lead("Hopwood Hall ‘will be brought back into community use’",
         "https://www.rochvalleyradio.com/news/local-news/hopwood-hall", "Roch Valley Radio Local News"),
    lead("Rochdale school evacuated and closed after suspected hoax call",
         "https://www.rochvalleyradio.com/news/local-news/school-hoax", "Roch Valley Radio Local News"),
    lead("Crewe 3-2 Rochdale | League Two highlights - Sky Sports",
         "https://www.skysports.com/football/video/13600381/crewe-3-2-rochdale-league-two-highlights", "Sky Sports"),
    lead("Travel alerts", "https://tfgm.com/travel-updates/travel-alerts?no-script=true", "TfGM Travel Alerts",
         kind="live",
         summary="Our travel alert page lets you check for any disruption on the network.",
         body="No trams will operate on the Eccles, Trafford Centre and Altrincham lines, with service "
              "changes in place across the network. From Monday 19 October to Sunday 1 November."),
    lead("Rochdale Borough Council",
         "https://publicaccess.rochdale.gov.uk/online-applications/applicationDetails.do?keyVal=X",
         "Rochdale Borough Council",
         summary="Demolition of existing dwelling and erection of 45 dwellings, land at Bamford Road, Rochdale",
         body="Proposal: demolition of existing dwelling and erection of 45 dwellings with access and landscaping."),
    lead("Next steps for historic Hopwood Hall after council avoided £1 sale in High Court",
         "https://www.manchestereveningnews.co.uk/news/greater-manchester-news/hopwood-hall-1",
         "Manchester Evening News"),
]


def test_every_real_junk_record_is_kept_out_for_the_right_reason():
    blocklist = load_blocklist()
    for expected, records in JUNK.items():
        for record in records:
            assert lane.reservoir_junk_reason(record, blocklist) == expected, record.source_title
            assert not lane._reservoir_candidate_allowed(record, blocklist), record.source_title


def test_real_stories_still_enter_the_reservoir():
    blocklist = load_blocklist()
    for record in REAL_STORIES:
        assert lane.reservoir_junk_reason(record, blocklist) == "", record.source_title


def test_stream_spam_title_rule_catches_all_three_hosts_without_the_host():
    # Hosts rotate; the title rule has to stand on its own.
    for title in (
        ">[!WATCHLIVE]4K!]Rochdale vs Crewe 𝐋𝐈𝐕𝐄 ＯＮ Ｔｖ Ｃｈａｎｎｅｌ 17 october 2026",
        "+✨+Streaming/TV:Crewe vs Rochdale en direct Live",
        "𝚆𝙰𝚃𝙲𝙷 (𝐓ODAY) Rochdale vs Crewe Alexandra 𝐋𝐈𝐕𝐄 𝐒𝐭𝐫𝐞𝐚𝐦 Ｔｖ Ｃｈａｎｎｅｌ",
        "Rochdale vs Oldham Athletic en vivo",
    ):
        assert is_stream_spam_title(title), title


def test_stream_rule_leaves_ordinary_fixture_and_live_headlines_alone():
    for title in (
        "Crewe 3-2 Rochdale | League Two highlights",
        "Preview | Crewe Alexandra (A)",
        "Rochdale vs Walsall: Dale fight back to win at the Crown Oil Arena",
        "Live music project brings early evening gigs to Rochdale",
        "Rochdale Hornets v Swinton: live updates as derby goes to golden point",
        "Bonfire night events taking place in Rochdale",
    ):
        assert not is_stream_spam_title(title), title


def test_reservoir_round_trip_drops_junk_already_on_disk(tmp_path=None):
    import json
    import tempfile

    folder = Path(tmp_path or tempfile.mkdtemp())
    original = lane.RESERVOIR_FILE
    lane.RESERVOIR_FILE = folder / "newsroom_candidates.json"
    try:
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        stamp = now.isoformat().replace("+00:00", "Z")
        records = []
        for record in [JUNK["denied publisher host"][0], JUNK["share/print utility page"][0], REAL_STORIES[0]]:
            item = {name: "" for name in lane.CANDIDATE_FIELD_NAMES}
            item.update(vars(record))
            item["source_published_at"] = stamp
            item = {key: value for key, value in item.items() if key in lane.CANDIDATE_FIELD_NAMES}
            records.append(item)
        lane.RESERVOIR_FILE.write_text(json.dumps({"candidates": records}), encoding="utf-8")
        loaded = lane._load_reservoir()
        assert [c.source_title for c in loaded] == [REAL_STORIES[0].source_title]
    finally:
        lane.RESERVOIR_FILE = original


def test_autopsy_reports_junk_instead_of_would_publish():
    from datetime import datetime, timezone

    import candidate_autopsy as autopsy

    gates, unavailable = autopsy.build_gates(datetime.now(timezone.utc))
    assert "junk page" in gates, unavailable
    stamp = datetime.now(timezone.utc).isoformat()
    record = dict(vars(JUNK["share/print utility page"][0]), source_published_at=stamp)
    assert autopsy.classify(record, gates) == "junk page"


if __name__ == "__main__":
    tests = [value for key, value in sorted(globals().items()) if key.startswith("test_")]
    for test in tests:
        test()
        print("ok", test.__name__)
    print(f"{len(tests)} passed")
