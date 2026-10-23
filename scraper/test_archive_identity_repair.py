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
