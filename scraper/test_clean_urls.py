#!/usr/bin/env python3
"""Internal links, canonicals and sitemaps use the address that answers 200.

Measured 19 October 2026 by the live search audit: 36 sitemap URLs and their
canonicals were .html addresses that Cloudflare answers with a 308 redirect,
20,535 internal links pointed at such addresses, and 2 sitemap entries were
pages that had been removed.

Run:  PYTHONPATH=scraper python scraper/test_clean_urls.py
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clean_urls as cu  # noqa: E402

PAGE = """<html><head><link rel="canonical" href="https://rochdaledaily.co.uk/news/crime.html">
<meta property="og:url" content="https://rochdaledaily.co.uk/news/crime.html">
<script type="application/ld+json">{"item": "https://rochdaledaily.co.uk/news/education.html", "home": "https://rochdaledaily.co.uk/index.html"}</script>
<link rel="stylesheet" href="/assets/css/site.css"></head><body>
<a class="related-story" href="council-approves-plan.html">x</a>
<a href="/articles/a-story.html#comments">y</a>
<a href="../news/index.html">sections</a>
<a href="/category.html?area=heywood">heywood</a>
<a href="https://www.rochdale.gov.uk/news/article/1/thing.html">council</a>
<a href="mailto:news@rochdaledaily.co.uk">email</a>
<a href="//cdn.example.com/x.html">cdn</a>
</body></html>"""


class CleanText(unittest.TestCase):
    def setUp(self):
        self.out = cu.clean_text(PAGE)

    def test_canonical_og_and_structured_data_use_the_clean_address(self):
        self.assertIn('rel="canonical" href="https://rochdaledaily.co.uk/news/crime"', self.out)
        self.assertIn('content="https://rochdaledaily.co.uk/news/crime"', self.out)
        self.assertIn('"item": "https://rochdaledaily.co.uk/news/education"', self.out)
        self.assertIn('"home": "https://rochdaledaily.co.uk/"', self.out)

    def test_internal_links_lose_html_and_keep_fragments_and_queries(self):
        self.assertIn('href="council-approves-plan"', self.out)
        self.assertIn('href="/articles/a-story#comments"', self.out)
        self.assertIn('href="../news/"', self.out)
        self.assertIn('href="/category?area=heywood"', self.out)

    def test_external_links_assets_and_schemes_are_untouched(self):
        self.assertIn('href="https://www.rochdale.gov.uk/news/article/1/thing.html"', self.out)
        self.assertIn('href="mailto:news@rochdaledaily.co.uk"', self.out)
        self.assertIn('href="//cdn.example.com/x.html"', self.out)
        self.assertIn('href="/assets/css/site.css"', self.out)

    def test_cleaning_twice_changes_nothing(self):
        self.assertEqual(cu.clean_text(self.out), self.out)


class Sitemaps(unittest.TestCase):
    def test_entries_for_removed_pages_are_dropped_and_the_rest_cleaned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "articles").mkdir()
            (root / "news").mkdir()
            (root / "articles" / "kept.html").write_text("x", encoding="utf-8")
            (root / "news" / "crime.html").write_text("x", encoding="utf-8")
            (root / "index.html").write_text("x", encoding="utf-8")
            xml = ("<urlset>\n<url><loc>https://rochdaledaily.co.uk/</loc></url>\n"
                   "<url><loc>https://rochdaledaily.co.uk/articles/kept</loc></url>\n"
                   "<url><loc>https://rochdaledaily.co.uk/articles/taken-down</loc></url>\n"
                   "<url><loc>https://rochdaledaily.co.uk/news/crime.html</loc></url>\n</urlset>")
            out, dropped = cu.clean_sitemap_text(xml, root)
        self.assertEqual(dropped, 1)
        self.assertNotIn("taken-down", out)
        self.assertIn("<loc>https://rochdaledaily.co.uk/news/crime</loc>", out)
        self.assertIn("<loc>https://rochdaledaily.co.uk/articles/kept</loc>", out)
        self.assertIn("<loc>https://rochdaledaily.co.uk/</loc>", out)


if __name__ == "__main__":
    unittest.main()
