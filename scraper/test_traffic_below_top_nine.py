#!/usr/bin/env python3
"""Roadworks and road-closure notices never take a top-nine homepage spot
(editor's rule, 9 Nov 2026).

Measured 9 Nov 2026: two 03:21 roadworks notices were positions 1 and 2 on the
front page over seven Remembrance Sunday stories. They stay published, in the
traffic section and below the top nine.

Run:  PYTHONPATH=scraper python scraper/test_traffic_below_top_nine.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_scraper_health import can_lead_homepage  # noqa: E402
from ensure_manual_frontpage import demote_sponsored  # noqa: E402
from feature_policy import is_traffic_notice  # noqa: E402


def row(slug, title, category="news"):
    return {"id": slug, "slug": slug, "title": title, "category": category}


class TrafficBelowTopNine(unittest.TestCase):
    def test_roadworks_held_below_the_top_nine(self):
        rows = [
            row("schofield", "Part of Schofield Street in Heywood to close for roadworks", "traffic"),
            row("various", "Roadworks to begin on various streets in Rochdale", "traffic"),
        ] + [row(f"story-{i}", f"Story {i}") for i in range(12)]
        ordered = [r["slug"] for r in demote_sponsored(rows)]
        self.assertEqual(ordered[:9], [f"story-{i}" for i in range(9)])
        self.assertEqual(ordered[9:11], ["schofield", "various"])
        self.assertEqual(len(ordered), len(rows), "nothing is dropped from the feed")

    def test_headline_catches_mislabelled_notices(self):
        self.assertTrue(is_traffic_notice(row("x", "Temporary traffic lights on Edenfield Road")))
        self.assertTrue(is_traffic_notice(row("y", "Road closures announced for Heywood Christmas Festival", "events")))

    def test_real_news_about_closures_is_not_traffic(self):
        for title in ("Bridge Street in Heywood closed over building safety concerns",
                      "Rochdale shop to close after 40 years",
                      "School closure consultation opens"):
            self.assertFalse(is_traffic_notice(row("z", title)), title)

    def test_fresh_roadworks_outside_top_three_is_not_a_health_failure(self):
        self.assertFalse(can_lead_homepage(row("schofield", "Roadworks on Schofield Street", "traffic")))
        self.assertTrue(can_lead_homepage(row("remembrance", "Remembrance Sunday parades")))


if __name__ == "__main__":
    unittest.main()
