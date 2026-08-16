#!/usr/bin/env python3
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from enforce_frontpage_freshness import (
    is_expired_time_sensitive_preview,
    is_expired_today_deadline,
    is_recent_live_update,
    is_thin_utility_not_frontpage,
    is_utility_not_lead,
    latest_verified_update,
)


class FrontpageFreshnessGuardTests(unittest.TestCase):
    def test_machine_contact_page_is_utility(self) -> None:
        article = {
            "title": "Rochdale Borough Council Updates Contact Information for Estates and Asset Management Team",
            "source_kind": "article",
            "source_url": "https://www.rochdale.gov.uk/contact-us/estates-asset-management-team-contact-details",
        }
        self.assertTrue(is_utility_not_lead(article))
        self.assertTrue(is_thin_utility_not_frontpage(article))

    def test_editorial_contact_story_is_not_suppressed(self) -> None:
        article = {
            "title": "Contact information changes after council service move",
            "source_kind": "editorial",
            "source_url": "https://www.rochdale.gov.uk/contact-us/service-contact-details",
        }
        self.assertFalse(is_utility_not_lead(article))
        self.assertFalse(is_thin_utility_not_frontpage(article))

    def test_real_service_change_story_is_not_treated_as_thin_contact_rewrite(self) -> None:
        article = {
            "title": "Council moves homelessness advice service to new town-centre office",
            "source_kind": "article",
            "source_url": "https://www.rochdale.gov.uk/news/service-moves-to-new-office",
            "excerpt": "The service will operate from a new location from Monday, with revised opening hours.",
        }
        self.assertFalse(is_thin_utility_not_frontpage(article))

    def test_recent_live_update_can_outrank_fresh_utility(self) -> None:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=14)
        verified = now - timedelta(minutes=20)
        article = {
            "title": "Police appeal for missing man",
            "live_story": True,
            "first_published_at": (now - timedelta(hours=22)).isoformat(),
            "last_updated_at": verified.isoformat(),
            "live_updates": [{"timestamp": verified.isoformat(), "text": "Police issued a new appeal."}],
            "source_url": "https://www.gmp.police.uk/news/appeal/",
        }
        self.assertTrue(is_recent_live_update(article, cutoff))

    def test_scrape_timestamp_does_not_resurrect_old_machine_live_story(self) -> None:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=14)
        original = now - timedelta(days=2)
        article = {
            "title": "Old automated breaking story",
            "live_story": True,
            "breaking_news": True,
            "source_kind": "aggregator_discovered_article",
            "first_published_at": original.isoformat(),
            "last_updated_at": (now - timedelta(minutes=5)).isoformat(),
            "scraped_at": (now - timedelta(minutes=2)).isoformat(),
            "live_updates": [{"timestamp": original.isoformat(), "text": "Original update only."}],
        }
        self.assertEqual(latest_verified_update(article), original)
        self.assertFalse(is_recent_live_update(article, cutoff))

    def test_editorial_live_story_may_use_explicit_last_updated_at(self) -> None:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=14)
        article = {
            "title": "Live council meeting",
            "live_story": True,
            "source_kind": "editorial",
            "manual_article": True,
            "first_published_at": (now - timedelta(days=1)).isoformat(),
            "last_updated_at": (now - timedelta(minutes=10)).isoformat(),
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

    def test_machine_sports_preview_expires_after_eight_hours(self) -> None:
        now = datetime.now(timezone.utc)
        article = {
            "title": "Rochdale AFC faces Newport County today",
            "excerpt": "Supporters are advised to arrive early for kick-off.",
            "category": "sport",
            "source_kind": "article",
            "first_published_at": (now - timedelta(hours=9)).isoformat(),
        }
        self.assertTrue(is_expired_time_sensitive_preview(article, now))

    def test_recent_machine_sports_preview_is_retained(self) -> None:
        now = datetime.now(timezone.utc)
        article = {
            "title": "Rochdale AFC faces Newport County today",
            "excerpt": "A match preview ahead of this afternoon's fixture.",
            "category": "sport",
            "source_kind": "article",
            "first_published_at": (now - timedelta(hours=2)).isoformat(),
        }
        self.assertFalse(is_expired_time_sensitive_preview(article, now))

    def test_editorial_sports_story_is_never_auto_expired(self) -> None:
        now = datetime.now(timezone.utc)
        article = {
            "title": "What today's Rochdale AFC fixture means for supporters",
            "category": "sport",
            "source_kind": "editorial",
            "manual_article": True,
            "first_published_at": (now - timedelta(hours=12)).isoformat(),
        }
        self.assertFalse(is_expired_time_sensitive_preview(article, now))

    def test_event_time_expires_preview_three_hours_after_start(self) -> None:
        now = datetime.now(timezone.utc)
        article = {
            "title": "Rochdale AFC match preview today",
            "category": "sport",
            "source_kind": "article",
            "first_published_at": (now - timedelta(hours=2)).isoformat(),
            "event_start_at": (now - timedelta(hours=4)).isoformat(),
        }
        self.assertTrue(is_expired_time_sensitive_preview(article, now))

    def test_machine_same_day_deadline_expires_after_local_deadline(self) -> None:
        local = ZoneInfo("Europe/London")
        now = datetime(2026, 8, 15, 19, 5, tzinfo=local).astimezone(timezone.utc)
        article = {
            "title": "Early Bird Tickets Available for Rochdale Hornets Matches Until 6pm Today",
            "excerpt": "Supporters have until 6pm today to buy discounted tickets.",
            "source_kind": "article",
        }
        self.assertTrue(is_expired_today_deadline(article, now))

    def test_machine_same_day_deadline_stays_expired_after_midnight(self) -> None:
        local = ZoneInfo("Europe/London")
        published = datetime(2026, 8, 15, 16, 54, tzinfo=local).astimezone(timezone.utc)
        now = datetime(2026, 8, 16, 1, 30, tzinfo=local).astimezone(timezone.utc)
        article = {
            "title": "Early Bird Tickets Available for Rochdale Hornets Matches Until 6pm Today",
            "excerpt": "Supporters have until 6pm today to buy discounted tickets.",
            "source_kind": "article",
            "first_published_at": published.isoformat(),
        }
        self.assertTrue(is_expired_today_deadline(article, now))

    def test_machine_same_day_deadline_is_retained_before_local_deadline(self) -> None:
        local = ZoneInfo("Europe/London")
        now = datetime(2026, 8, 15, 17, 30, tzinfo=local).astimezone(timezone.utc)
        article = {
            "title": "Early Bird Tickets Available for Rochdale Hornets Matches Until 6pm Today",
            "excerpt": "Supporters have until 6pm today to buy discounted tickets.",
            "source_kind": "article",
        }
        self.assertFalse(is_expired_today_deadline(article, now))

    def test_editorial_same_day_deadline_story_is_not_auto_expired(self) -> None:
        local = ZoneInfo("Europe/London")
        now = datetime(2026, 8, 15, 21, 0, tzinfo=local).astimezone(timezone.utc)
        article = {
            "title": "Council consultation closes at 6pm today",
            "excerpt": "Our explainer covers what happens after the deadline.",
            "source_kind": "editorial",
            "manual_article": True,
        }
        self.assertFalse(is_expired_today_deadline(article, now))


if __name__ == "__main__":
    unittest.main()
