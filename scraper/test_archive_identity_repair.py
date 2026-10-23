"""Retired URLs stay gone; canonicals never name a missing or unrelated story.

Run: python -m pytest -q scraper/test_archive_identity_repair.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import archive_identity_repair as R  # noqa: E402


def page(slug, h1, canonical=None):
    canonical = canonical or slug
    return (
        f'<html><head><link rel="canonical" href="https://rochdaledaily.co.uk/articles/{canonical}.html">'
        f'<meta property="og:url" content="https://rochdaledaily.co.uk/articles/{canonical}.html"></head>'
        f'<body><h1>{h1}</h1><div class="article-copy"><p>Body.</p></div></body></html>'
    )


def setup(pages, redirects):
    tmp = Path(tempfile.mkdtemp())
    (tmp / "articles").mkdir()
    for slug, h1, canonical in pages:
        (tmp / "articles" / f"{slug}.html").write_text(page(slug, h1, canonical), encoding="utf-8")
    (tmp / "_redirects").write_text(redirects, encoding="utf-8")
    return tmp


def canonical(tmp, slug):
    text = (tmp / "articles" / f"{slug}.html").read_text(encoding="utf-8")
    return R._CANONICAL.search(text).group(1)


REDIRECTS = """/rochdale / 301
# comment
/articles/old-bamford-mixup.html /news/crime 301
/articles/old-bamford-mixup /news/crime 301
/articles/shrewsbury-win-duplicate /articles/rochdale-beat-shrewsbury-3-0 301
/articles/still-live-story /news/ 301
/articles/:splat /x 301
"""


def test_retired_pages_removed_but_live_pages_kept():
    tmp = setup([
        ("old-bamford-mixup", "Man Arrested Following Thefts in Bamford Area", None),
        ("still-live-story", "Still live", None),
    ], REDIRECTS)
    stats = R.repair(tmp / "articles", tmp / "_redirects", {"still-live-story"})
    assert not (tmp / "articles" / "old-bamford-mixup.html").exists()
    assert (tmp / "articles" / "still-live-story.html").exists()
    assert stats["retired_pages_removed"] == 1 and stats["retired_but_live_kept"] == 1


def test_canonical_to_removed_page_follows_redirect_when_same_story():
    tmp = setup([
        ("shrewsbury-win-duplicate", "Rochdale beat Shrewsbury 3-0", None),
        ("rochdale-beat-shrewsbury-3-0", "Rochdale beat Shrewsbury Town 3-0 for first league win", None),
        ("dale-first-league-win-shrewsbury", "Dale first league win: 3-0 over Shrewsbury", "shrewsbury-win-duplicate"),
    ], REDIRECTS)
    R.repair(tmp / "articles", tmp / "_redirects", set())
    assert canonical(tmp, "dale-first-league-win-shrewsbury").endswith("/rochdale-beat-shrewsbury-3-0.html")


def test_canonical_to_unrelated_story_points_to_self():
    tmp = setup([
        ("rochdale-secures-first-league-win-over-shrewsbury", "Rochdale secures first league win over Shrewsbury", "youth-team-loses-to-salford"),
        ("youth-team-loses-to-salford", "Youth team loses 4-3 to Salford City in PDL Cup", None),
    ], REDIRECTS)
    R.repair(tmp / "articles", tmp / "_redirects", set())
    slug = "rochdale-secures-first-league-win-over-shrewsbury"
    assert canonical(tmp, slug).endswith(f"/{slug}.html")
    text = (tmp / "articles" / f"{slug}.html").read_text(encoding="utf-8")
    assert f'og:url" content="https://rochdaledaily.co.uk/articles/{slug}.html"' in text


def test_genuine_duplicate_canonical_untouched_and_idempotent():
    tmp = setup([
        ("tram-disruption-oldham-rochdale", "Tram services suspended between Oldham and Rochdale", "trams-suspended-oldham-rochdale"),
        ("trams-suspended-oldham-rochdale", "Trams suspended between Oldham and Rochdale", None),
    ], REDIRECTS)
    first = R.repair(tmp / "articles", tmp / "_redirects", set())
    second = R.repair(tmp / "articles", tmp / "_redirects", set())
    assert canonical(tmp, "tram-disruption-oldham-rochdale").endswith("/trams-suspended-oldham-rochdale.html")
    assert first["canonicals_to_self"] == second["canonicals_to_self"] == 0


def test_dynamic_rules_ignored():
    assert ":splat" not in R.retired_article_redirects(setup([], REDIRECTS) / "_redirects")


def _page_with(slug, title, published, canonical=None):
    canonical = canonical or slug
    return (
        f'<html><head><title>{title}</title>'
        f'<link rel="canonical" href="https://rochdaledaily.co.uk/articles/{canonical}.html">'
        f'<meta property="article:published_time" content="{published}"></head>'
        f'<body><h1>{title}</h1><div class="article-copy"><p>{BODY_TEXT}</p></div></body></html>'
    )


BODY_TEXT = ("Rochdale AFC secured their first league win of the season with a three nil "
             "victory over Shrewsbury Town at the Crown Oil Arena on Saturday afternoon, "
             "with goals from Henderson, Tasker and Middleton sending the home supporters "
             "away happy after a difficult opening month for the club and its manager")


def test_identical_archived_titles_point_to_earliest():
    tmp = setup([], "")
    title = "Rochdale AFC Secures 3-0 Victory Against Shrewsbury Town | Rochdale Daily"
    for slug, when in (("b-later", "2026-08-10T10:00:00Z"), ("a-first", "2026-08-09T10:00:00Z"), ("c-latest", "2026-08-11T10:00:00Z")):
        (tmp / "articles" / f"{slug}.html").write_text(_page_with(slug, title, when), encoding="utf-8")
    stats = R.repair(tmp / "articles", tmp / "_redirects", set())
    assert stats["duplicate_titles_consolidated"] == 2
    assert canonical(tmp, "b-later").endswith("/a-first.html")
    assert canonical(tmp, "c-latest").endswith("/a-first.html")
    assert canonical(tmp, "a-first").endswith("/a-first.html")
    assert R.repair(tmp / "articles", tmp / "_redirects", set())["duplicate_titles_consolidated"] == 0


def test_groups_with_a_live_story_are_left_alone():
    tmp = setup([], "")
    title = "Same headline | Rochdale Daily"
    (tmp / "articles" / "live-one.html").write_text(_page_with("live-one", title, "2026-10-01T00:00:00Z"), encoding="utf-8")
    (tmp / "articles" / "old-one.html").write_text(_page_with("old-one", title, "2026-08-01T00:00:00Z"), encoding="utf-8")
    (tmp / "articles" / "old-two.html").write_text(_page_with("old-two", title, "2026-08-02T00:00:00Z"), encoding="utf-8")
    R.repair(tmp / "articles", tmp / "_redirects", {"live-one"})
    assert canonical(tmp, "old-two").endswith("/old-two.html")


def test_same_headline_different_story_not_merged():
    tmp = setup([], "")
    title = "Rochdale fixture news | Rochdale Daily"
    a = _page_with("first", title, "2026-08-01T00:00:00Z")
    b = _page_with("second", title, "2026-08-02T00:00:00Z").replace(
        BODY_TEXT, "Bradford City will host the club in the first round of the Carabao Cup next month "
                   "after the draw was made on Thursday evening, with kick-off times still to be "
                   "confirmed by the English Football League and both clubs awaiting broadcast picks")
    (tmp / "articles" / "first.html").write_text(a, encoding="utf-8")
    (tmp / "articles" / "second.html").write_text(b, encoding="utf-8")
    R.repair(tmp / "articles", tmp / "_redirects", set())
    assert canonical(tmp, "second").endswith("/second.html")


def test_same_body_canonical_left_to_archive_integrity():
    tmp = setup([], "")
    copy = _page_with("al-rayyan-to-face-rochdale", "Al-Rayyan to face Rochdale", "2026-08-01T00:00:00Z", "york-city-to-face-rochdale")
    primary = _page_with("york-city-to-face-rochdale", "York City visit Rochdale on Saturday", "2026-08-01T00:00:00Z")
    (tmp / "articles" / "al-rayyan-to-face-rochdale.html").write_text(copy, encoding="utf-8")
    (tmp / "articles" / "york-city-to-face-rochdale.html").write_text(primary, encoding="utf-8")
    stats = R.repair(tmp / "articles", tmp / "_redirects", set())
    assert canonical(tmp, "al-rayyan-to-face-rochdale").endswith("/york-city-to-face-rochdale.html")
    assert stats["canonicals_to_self"] == 0
