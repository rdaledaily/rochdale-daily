#!/usr/bin/env python3
from __future__ import annotations

import unittest
from datetime import datetime, timezone

import add_article_time_metadata as timing


class ArticleTimeMetadataTests(unittest.TestCase):
    def test_published_time_is_visible_and_semantic(self) -> None:
        article = {
            "slug": "test-story",
            "status": "published",
            "first_published_at": "2026-08-16T03:12:00Z",
            "title": "Test story",
        }
        markup = timing.metadata_markup(article)
        self.assertIn('datetime="2026-08-16T03:12:00Z"', markup)
        self.assertIn("Published 16 August 2026 at 04:12", markup)
        self.assertNotIn("Updated", markup)

    def test_routine_scrape_timestamp_is_not_shown_as_update(self) -> None:
        article = {
            "slug": "automated-story",
            "status": "published",
            "first_published_at": "2026-08-16T03:12:00Z",
            "last_updated_at": "2026-08-16T04:30:00Z",
            "scraped_at": "2026-08-16T04:31:00Z",
            "source_kind": "article",
        }
        markup = timing.metadata_markup(article)
        self.assertNotIn("Updated", markup)

    def test_verified_live_update_is_shown(self) -> None:
        article = {
            "slug": "live-story",
            "status": "published",
            "first_published_at": "2026-08-16T03:12:00Z",
            "live_story": True,
            "last_updated_at": "2026-08-16T04:40:00Z",
            "live_updates": [
                {"timestamp": "2026-08-16T03:12:00Z", "text": "Original report."},
                {"timestamp": "2026-08-16T04:25:00Z", "text": "Verified new development."},
            ],
        }
        markup = timing.metadata_markup(article)
        self.assertIn("Updated 16 August 2026 at 05:25", markup)
        self.assertNotIn("05:40", markup)

    def test_editorial_last_updated_time_is_allowed(self) -> None:
        article = {
            "slug": "manual-story",
            "status": "published",
            "first_published_at": "2026-08-16T03:12:00Z",
            "last_updated_at": "2026-08-16T04:10:00Z",
            "manual_article": True,
            "source_kind": "editorial",
        }
        published = timing.first_published(article)
        self.assertIsNotNone(published)
        self.assertEqual(
            timing.meaningful_update(article, published),
            datetime(2026, 8, 16, 4, 10, tzinfo=timezone.utc),
        )

    def test_injection_is_idempotent(self) -> None:
        article = {
            "slug": "test-story",
            "status": "published",
            "first_published_at": "2026-08-16T03:12:00Z",
        }
        page = '<div class="article-byline">By Rochdale Daily Newsdesk</div><p>Body</p>'
        once, changed = timing.inject(page, article)
        self.assertTrue(changed)
        twice, changed_again = timing.inject(once, article)
        self.assertFalse(changed_again)
        self.assertEqual(once, twice)
        self.assertEqual(once.count(timing.START), 1)


if __name__ == "__main__":
    unittest.main()
