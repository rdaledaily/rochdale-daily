"""The /roadworks page lists every council notice, honestly grouped.

Run: python -m pytest -q scraper/test_roadworks_page.py
"""
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import generate_roadworks_page as G  # noqa: E402
import primary_data as P  # noqa: E402

# Real anchor text shape from rochdale.gov.uk's roadworks directory (23 Oct 2026).
LISTING = """
<a href="/directory-record/2647/elizabethan-way-roadworks-in-milnrow-from-23-october-2026">Elizabethan Way, roadworks in Milnrow from 23 October 2026</a>
<a href="/directory-record/2640/joy-street-roadworks-in-rochdale-from-2-november-2026">Joy Street, roadworks in Rochdale from 2 November 2026</a>
<a href="/directory-record/2641/west-starkey-street-roadworks-in-heywood-from-26-october-2026">West Starkey Street, roadworks in Heywood from 26 October 2026</a>
<a href="/directory-record/2642/rochdale-bonfire-road-closures">Rochdale Bonfire and Firework Display, road closures in Rochdale on 4 November 2026</a>
<a href="/directory-record/2500/old-works">Smith Street, roadworks in Rochdale from 1 August 2026</a>
<a href="/directory-record/2600/no-date">Toad Lane and surrounding streets, roadworks in Rochdale</a>
"""
NOW = datetime(2026, 10, 24, 9, 0, tzinfo=timezone.utc)


def test_collector_saves_whole_listing():
    rows = P.parse_roadworks_listing(LISTING)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "roadworks.json"
        P.save_roadworks_listing(rows, NOW, path)
        data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data["notices"]) == 6
    joy = next(n for n in data["notices"] if n["id"] == "2640")
    assert joy["start"] == "2026-11-02" and joy["area"] == "rochdale"
    assert joy["url"].startswith("https://www.rochdale.gov.uk/directory-record/2640/")
    west = next(n for n in data["notices"] if n["id"] == "2641")
    assert west["area"] == "heywood"


def test_empty_listing_never_overwrites():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "roadworks.json"
        path.write_text('{"notices": [1]}', encoding="utf-8")
        P.save_roadworks_listing([], NOW, path)
        assert path.read_text(encoding="utf-8") == '{"notices": [1]}'


def test_grouping_and_rendering():
    rows = P.parse_roadworks_listing(LISTING)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "roadworks.json"
        P.save_roadworks_listing(rows, NOW, path)
        payload = json.loads(path.read_text(encoding="utf-8"))
    groups = G.group(payload["notices"], NOW.date())
    assert [n["id"] for n in groups["week"]] == ["2641"]                 # 26 Oct
    assert [n["id"] for n in groups["recent"]] == ["2647"]               # 23 Oct
    assert [n["id"] for n in groups["later"]] == ["2640", "2642"]        # 2 and 4 Nov
    assert [n["id"] for n in groups["undated"]] == ["2600"]
    article = {"slug": "joy-street-roadworks", "source_url": payload["notices"][1]["url"]}
    html = G.render(payload, [article], NOW)
    assert "Smith Street" not in html                                    # started 1 Aug: not current
    assert "West Starkey Street" in html and "Heywood" in html
    assert 'href="/articles/joy-street-roadworks.html">Our report' in html
    assert "<title>Roadworks and road closures in Rochdale this week | Rochdale Daily</title>" in html
    assert 'rel="canonical" href="https://rochdaledaily.co.uk/roadworks.html"' in html


def test_describe_splits_road_and_detail():
    assert G.describe("Joy Street, roadworks in Rochdale from 2 November 2026 - Rochdale Borough Council") == (
        "Joy Street", "Roadworks in Rochdale from 2 November 2026")


def test_no_page_without_data():
    import os
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        try:
            assert G.main() == 0
            assert not Path("roadworks.html").exists()
        finally:
            os.chdir(cwd)
