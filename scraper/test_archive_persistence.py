"""Regression tests: published article pages stay online forever.

Guards against the regression measured on the live site in July 2026, where
published article pages had a median lifespan of 4.3 hours because:
  1. frontpage_pipeline.cleanup_stale_article_pages() deleted every page
     whose slug was not in the current articles.json, and
  2. any article under 200 body words was re-queued for a rewrite on every
     15-minute run, and each rewrite's slightly different headline changed
     the slug, dropping the old slug out of articles.json.

The contract now: a published URL is permanent. Pages are removed only for
explicit takedowns listed in story_blocklist.json, and an already-published
story keeps its slug, id and story key across every subsequent rewrite.

Run directly: python scraper/test_archive_persistence.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def test_cleanup_never_deletes_stale_pages() -> None:
    import frontpage_pipeline as fp

    with tempfile.TemporaryDirectory() as tmp:
        pages = Path(tmp)
        (pages / "old-story-no-longer-live.html").write_text("<html>archived</html>", encoding="utf-8")
        (pages / "current-story.html").write_text("<html>live</html>", encoding="utf-8")
        original_dir = fp.ARTICLE_PAGES_DIR
        fp.ARTICLE_PAGES_DIR = pages
        try:
            live_articles = [{"slug": "current-story"}]
            removed = fp.cleanup_stale_article_pages(live_articles, blocklist={"slugs": []})
            assert removed == 0, "no page may be deleted merely for leaving articles.json"
            assert (pages / "old-story-no-longer-live.html").exists(), (
                "a page whose story left the live feed must remain online as archive"
            )
            removed_default = fp.cleanup_stale_article_pages(live_articles)
            assert removed_default == 0, "cleanup with no blocklist must delete nothing"
            assert (pages / "old-story-no-longer-live.html").exists()
        finally:
            fp.ARTICLE_PAGES_DIR = original_dir
    print("cleanup: stale pages preserved — OK")


def test_cleanup_removes_only_blocklisted_slugs() -> None:
    import frontpage_pipeline as fp

    with tempfile.TemporaryDirectory() as tmp:
        pages = Path(tmp)
        (pages / "takedown-target.html").write_text("<html>blocked</html>", encoding="utf-8")
        (pages / "innocent-archive-story.html").write_text("<html>archived</html>", encoding="utf-8")
        original_dir = fp.ARTICLE_PAGES_DIR
        fp.ARTICLE_PAGES_DIR = pages
        try:
            removed = fp.cleanup_stale_article_pages(
                [], blocklist={"slugs": ["Takedown-Target"]}
            )
            assert removed == 1, "exactly the blocklisted page is removed"
            assert not (pages / "takedown-target.html").exists()
            assert (pages / "innocent-archive-story.html").exists()
        finally:
            fp.ARTICLE_PAGES_DIR = original_dir
    print("cleanup: blocklist takedowns honoured, case-insensitively — OK")


def test_sitemap_includes_archived_pages() -> None:
    import generate_pages as gp

    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "archived-story.html"
        page.write_text(
            '<html><script type="application/ld+json">'
            '{"@type":"NewsArticle","datePublished":"2026-07-01T09:30:00Z"}'
            "</script></html>",
            encoding="utf-8",
        )
        lastmod = gp.archive_page_lastmod(page)
        assert lastmod == "2026-07-01T09:30:00Z", f"unexpected lastmod: {lastmod!r}"

        undated = Path(tmp) / "undated-story.html"
        undated.write_text("<html>no schema</html>", encoding="utf-8")
        assert gp.archive_page_lastmod(undated) == ""
    print("sitemap: archived page dates read from JSON-LD — OK")


def test_sitemap_omits_lastmod_when_unknown() -> None:
    import generate_pages as gp

    with tempfile.TemporaryDirectory() as tmp:
        original = gp.SITEMAP_PATH
        gp.SITEMAP_PATH = Path(tmp) / "sitemap.xml"
        try:
            gp.write_sitemap([("dated", "2026-07-01T09:30:00Z"), ("undated", "")])
            xml = gp.SITEMAP_PATH.read_text(encoding="utf-8")
            assert "/articles/dated.html</loc><lastmod>2026-07-01T09:30:00Z</lastmod>" in xml
            assert "/articles/undated.html</loc><changefreq>" in xml, (
                "entries without a known date must omit lastmod, not invent one"
            )
        finally:
            gp.SITEMAP_PATH = original
    print("sitemap: unknown dates omitted rather than faked — OK")


def test_short_articles_are_not_perpetually_rewritten() -> None:
    from scraper import Candidate, candidate_is_rewrite_eligible
    from house_style import STYLE_VERSION

    candidate = Candidate(
        source_name="Traffic Update — Rochdale",
        source_url="https://www.traffic-update.co.uk/traffic/rochdale.asp#live-abc",
        source_title="Slow traffic on the A627(M) near junction 20",
        source_summary="Queueing traffic reported northbound.",
        source_published_at="2026-07-10T08:00:00Z",
        area="rochdale",
        category="traffic",
    )
    candidate.story_key = "traffic-v3-shortbrief"
    existing = {
        "traffic-v3-shortbrief": {
            "slug": "slow-traffic-on-the-a627m-near-junction-20",
            "editorial_style_version": STYLE_VERSION,
            "content_html": "<p>" + " ".join(["word"] * 120) + "</p>",  # 120 words: short by design
            "source_url": "https://www.traffic-update.co.uk/traffic/rochdale.asp#live-abc",
            "source_urls": ["https://www.traffic-update.co.uk/traffic/rochdale.asp#live-abc"],
        }
    }
    assert not candidate_is_rewrite_eligible(candidate, existing), (
        "a published short brief with no new source material must not be "
        "re-queued for rewriting (this loop caused hourly slug churn)"
    )

    fresh_material = Candidate(
        source_name="Manchester Evening News — Rochdale",
        source_url="https://www.manchestereveningnews.co.uk/news/a627m-junction-20-collision",
        source_title="Collision closes A627(M) slip road",
        source_summary="Two vehicles involved; recovery under way.",
        source_published_at="2026-07-10T09:00:00Z",
        area="rochdale",
        category="traffic",
    )
    fresh_material.story_key = "traffic-v3-shortbrief"
    assert candidate_is_rewrite_eligible(fresh_material, existing), (
        "a genuinely new source URL for the same story must trigger a rewrite"
    )
    print("eligibility: short briefs stable, new material still updates — OK")


def test_events_candidates_never_consume_rewrite_slots() -> None:
    from scraper import Candidate, candidate_is_rewrite_eligible

    event = Candidate(
        source_name="Visit Rochdale",
        source_url="https://www.visitrochdale.com/whats-on/summer-fair",
        source_title="Summer fair returns to Broadfield Park",
        source_summary="Family fun day this weekend.",
        source_published_at="2026-07-10T08:00:00Z",
        area="rochdale",
        category="events",
    )
    assert not candidate_is_rewrite_eligible(event, {}), (
        "events candidates are guaranteed skips downstream and must be "
        "filtered before selection"
    )
    print("eligibility: events candidates excluded before selection — OK")


def test_editorial_lock_still_respected() -> None:
    from scraper import Candidate, candidate_is_rewrite_eligible

    candidate = Candidate(
        source_name="Roch Valley Radio",
        source_url="https://www.rochvalleyradio.com/news/local-news/locked-story-update",
        source_title="Update on locked story",
        source_summary="New details.",
        source_published_at="2026-07-10T08:00:00Z",
        area="rochdale",
        category="news",
    )
    candidate.story_key = "hard-news-v3-locked"
    existing = {
        "hard-news-v3-locked": {
            "slug": "hand-edited-story",
            "editorial_lock": True,
            "source_urls": [],
        }
    }
    assert not candidate_is_rewrite_eligible(candidate, existing), (
        "editorially locked articles are never rewritten, even with new URLs"
    )
    print("eligibility: editorial lock respected — OK")


def main() -> int:
    test_cleanup_never_deletes_stale_pages()
    test_cleanup_removes_only_blocklisted_slugs()
    test_sitemap_includes_archived_pages()
    test_sitemap_omits_lastmod_when_unknown()
    test_short_articles_are_not_perpetually_rewritten()
    test_events_candidates_never_consume_rewrite_slots()
    test_editorial_lock_still_respected()
    print("Archive persistence and URL stability tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
