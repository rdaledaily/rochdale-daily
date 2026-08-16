#!/usr/bin/env python3
import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import update_homepage_static_latest as latest


class StaticLatestEligibilityTests(unittest.TestCase):
    def base(self, **overrides):
        row = {
            "status": "published",
            "slug": "example-story",
            "title": "Rochdale residents face disruption after road closure",
            "published_at": datetime.now(timezone.utc).isoformat(),
            "category": "news",
            "source_kind": "article",
            "source_url": "https://example.org/news/story",
        }
        row.update(overrides)
        return row

    def test_live_departure_board_is_excluded(self):
        row = self.base(title="Live bus departures at Rochdale Interchange")
        self.assertTrue(latest.is_utility_not_news(row))
        self.assertFalse(latest.eligible(row))

    def test_department_contact_page_is_excluded(self):
        row = self.base(title="Council updates contact information for Estates and Asset Management")
        self.assertTrue(latest.is_utility_not_news(row))
        self.assertFalse(latest.eligible(row))

    def test_editorial_story_is_exempt_from_utility_heuristic(self):
        row = self.base(
            title="Council contact information failures leave residents waiting",
            source_kind="editorial",
        )
        self.assertFalse(latest.is_utility_not_news(row))
        self.assertTrue(latest.eligible(row))

    def test_normal_transport_news_remains_eligible(self):
        row = self.base(
            title="Lift at Derker Tram Stop Out of Service Until Further Notice",
            category="transport",
            source_url="https://tfgm.com/travel-updates/travel-alerts",
        )
        self.assertFalse(latest.is_utility_not_news(row))
        self.assertTrue(latest.eligible(row))

    def test_latest_story_inside_14_hour_window_is_eligible(self):
        now = datetime(2026, 8, 16, 6, 30, tzinfo=timezone.utc)
        row = self.base(
            first_published_at=(now - timedelta(hours=13, minutes=59)).isoformat(),
            published_at=(now - timedelta(hours=13, minutes=59)).isoformat(),
        )
        self.assertTrue(latest.eligible(row, now))

    def test_story_older_than_14_hours_is_not_latest(self):
        now = datetime(2026, 8, 16, 6, 30, tzinfo=timezone.utc)
        row = self.base(
            first_published_at=(now - timedelta(hours=14, minutes=1)).isoformat(),
            published_at=(now - timedelta(hours=14, minutes=1)).isoformat(),
        )
        self.assertFalse(latest.eligible(row, now))

    def test_stale_editorial_story_is_not_latest_even_if_editorial(self):
        now = datetime(2026, 8, 16, 6, 30, tzinfo=timezone.utc)
        row = self.base(
            source_kind="editorial",
            manual_article=True,
            first_published_at=(now - timedelta(hours=24)).isoformat(),
            published_at=(now - timedelta(hours=24)).isoformat(),
        )
        self.assertFalse(latest.eligible(row, now))

    def test_stale_machine_sports_preview_is_excluded(self):
        now = datetime.now(timezone.utc)
        row = self.base(
            title="Rochdale AFC faces Newport County today",
            category="sport",
            excerpt="Supporters are advised to arrive early for kick-off.",
            first_published_at=(now - timedelta(hours=9)).isoformat(),
            published_at=(now - timedelta(hours=9)).isoformat(),
        )
        self.assertTrue(latest.is_expired_time_sensitive_preview(row, now))
        self.assertFalse(latest.eligible(row, now))

    def test_recent_machine_sports_preview_remains_eligible(self):
        now = datetime.now(timezone.utc)
        row = self.base(
            title="Rochdale AFC faces Newport County today",
            category="sport",
            excerpt="A match preview ahead of this afternoon's fixture.",
            first_published_at=(now - timedelta(hours=2)).isoformat(),
            published_at=(now - timedelta(hours=2)).isoformat(),
        )
        self.assertFalse(latest.is_expired_time_sensitive_preview(row, now))
        self.assertTrue(latest.eligible(row, now))

    def test_expired_same_day_deadline_is_excluded(self):
        now = datetime(2026, 8, 15, 21, 45, tzinfo=timezone.utc)
        row = self.base(
            title="Early Bird Tickets Available for Rochdale Hornets Matches Until 6pm Today",
            category="sport",
            excerpt="Supporters can buy the discounted tickets until 6pm today.",
            published_at=datetime(2026, 8, 15, 16, 54, tzinfo=timezone.utc).isoformat(),
        )
        self.assertTrue(latest.is_expired_today_deadline(row, now))

    def test_same_day_deadline_remains_expired_after_midnight(self):
        local = ZoneInfo("Europe/London")
        published = datetime(2026, 8, 15, 16, 54, tzinfo=local).astimezone(timezone.utc)
        now = datetime(2026, 8, 16, 1, 30, tzinfo=local).astimezone(timezone.utc)
        row = self.base(
            title="Early Bird Tickets Available for Rochdale Hornets Matches Until 6pm Today",
            category="sport",
            excerpt="Supporters can buy the discounted tickets until 6pm today.",
            first_published_at=published.isoformat(),
            published_at=published.isoformat(),
        )
        self.assertTrue(latest.is_expired_today_deadline(row, now))

    def test_future_same_day_deadline_remains_eligible(self):
        now = datetime(2026, 8, 15, 15, 0, tzinfo=timezone.utc)
        row = self.base(
            title="Early Bird Tickets Available Until 6pm Today",
            category="sport",
            published_at=datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc).isoformat(),
        )
        self.assertFalse(latest.is_expired_today_deadline(row, now))

    def test_editorial_deadline_story_is_exempt(self):
        now = datetime(2026, 8, 15, 21, 45, tzinfo=timezone.utc)
        row = self.base(
            title="Council consultation closes at 6pm today after residents raise concerns",
            source_kind="editorial",
        )
        self.assertFalse(latest.is_expired_today_deadline(row, now))

    def test_inline_masthead_logo_is_externalised(self):
        html = (
            '<a class="brand"><img class="brand-logo" '
            'src="data:image/png;base64,AAAAABBBBB" alt="Rochdale Daily"></a>'
        )
        updated = latest.externalise_inline_masthead_logo(html)
        self.assertIn('src="/assets/img/logo.png"', updated)
        self.assertNotIn('data:image/png;base64', updated)
        self.assertIn('alt="Rochdale Daily"', updated)

    def test_existing_static_masthead_logo_is_unchanged(self):
        html = '<img class="brand-logo" src="/assets/img/logo.png" alt="Rochdale Daily">'
        self.assertEqual(latest.externalise_inline_masthead_logo(html), html)


if __name__ == "__main__":
    unittest.main()
