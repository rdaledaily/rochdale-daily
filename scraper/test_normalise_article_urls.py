import tempfile
import unittest
from pathlib import Path
from normalise_article_urls import normalise_text, normalise_snapshot


class PublicArticleUrlTests(unittest.TestCase):
    def test_archived_related_links_can_still_be_pruned_after_alignment(self):
        from generate_pages import prune_dead_related_links
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'winner.html').write_text('Winner', encoding='utf-8')
            page = root / 'archive.html'
            page.write_text('<a class="related-story" href="winner">Keep</a><a class="related-story" href="missing">Drop</a>', encoding='utf-8')
            self.assertEqual(prune_dead_related_links(root, set()), (1, 1))
            self.assertIn('Keep', page.read_text())
            self.assertNotIn('Drop', page.read_text())

    def test_metadata_duplicate_targets_and_suffixes(self):
        text = '<link rel="canonical" href="https://rochdaledaily.co.uk/articles/winner.html"><meta property="og:url" content="https://rochdaledaily.co.uk/articles/winner.html"><script>{"@id":"https://rochdaledaily.co.uk/articles/winner.html#article"}</script><a href="/articles/winner.html?share=1#top">Read</a>'
        result = normalise_text(text, {'winner'})
        self.assertNotIn('.html', result)
        self.assertIn('/articles/winner#article', result)
        self.assertIn('/articles/winner?share=1#top', result)

    def test_source_links_images_and_nonarticle_pages_unchanged(self):
        text = '<a href="https://publisher.test/articles/source.html">Source</a><a href="/about.html">About</a><img src="/assets/img/cards/example.html.jpg"><a href="unknown.html">Unknown</a>'
        self.assertEqual(normalise_text(text, {'winner'}, True), text)

    def test_related_links_only_for_existing_articles(self):
        text = '<a href="winner.html">Read</a><a href="missing.html">Missing</a>'
        self.assertEqual(normalise_text(text, {'winner'}, True), '<a href="winner">Read</a><a href="missing.html">Missing</a>')
        self.assertEqual(normalise_text(text, {'winner'}), text)

    def test_snapshot_keeps_archives_and_publication_dates_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'articles').mkdir()
            page = root / 'articles' / 'historic.html'
            page.write_text('<link rel="canonical" href="https://rochdaledaily.co.uk/articles/historic.html"><script>{"datePublished":"2026-09-28T16:04:53Z"}</script>', encoding='utf-8')
            sitemap = root / 'sitemap.xml'
            sitemap.write_text('<loc>https://rochdaledaily.co.uk/articles/historic.html</loc>', encoding='utf-8')
            self.assertEqual(normalise_snapshot(root), 2)
            self.assertTrue(page.exists())
            self.assertIn('2026-09-28T16:04:53Z', page.read_text())
            self.assertEqual(sitemap.read_text(), '<loc>https://rochdaledaily.co.uk/articles/historic</loc>')
            self.assertEqual(normalise_snapshot(root), 0)


if __name__ == '__main__':
    unittest.main()
