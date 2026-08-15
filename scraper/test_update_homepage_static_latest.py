#!/usr/bin/env python3
import unittest

import update_homepage_static_latest as latest


class StaticLatestEligibilityTests(unittest.TestCase):
    def base(self, **overrides):
        row = {
            "status": "published",
            "slug": "example-story",
            "title": "Rochdale residents face disruption after road closure",
            "published_at": "2026-08-15T12:00:00Z",
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
