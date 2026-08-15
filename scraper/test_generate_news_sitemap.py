#!/usr/bin/env python3
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from generate_news_sitemap import eligible_articles, title_fingerprint


class NewsSitemapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 15, 8, 0, tzinfo=timezone.utc)

    def test_exact_headline_duplicate_prefers_manual_article(self) -> None:
        rows = [
            {
                "slug": "scraped-copy",
                "title": "Rochdale businesses urged to back Denehurst House in £30-a-month veterans challenge",
                "published_at": "2026-08-14T14:30:00Z",
                "source_kind": "news",
                "status": "published",
            },
            {
                "slug": "editorial-copy",
                "title": "Rochdale businesses urged to back Denehurst House in £30-a-month veterans challenge",
                "published_at": "2026-08-14T14:22:00Z",
                "source_kind": "editorial",
                "manual_article": True,
                "status": "published",
            },
        ]
        selected = eligible_articles(rows, self.now)
        self.assertEqual([item[1]["slug"] for item in selected], ["editorial-copy"])

    def test_distinct_headlines_are_not_fuzzily_merged(self) -> None:
        rows = [
            {
                "slug": "road-closed",
                "title": "Edenfield Road closes overnight for resurfacing works",
                "published_at": "2026-08-14T16:00:00Z",
                "status": "published",
            },
            {
                "slug": "road-reopens",
                "title": "Edenfield Road reopens early after resurfacing works",
                "published_at": "2026-08-14T18:00:00Z",
                "status": "published",
            },
        ]
        selected = eligible_articles(rows, self.now)
        self.assertEqual({item[1]["slug"] for item in selected}, {"road-closed", "road-reopens"})

    def test_first_published_at_is_used_for_google_news_date(self) -> None:
        rows = [
            {
                "slug": "live-update",
                "title": "Live local transport update for Rochdale town centre",
                "first_published_at": "2026-08-14T09:00:00Z",
                "published_at": "2026-08-15T07:30:00Z",
                "status": "published",
            }
        ]
        selected = eligible_articles(rows, self.now)
        self.assertEqual(selected[0][0].isoformat(), "2026-08-14T09:00:00+00:00")

    def test_short_generic_titles_are_not_duplicate_keys(self) -> None:
        self.assertEqual(title_fingerprint("Council update"), "")


if __name__ == "__main__":
    unittest.main()
