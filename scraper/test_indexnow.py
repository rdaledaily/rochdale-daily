#!/usr/bin/env python3
"""IndexNow submits only pages that changed, never images, and only with a valid key file."""
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import indexnow as ix  # noqa: E402

MAP = """<urlset>
<url><loc>https://rochdaledaily.co.uk/</loc><lastmod>2026-10-19T22:00:00Z</lastmod></url>
<url><loc>https://rochdaledaily.co.uk/archive</loc></url>
<url><loc>https://rochdaledaily.co.uk/articles/old</loc><lastmod>2026-01-01</lastmod></url>
<url><loc>https://rochdaledaily.co.uk/assets/a.jpg</loc><lastmod>2026-10-19T23:00:00Z</lastmod></url>
</urlset>"""
NEWS = """<urlset><url><loc>https://rochdaledaily.co.uk/articles/new</loc>
<news:news><news:publication_date>2026-10-19T23:30:00Z</news:publication_date></news:news></url></urlset>"""


class IndexNowTests(unittest.TestCase):
    def test_only_changed_pages_newest_first(self):
        since = datetime(2026, 10, 19, 21, 0, tzinfo=timezone.utc)
        self.assertEqual(ix.changed_urls([MAP, NEWS], since),
                         ["https://rochdaledaily.co.uk/articles/new", "https://rochdaledaily.co.uk/"])

    def test_all_includes_undated_pages_but_never_images(self):
        urls = ix.changed_urls([MAP, NEWS], None)
        self.assertEqual(len(urls), 4)
        self.assertNotIn("https://rochdaledaily.co.uk/assets/a.jpg", urls)

    def test_key_file_must_contain_its_own_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "robots.txt").write_text("User-agent: *")
            self.assertIsNone(ix.find_key(root))
            key = "0123456789abcdef0123456789abcdef"
            (root / f"{key}.txt").write_text("wrong")
            self.assertIsNone(ix.find_key(root))
            (root / f"{key}.txt").write_text(key)
            self.assertEqual(ix.find_key(root), key)

    def test_repository_has_a_key(self):
        self.assertIsNotNone(ix.find_key())


if __name__ == "__main__":
    unittest.main()
