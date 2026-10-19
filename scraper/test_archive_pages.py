#!/usr/bin/env python3
"""The month archive lists every indexable story, links months together and stays out of duplicates."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import archive_pages as ap  # noqa: E402


def article(slug, canonical=None, robots="index,follow"):
    return (f'<html><head><link rel="canonical" href="https://rochdaledaily.co.uk/articles/{canonical or slug}">'
            f'<meta name="robots" content="{robots}"></head><body></body></html>')


class ArchivePagesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.root = Path(self.tmp.name)
        (root / "articles").mkdir()
        index = []
        for slug, when, html in (
            ("sept-story", "2026-09-04T10:00:00Z", article("sept-story")),
            ("oct-story", "2026-10-02T10:00:00Z", article("oct-story")),
            ("oct-copy", "2026-10-02T11:00:00Z", article("oct-copy", canonical="oct-story")),
            ("oct-hidden", "2026-10-03T11:00:00Z", article("oct-hidden", robots="noindex,follow")),
        ):
            (root / "articles" / f"{slug}.html").write_text(html)
            index.append({"slug": slug, "title": slug.replace("-", " "), "published_at": when, "category": "News"})
        index.append({"slug": "taken-down", "title": "gone", "published_at": "2026-10-05T10:00:00Z"})
        (root / "archive-index.json").write_text(json.dumps(index))
        (root / "archive.html").write_text("<html><head></head><body><main><h1>Archive</h1></main></body></html>")

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_indexable_existing_stories_are_listed(self):
        months = ap.stories_by_month(self.root)
        self.assertEqual({k: [i["slug"] for i in v] for k, v in months.items()},
                         {"2026-09": ["sept-story"], "2026-10": ["oct-story"]})

    def test_pages_link_months_and_stories(self):
        pages, stale = ap.build(self.root)
        october = pages[self.root / "news" / "archive" / "2026-10.html"]
        self.assertIn('href="/articles/oct-story"', october)
        self.assertIn('href="/news/archive/2026-09"', october)
        self.assertIn('href="/news/archive/2026-10"', pages[self.root / "news" / "archive" / "index.html"])
        archive = pages[self.root / "archive.html"]
        self.assertIn('href="/news/archive/2026-09"', archive)
        self.assertEqual(ap.with_archive_block(archive, ap.archive_block(ap.stories_by_month(self.root))), archive)
        self.assertEqual(stale, [])

    def test_month_with_no_stories_left_is_removed(self):
        (self.root / "news" / "archive").mkdir(parents=True)
        old = self.root / "news" / "archive" / "2026-06.html"
        old.write_text("x")
        _, stale = ap.build(self.root)
        self.assertEqual(stale, [old])


if __name__ == "__main__":
    unittest.main()
