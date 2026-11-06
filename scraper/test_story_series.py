"""Series links: 'Enjoyed this article? We think you'll find ... interesting.'

Run: python -m pytest -q scraper/test_story_series.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import story_series as S  # noqa: E402

SERIES = [
    {"id": "christmas", "label": "Christmas", "window_days": 70,
     "pattern": re.compile(r"\b(?:christmas|festive|panto)\b", re.I)},
    {"id": "remembrance", "label": "Remembrance", "window_days": 21,
     "pattern": re.compile(r"\bremembrance\b", re.I)},
]


def story(slug, title, day, **extra):
    record = {"slug": slug, "title": title, "category": "events", "status": "published",
              "published_at": f"2026-{day}T10:00:00Z", "content_html": "<p>One.</p><p>Two.</p>"}
    record.update(extra)
    return record


PARKING = story("xmas-parking", "Free Christmas parking in Rochdale town centre", "11-20")
MARKETS = story("xmas-markets", "Every Christmas market in the borough", "11-18")
EVENTS = story("xmas-events", "Every Christmas event in Rochdale this year", "11-15")
PANTO = story("panto", "Cinderella panto opens at Middleton Arena", "11-10", area="middleton")
LAST_YEAR = story("xmas-2025", "Christmas lights switch-on draws crowds", "11-01", published_at="2025-12-01T10:00:00Z")
COURT = story("court", "Man charged after Christmas party assault", "11-19", category="crime")
SPONSORED = story("advert", "A kitchen for Christmas from a family firm", "11-19", sponsored=True)
UNRELATED = story("bins", "Bin collection changes for Kirkholt", "11-19")
FEED = [PARKING, MARKETS, EVENTS, PANTO, LAST_YEAR, COURT, SPONSORED, UNRELATED]


def related(article, feed=FEED):
    return [slug for slug, _ in S.related(article, feed, series=SERIES)]


def test_series_members_link_to_each_other():
    assert set(related(PARKING)) <= {"xmas-markets", "xmas-events", "panto"}
    assert len(related(PARKING)) == 3
    for member in (MARKETS, EVENTS, PANTO):
        assert "xmas-parking" in related(member) or len(related(member)) == 3


def test_every_member_is_reachable():
    members = [PARKING, MARKETS, EVENTS, PANTO]
    incoming = {m["slug"]: 0 for m in members}
    for member in members:
        for slug in related(member):
            incoming[slug] += 1
    assert all(incoming.values()), incoming


def test_last_years_season_is_not_linked():
    assert "xmas-2025" not in related(PARKING)
    assert related(LAST_YEAR) == []


def test_crime_sponsored_and_unrelated_never_join():
    for slug in ("court", "advert", "bins"):
        assert slug not in related(PARKING)
    assert related(COURT) == [] and related(SPONSORED) == []
    assert related(UNRELATED) == []


def test_editor_series_field_adds_a_story():
    bus = story("bus", "Late buses added for shoppers", "11-19", series="christmas")
    assert "bus" in related(PARKING, FEED + [bus])
    assert "xmas-parking" in related(bus, FEED + [bus])


def test_near_identical_copies_count_once_but_different_towns_do_not():
    a = story("rem-milnrow", "Road closures in Milnrow for Remembrance Sunday", "11-03")
    b = story("rem-norden", "Road closures in Norden for Remembrance Sunday", "11-03")
    c = story("rem-milnrow-copy", "Road closures in Milnrow for Remembrance Sunday service", "11-04")
    d = story("rem-service", "Remembrance services across the borough", "11-05")
    links = related(d, [a, b, c, d])
    assert "rem-norden" in links
    assert not ({"rem-milnrow", "rem-milnrow-copy"} <= set(links))


def test_same_town_comes_first():
    lights = story("mid-lights", "Middleton Christmas lights switch-on", "11-19", area="middleton")
    assert related(lights, FEED + [lights])[0] == "panto"


def test_line_wording_and_no_line_without_members():
    line = S.markup([("a", "First story"), ("b", "Second story"), ("c", "Third & last")])
    assert line.startswith('<p class="rd-series-links">Enjoyed this article? We think you’ll find ')
    assert line.endswith(" interesting.</p>")
    assert '<a href="/articles/a">First story</a>, <a href="/articles/b">Second story</a> and ' in line
    assert "Third &amp; last" in line
    assert S.markup([("a", "Only one")]).count("<a ") == 1
    assert S.markup([]) == ""


def test_insert_appends_once_and_skips_stories_already_linked(monkeypatch):
    monkeypatch.setattr(S, "load_series", lambda path=None: SERIES)
    body = '<p>One.</p><p class="rd-related-inline">Read more: <a href="/articles/xmas-markets">M</a></p><p>Two.</p>'
    once = S.insert(body, PARKING, FEED)
    twice = S.insert(once, PARKING, FEED)
    assert once == twice
    assert once.count('class="rd-series-links"') == 1
    line = re.search(r'<p class="rd-series-links">.*?</p>', once).group(0)
    assert "xmas-markets" not in line
    assert once.rstrip().endswith("</p>") and once.index("rd-series-links") > once.index("Two.")
    assert S.insert(UNRELATED["content_html"], UNRELATED, FEED) == UNRELATED["content_html"]


def test_strip_removes_the_line():
    line = S.markup([("a", "First")])
    assert S.strip("<p>Copy.</p>" + line) == "<p>Copy.</p>"


def test_shipped_config_loads_and_matches_real_headlines():
    loaded = S.load_series()
    ids = {s["id"] for s in loaded}
    assert {"christmas", "bonfire-night", "remembrance"} <= ids
    christmas = next(s for s in loaded if s["id"] == "christmas")
    for title in ("Middleton prepares for Christmas lights switch-on event",
                  "Heywood Civic launches its 10th pantomime with Aladdin",
                  "Littleborough Christmas lights: Church Street restrictions confirmed"):
        assert christmas["pattern"].search(title), title
    assert not christmas["pattern"].search("Council budget gap widens")
