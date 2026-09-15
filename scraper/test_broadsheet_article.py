"""The broadsheet port of the article template, pinned.

These tests exist because each of them corresponds to something that was
actually wrong before the port, not to a hypothetical regression:

  * article pages carried a masthead and no navigation at all;
  * the corrections box and the generated footers still held #f5c400, a gold
    from a palette retired two rounds ago;
  * a malformed timestamp printed "1 Jan 1" on the byline, because parse_iso
    returns datetime.min on failure;
  * the archived-page rewrite runs on every pipeline run over 1,130 files, so
    it has to be exactly idempotent or it appends the navigation again each
    time.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import generate_pages as gp


def _article(**overrides):
    base = {
        "slug": "test-story",
        "title": "A Test Story About Rochdale",
        "category": "news",
        "excerpt": "A short standfirst for the test story.",
        "content_html": "<p>First paragraph.</p><p>Second paragraph.</p>",
        "published_at": "2026-09-14T08:30:00+00:00",
        "byline": "Rochdale Daily Newsdesk",
    }
    base.update(overrides)
    return base


class ArticleShellTests(unittest.TestCase):
    def test_generated_page_carries_the_edition_bar(self):
        page = gp.render_article_page(_article(), [])
        self.assertIn('class="primary-nav"', page)
        self.assertIn('class="utility"', page)
        # Every destination in the edition bar, so a reader who lands on a
        # story from search can reach the rest of the paper.
        for label in ("Your area", "Democracy", "Community support", "Local services"):
            self.assertIn(label, page)

    def test_masthead_search_pill_is_not_emitted(self):
        # The canvas has no search in the masthead; it lives at the right-hand
        # end of the edition bar instead.
        page = gp.render_article_page(_article(), [])
        self.assertNotIn('class="masthead-actions"', page)
        self.assertIn('class="menu-search"', page)

    def test_retired_gold_is_gone_from_generated_markup(self):
        page = gp.render_article_page(
            _article(corrections=[{"note": "A correction.", "date": "2026-09-14"}]), []
        )
        # The markup only. site.css is inlined into every page and still holds
        # literals of its own (#e9e9e9 for the body ground among them); those
        # are overridden by newspaper-global.css and are a separate job. What
        # this pins is that no colour is written into the TEMPLATE, where no
        # stylesheet can reach it.
        markup = page.split("</style>", 1)[-1]
        for retired in ("#f5c400", "#e5d089", "#fdf6dc", "#c9c9c9", "#f6f6f6", "#b3001b", "#fbeaec"):
            self.assertNotIn(retired, markup, f"{retired} still written into the markup")

    def test_retired_faces_are_not_requested(self):
        # rd-tokens.css @imports Libre Baskerville and Instrument Sans. The
        # page was also fetching Inter and Libre Franklin, which no rule uses.
        page = gp.render_article_page(_article(), [])
        self.assertNotIn("family=Inter", page)
        self.assertNotIn("Libre+Franklin", page)


class BylineDateTests(unittest.TestCase):
    def test_real_timestamp_is_printed(self):
        page = gp.render_article_page(_article(), [])
        self.assertIn("14 Sep 2026", page)

    def test_unparseable_timestamp_prints_nothing(self):
        # parse_iso returns datetime.min, which formats as year 1.
        page = gp.render_article_page(_article(published_at="not a date", scraped_at=""), [])
        self.assertNotIn("Jan 1 ", page)
        self.assertNotIn(" 1 Jan 1", page)


class OngoingChipTests(unittest.TestCase):
    def test_chip_absent_by_default(self):
        self.assertNotIn("kicker-chip", gp.render_article_page(_article(), []))

    def test_chip_uses_the_pipeline_label(self):
        page = gp.render_article_page(
            _article(is_ongoing=True, ongoing_label="Live"), []
        )
        self.assertIn('<span class="kicker-chip">Live</span>', page)

    def test_chip_falls_back_to_ongoing(self):
        page = gp.render_article_page(_article(is_ongoing=True), [])
        self.assertIn('<span class="kicker-chip">Ongoing</span>', page)


class ArchivedShellTests(unittest.TestCase):
    PAGE = (
        "<!DOCTYPE html><html><body>\n"
        '  <header class="masthead">\n'
        '    <div class="wrap masthead-row"></div>\n'
        "  </header>\n"
        '  <div class="article-layout"></div>\n'
        "</body></html>\n"
    )

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = self.dir / "old-story.html"
        self.path.write_text(self.PAGE, encoding="utf-8")

    def test_shell_is_injected_in_canvas_order(self):
        self.assertEqual(gp.modernise_archived_masthead(self.dir, skip=set()), 1)
        text = self.path.read_text(encoding="utf-8")
        utility = text.find('class="utility"')
        masthead = text.find('<header class="masthead">')
        nav = text.find("primary-nav archived-nav")
        self.assertNotEqual(utility, -1)
        self.assertNotEqual(nav, -1)
        self.assertLess(utility, masthead, "utility bar must sit above the masthead")
        self.assertLess(masthead, nav, "edition bar must sit below the masthead")

    def test_second_pass_changes_nothing(self):
        gp.modernise_archived_masthead(self.dir, skip=set())
        once = self.path.read_text(encoding="utf-8")
        self.assertEqual(gp.modernise_archived_masthead(self.dir, skip=set()), 0)
        self.assertEqual(self.path.read_text(encoding="utf-8"), once)
        self.assertEqual(once.count('class="utility"'), 1)
        self.assertEqual(once.count("primary-nav archived-nav"), 1)

    def test_page_without_a_masthead_is_left_alone(self):
        stray = self.dir / "no-masthead.html"
        stray.write_text("<html><body><p>Nothing to hang it on.</p></body></html>", encoding="utf-8")
        gp.modernise_archived_masthead(self.dir, skip=set())
        self.assertNotIn(gp.ARCHIVED_SHELL_MARKER, stray.read_text(encoding="utf-8"))

    def test_skip_list_is_honoured(self):
        gp.modernise_archived_masthead(self.dir, skip={"old-story"})
        self.assertNotIn(gp.ARCHIVED_SHELL_MARKER, self.path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
