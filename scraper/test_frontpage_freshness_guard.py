#!/usr/bin/env python3
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from enforce_frontpage_freshness import is_recent_live_update, is_utility_not_lead


class FrontpageFreshnessGuardTests(unittest.TestCase):
    def test_machine_contact_page_is_utility(self) -> None:
        article = {
            "title": "Rochdale Borough Council Updates Contact Information for Estates and Asset Management Team",
            "source_kind": "article",
            "source_url": "https://www.rochdale.gov.uk/contact-us/estates-asset-management-team-contact-details",
        }
        self.assertTrue(is_utility_not_lead(article))

    def test_editorial_contact_story_is_not_suppressed(self) -> None:
        article = {
            "title": "Contact information changes after council service move",
            "source_kind": "editorial",
            "source_url": "https://www.rochdale.gov.uk/contact-us/service-contact-details",
        }
        self.assertFalse(is_utility_not_lead(article))

    def test_recent_live_update_can_outrank_fresh_utility(self) -> None:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=14)
        article = {
            "title": "Police appeal for missing man",
            "live_story": True,
            "first_published_at": (now - timedelta(hours=22)).isoformat(),
            "last_updated_at": (now - timedelta(minutes=20)).isoformat(),
            "source_url": "https://www.gmp.police.uk/news/appeal/",
        }
        self.assertTrue(is_recent_live_update(article, cutoff))

    def test_stale_live_story_does_not_get_promoted_forever(self) -> None:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=14)
        article = {
            "title": "Old live story",
            "live_story": True,
            "first_published_at": (now - timedelta(days=2)).isoformat(),
            "last_updated_at": (now - timedelta(hours=20)).isoformat(),
        }
        self.assertFalse(is_recent_live_update(article, cutoff))


if __name__ == "__main__":
    unittest.main()
