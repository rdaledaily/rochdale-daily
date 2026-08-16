#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import externalise_article_css as mod


class ExternaliseArticleCssTests(unittest.TestCase):
    def test_exact_shared_css_is_replaced(self):
        css = ".article{max-width:700px}\n"
        page = f"<html><head><style>{css}</style></head><body>Story</body></html>"
        updated, changed = mod.externalise_page_css(page, css)
        self.assertTrue(changed)
        self.assertIn(mod.STYLESHEET_LINK, updated)
        self.assertNotIn(f"<style>{css}</style>", updated)

    def test_unrelated_inline_css_is_not_touched(self):
        shared = ".article{max-width:700px}\n"
        page = "<html><head><style>.special{color:red}</style></head></html>"
        updated, changed = mod.externalise_page_css(page, shared)
        self.assertFalse(changed)
        self.assertEqual(updated, page)

    def test_already_external_page_is_idempotent(self):
        page = f"<html><head>{mod.STYLESHEET_LINK}</head></html>"
        updated, changed = mod.externalise_page_css(page, ".article{}\n")
        self.assertFalse(changed)
        self.assertEqual(updated, page)

    def test_directory_only_rewrites_exact_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            articles = root / "articles"
            articles.mkdir()
            css_path = root / "site.css"
            css = ".article{font-size:18px}\n"
            css_path.write_text(css, encoding="utf-8")
            (articles / "one.html").write_text(
                f"<head><style>{css}</style></head>", encoding="utf-8"
            )
            (articles / "two.html").write_text(
                "<head><style>.legacy{display:block}</style></head>", encoding="utf-8"
            )
            changed, scanned = mod.externalise_directory(articles, css_path)
            self.assertEqual(scanned, 2)
            self.assertEqual(changed, 1)
            self.assertIn(mod.STYLESHEET_LINK, (articles / "one.html").read_text(encoding="utf-8"))
            self.assertIn(".legacy", (articles / "two.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
