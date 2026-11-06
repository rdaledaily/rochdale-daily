"""Ordinary stories never show crime or court stories in their related boxes.

Measured 6 Nov 2026: "Related reporting" grouped by town alone, so the
Heywood Christmas Festival page led with an abuse trial; 140 non-crime pages
linked to 161 crime/court stories there and 87 more in the "More on this"
sidebar. Crime pages may still link to other crime stories.

Run: python -m pytest -q scraper/test_related_no_crime.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from archive_quality import related_graph, scrub_sidebar, sensitivity  # noqa: E402


def row(slug, title, area="heywood", published="2026-10-01", category=None):
    record = {"slug": slug, "title": title, "area": area, "indexable": True,
              "published_at": published, "excerpt": "", "content_html": "<p>Copy.</p>"}
    if category:
        record["category"] = category
    return record


FESTIVAL = row("festival", "Road closures for Heywood Christmas Festival", published="2026-10-31")
TRIAL = row("trial", "Heywood man on trial for alleged abuse of his wife", published="2026-10-30")
REMEMBRANCE = row("remembrance", "Road closures for Heywood Remembrance Sunday", published="2026-10-29")
CADETS = row("cadets", "Heywood cadets open evening for new members", published="2026-10-28")
STABBING = row("stabbing", "Teenager stabbed in Heywood town centre", published="2026-10-27")
ROWS = [FESTIVAL, TRIAL, REMEMBRANCE, CADETS, STABBING]


def test_trial_is_sensitive_festival_is_not():
    flags = sensitivity(ROWS)
    assert flags["trial"] and flags["stabbing"]
    assert not flags["festival"] and not flags["remembrance"] and not flags["cadets"]


def test_ordinary_story_never_links_to_crime():
    edges, _ = related_graph(ROWS)
    for ordinary in ("festival", "remembrance", "cadets"):
        assert not {"trial", "stabbing"} & set(edges[ordinary]), (ordinary, edges[ordinary])


def test_crime_stories_still_link_and_nothing_is_orphaned():
    edges, incoming = related_graph(ROWS)
    assert edges["trial"] and edges["stabbing"]
    for record in ROWS:
        assert edges[record["slug"]], record["slug"]
        assert incoming[record["slug"]], record["slug"]


def test_lone_court_story_is_paired_not_orphaned():
    tours = row("tours", "Guided tours of the historic court chamber", area="littleborough")
    edges, incoming = related_graph(ROWS + [tours])
    assert edges["tours"] and incoming["tours"]


SIDEBAR = (
    '<div class="sidebar-box"><h3 class="rail-title">More on this</h3>'
    '<a class="related-story" href="trial.html"><span class="related-title">Trial</span></a>'
    '<a class="related-story" href="remembrance.html"><span class="related-title">Remembrance</span></a>'
    '</div>'
)


def test_archive_sidebar_scrubbed_on_ordinary_page_only():
    flags = sensitivity(ROWS)
    cleaned = scrub_sidebar(SIDEBAR, flags["festival"], flags)
    assert 'href="trial.html"' not in cleaned
    assert 'href="remembrance.html"' in cleaned
    assert scrub_sidebar(SIDEBAR, flags["stabbing"], flags) == SIDEBAR
    assert scrub_sidebar(cleaned, flags["festival"], flags) == cleaned


def test_live_sidebar_skips_crime_on_ordinary_story():
    import generate_newspaper_pages as G
    base = {"status": "published", "area": "heywood", "content_html": "<p>Copy.</p>",
            "published_at": "2026-10-30T10:00:00Z"}
    festival = dict(base, slug="festival", title="Heywood Christmas Festival road closures", category="events")
    trial = dict(base, slug="trial", title="Heywood man on trial for alleged abuse of his wife",
                 category="crime", police_matter=True)
    walk = dict(base, slug="walk", title="Heywood heritage walk this weekend", category="community")
    box = G._newsroom_related_stories_markup(festival, [festival, trial, walk])
    assert 'href="trial.html"' not in box and 'href="walk.html"' in box
    crime_box = G._newsroom_related_stories_markup(trial, [festival, trial, walk])
    assert 'href="walk.html"' in crime_box
