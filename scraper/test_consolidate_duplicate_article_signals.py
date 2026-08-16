#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from consolidate_duplicate_article_signals import apply, find_duplicates


class DuplicateSeoTests(unittest.TestCase):
    def article(self, **overrides):
        row = {
            "status": "published",
            "category": "transport",
            "source_url": "https://tfgm.com/travel-updates/travel-alerts?active_tab=tram",
            "publication_route": "ai-grounded-rewrite",
            "source_kind": "live",
            "byline": "Rochdale Daily Newsdesk",
            "published_at": "2026-08-16T10:00:00Z",
            "first_published_at": "2026-08-16T10:00:00Z",
        }
        row.update(overrides)
        return row

    def test_similar_same_source_articles_consolidate_to_oldest(self):
        articles = [
            self.article(slug="rochdale-line-works", title="Service Changes on Rochdale Line Due to Planned Works"),
            self.article(slug="rochdale-line-works-until-28-august", title="Service Changes on Rochdale Line Due to Planned Works Until 28 August", first_published_at="2026-08-16T11:00:00Z"),
        ]
        found = find_duplicates(articles)
        self.assertEqual([(x.duplicate_slug, x.canonical_slug) for x in found], [("rochdale-line-works-until-28-august", "rochdale-line-works")])

    def test_distinct_alerts_on_same_source_are_not_collapsed(self):
        articles = [
            self.article(slug="rochdale-line-works", title="Service Changes on Rochdale Line Due to Planned Works"),
            self.article(slug="derker-lift", title="Lift at Derker Tram Stop Out of Service Until Further Notice"),
        ]
        self.assertEqual(find_duplicates(articles), [])

    def test_manual_story_wins_over_automated_copy(self):
        articles = [
            self.article(slug="auto-copy", title="Rochdale Line Service Changes During Planned Works", first_published_at="2026-08-16T09:00:00Z"),
            self.article(slug="editorial", title="Rochdale Line Service Changes During Planned Works", source_kind="manual", publication_route="manual", byline="Rochdale Daily", first_published_at="2026-08-16T12:00:00Z"),
        ]
        found = find_duplicates(articles)
        self.assertEqual([(x.duplicate_slug, x.canonical_slug) for x in found], [("auto-copy", "editorial")])

    def test_two_manual_articles_are_never_auto_collapsed(self):
        articles = [
            self.article(slug="one", title="Rochdale Line Service Changes During Planned Works", source_kind="manual", publication_route="manual"),
            self.article(slug="two", title="Rochdale Line Service Changes During Planned Works Until Friday", source_kind="editorial", publication_route="editorial"),
        ]
        self.assertEqual(find_duplicates(articles), [])

    def test_apply_rewrites_canonical_and_removes_duplicate_from_sitemap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "articles").mkdir()
            articles = [
                self.article(slug="winner", title="Service Changes on Rochdale Line Due to Planned Works"),
                self.article(slug="duplicate", title="Service Changes on Rochdale Line Due to Planned Works Until 28 August", first_published_at="2026-08-16T11:00:00Z"),
            ]
            articles_path = root / "articles.json"
            articles_path.write_text(json.dumps(articles), encoding="utf-8")
            (root / "articles" / "duplicate.html").write_text(
                '<html><head><link rel="canonical" href="https://rochdaledaily.co.uk/articles/duplicate.html"></head></html>',
                encoding="utf-8",
            )
            sitemap = root / "sitemap.xml"
            sitemap.write_text(
                '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                '<url><loc>https://rochdaledaily.co.uk/articles/winner.html</loc></url>'
                '<url><loc>https://rochdaledaily.co.uk/articles/duplicate.html</loc></url>'
                '</urlset>',
                encoding="utf-8",
            )
            pages, removed = apply(articles_path, sitemap, root)
            self.assertEqual((pages, removed), (1, 1))
            duplicate_html = (root / "articles" / "duplicate.html").read_text(encoding="utf-8")
            self.assertIn('href="https://rochdaledaily.co.uk/articles/winner.html"', duplicate_html)
            self.assertNotIn('/articles/duplicate.html</loc>', sitemap.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
