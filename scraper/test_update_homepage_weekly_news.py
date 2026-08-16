#!/usr/bin/env python3
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from update_homepage_weekly_news import START, END, choose_weekly, update_html


NOW = datetime(2026, 8, 16, 6, 0, tzinfo=timezone.utc)


def row(slug: str, hours_old: int, area: str = "rochdale", category: str = "news", **extra):
    published = NOW - timedelta(hours=hours_old)
    payload = {
        "slug": slug,
        "title": slug.replace("-", " ").title(),
        "status": "published",
        "published_at": published.isoformat().replace("+00:00", "Z"),
        "first_published_at": published.isoformat().replace("+00:00", "Z"),
        "area": area,
        "category": category,
        "excerpt": "Useful local reporting.",
    }
    payload.update(extra)
    return payload


class WeeklySelectionTests(unittest.TestCase):
    def test_excludes_current_frontpage_and_older_than_week(self):
        rows = [
            row("current", 2),
            row("recent", 20),
            row("old", 24 * 8),
        ]
        chosen = choose_weekly(rows, {"current"}, now=NOW)
        self.assertEqual([item["slug"] for item in chosen], ["recent"])

    def test_prefers_editorial_and_keeps_variety(self):
        rows = [
            row("manual", 30, area="heywood", category="community", manual_article=True, source_kind="editorial"),
            row("traffic-a", 18, area="rochdale", category="traffic"),
            row("traffic-b", 19, area="rochdale", category="traffic"),
            row("traffic-c", 20, area="rochdale", category="traffic"),
            row("sport", 21, area="middleton", category="sport"),
            row("business", 22, area="pennines", category="business"),
        ]
        chosen = choose_weekly(rows, set(), now=NOW)
        slugs = [item["slug"] for item in chosen]
        self.assertEqual(slugs[0], "manual")
        self.assertIn("sport", slugs)
        self.assertIn("business", slugs)

    def test_utility_endpoint_is_excluded(self):
        utility = row("live-bus", 18, title="Live bus departures from Rochdale interchange")
        normal = row("normal-story", 19)
        chosen = choose_weekly([utility, normal], set(), now=NOW)
        self.assertEqual([item["slug"] for item in chosen], ["normal-story"])


class WeeklyMarkupTests(unittest.TestCase):
    def test_inserts_before_ward_section_and_is_idempotent(self):
        html = '<main>\n      <section class="section" id="news-by-ward" aria-labelledby="news-by-ward-title"></section>\n</main>'
        rows = [row("recent", 20)]
        updated, changed = update_html(html, rows)
        self.assertTrue(changed)
        self.assertIn(START, updated)
        self.assertIn(END, updated)
        self.assertLess(updated.index(START), updated.index('id="news-by-ward"'))

        again, changed_again = update_html(updated, rows)
        self.assertFalse(changed_again)
        self.assertEqual(updated, again)

    def test_removes_section_when_no_weekly_rows_exist(self):
        html = f"before\n{START}\n<section>old</section>\n{END}\nafter"
        updated, changed = update_html(html, [])
        self.assertTrue(changed)
        self.assertNotIn(START, updated)
        self.assertNotIn(END, updated)
        self.assertIn("before", updated)
        self.assertIn("after", updated)


if __name__ == "__main__":
    unittest.main()
