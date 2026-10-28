"""28 Oct 2026: removed stories must redirect, Read next must not link to
missing pages, and withheld-source links must never break the page."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import retired_urls  # noqa: E402
import source_presentation as SP  # noqa: E402
from generate_pages import prune_dead_related_links  # noqa: E402

SPORT_PAGE = (
    '<nav class="article-breadcrumb" aria-label="Breadcrumb"><a href="../">News</a>'
    '<span aria-hidden="true">/</span><a href="/news/sport">Sport</a></nav><h1>Match</h1>'
)


class RetiredUrlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.redirects = self.tmp / "_redirects"
        self.redirects.write_text("/rochdale / 301\n", encoding="utf-8")
        self.pages = self.tmp / "articles"
        self.pages.mkdir()

    def rules(self):
        return self.redirects.read_text(encoding="utf-8")

    def test_retire_page_writes_redirect_to_section_then_deletes(self):
        page = self.pages / "rochdale-v-crewe.html"
        page.write_text(SPORT_PAGE, encoding="utf-8")
        self.assertEqual(retired_urls.retire_page(page, self.redirects), "/news/sport")
        self.assertFalse(page.exists())
        self.assertIn("/articles/rochdale-v-crewe /news/sport 301", self.rules())
        self.assertIn("/articles/rochdale-v-crewe.html /news/sport 301", self.rules())
        self.assertTrue(self.rules().startswith("/rochdale / 301\n"))

    def test_generated_breadcrumb_with_html_suffix(self):
        self.assertEqual(
            retired_urls.hub_for_page('<nav class="article-breadcrumb"><a href="/news/crime.html">Crime</a></nav>'),
            "/news/crime",
        )

    def test_page_without_breadcrumb_goes_to_all_sections(self):
        page = self.pages / "no-crumb.html"
        page.write_text("<h1>x</h1>", encoding="utf-8")
        self.assertEqual(retired_urls.retire_page(page, self.redirects), "/news/")

    def test_editor_rule_wins_and_nothing_duplicates(self):
        self.redirects.write_text("/articles/old-story /articles/new-story 301\n", encoding="utf-8")
        page = self.pages / "old-story.html"
        page.write_text(SPORT_PAGE, encoding="utf-8")
        retired_urls.retire_page(page, self.redirects)
        self.assertNotIn("/news/sport", self.rules())
        self.assertFalse(retired_urls.record_redirect(self.redirects, "old-story", "/news/"))

    def test_backfill_only_for_missing_pages_and_real_slugs(self):
        (self.pages / "still-here.html").write_text(SPORT_PAGE, encoding="utf-8")
        written = retired_urls.backfill(
            self.redirects, self.pages, ["still-here", "gone-story", "Bad Slug!"], {"gone-story": "/news/sport"}
        )
        self.assertEqual(written, ["gone-story"])
        self.assertIn("/articles/gone-story /news/sport 301", self.rules())
        self.assertEqual(self.rules().count(retired_urls.SECTION_HEADER), 1)
        self.assertEqual(retired_urls.backfill(self.redirects, self.pages, ["gone-story"]), [])


class ReadNextPruneTests(unittest.TestCase):
    def test_dead_read_next_links_removed_live_ones_kept(self):
        pages = Path(tempfile.mkdtemp())
        (pages / "live-story.html").write_text("<h1>live</h1>", encoding="utf-8")
        page = pages / "archived.html"
        page.write_text(
            '<section class="read-next">'
            '<a class="rn-card" href="gone-lead.html"><span class="rn-title">Gone</span></a>'
            '<div class="rn-col"><h3 class="rn-heading">More from Heywood</h3>'
            '<a class="rn-item" href="george-galloway-wins">Old</a></div>'
            '<div class="rn-col"><h3 class="rn-heading">More Sport</h3>'
            '<a class="rn-item" href="live-story.html">Live</a></div></section>',
            encoding="utf-8",
        )
        changed, removed = prune_dead_related_links(pages, set())
        html = page.read_text(encoding="utf-8")
        self.assertEqual((changed, removed), (1, 2))
        self.assertNotIn("gone-lead", html)
        self.assertNotIn("george-galloway", html)
        self.assertNotIn("More from Heywood", html)  # emptied column dropped
        self.assertIn('href="live-story.html"', html)
        self.assertEqual(prune_dead_related_links(pages, set()), (0, 0))


class SourceLinkTests(unittest.TestCase):
    # Exact damaged markup from the live Peacocks story.
    DAMAGED = (
        "<p>Sources: the source’s opening-day report: "
        '<a href="the source rel=" noopener"="">the source Lisa Riley’s public opening announcement: </a>'
        '<a href="https://www.facebook.com/officiallisariley/posts/1/" rel="noopener">fb</a></p>'
    )

    def test_repair_restores_text_and_removes_broken_link(self):
        fixed = SP.repair_mangled_source_links(self.DAMAGED)
        self.assertNotIn('href="the source', fixed)
        self.assertIn("opening-day report. Lisa Riley’s public opening announcement:", fixed)
        self.assertIn('href="https://www.facebook.com/officiallisariley/posts/1/"', fixed)
        self.assertEqual(SP.repair_mangled_source_links(fixed), fixed)

    def test_sanitise_heals_any_article(self):
        article = {"title": "Peacocks opens", "content_html": self.DAMAGED, "source_url": "https://example.org"}
        self.assertNotIn('href="the source', SP.sanitise_article(article)["content_html"])

    def test_subtle_source_link_becomes_plain_words_and_next_link_survives(self):
        html = (
            '<p>Sources: Roch Valley Radio report: <a href="https://rochvalleyradio.com/news/x" rel="noopener">'
            'https://rochvalleyradio.com/news/x</a> Council notice: '
            '<a href="https://www.rochdale.gov.uk/y" rel="noopener">council</a></p>'
        )
        out = SP.clean_public_text(html)
        self.assertNotIn("rochvalleyradio", out)
        self.assertNotIn('href="the source', out)
        self.assertIn('<a href="https://www.rochdale.gov.uk/y" rel="noopener">council</a>', out)

    def test_bare_url_keeps_sentence_punctuation(self):
        self.assertEqual(
            SP.clean_public_text("Read more at https://rochvalleyradio.com/story-1. Thanks"),
            "Read more at the source. Thanks",
        )


if __name__ == "__main__":
    unittest.main()
