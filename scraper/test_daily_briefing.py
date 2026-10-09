#!/usr/bin/env python3
"""The Morning Briefing publishes when the scheduler is late, and lists news only.

Measured 9 October 2026: GitHub started all 34 scheduled briefing runs between
12:04 and 19:27 UTC. The gate wanted the London hour to be exactly 9, so none
of them published anything. The fast news lane now starts the briefing once it
is due, and the gate is a 9am-to-noon window.

Run:  PYTHONPATH=scraper python scraper/test_daily_briefing.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import daily_briefing as briefing  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


def london(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, 9, hour, minute, tzinfo=briefing.LONDON)


def story(slug: str, when: datetime, **extra) -> dict:
    stamp = when.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    row = {"id": slug, "slug": slug, "title": slug.replace("-", " ").title(), "status": "published",
           "category": "news", "area": "rochdale", "excerpt": "Summary.", "first_published_at": stamp}
    row.update(extra)
    return row


class DueWindow(unittest.TestCase):
    def test_due_from_nine_until_noon_london_time(self) -> None:
        self.assertFalse(briefing.is_due("morning", london(8, 59)))
        self.assertTrue(briefing.is_due("morning", london(9, 0)))
        self.assertTrue(briefing.is_due("morning", london(11, 59)), "a late scheduler must still publish")
        self.assertFalse(briefing.is_due("morning", london(12, 0)), "an afternoon 'morning briefing' is not published")
        self.assertFalse(briefing.is_due("morning", london(16, 9)), "when GitHub actually ran it on 9 October")


class Contents(unittest.TestCase):
    def build(self, rows: list[dict]) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            feed = Path(tmp) / "articles.json"
            feed.write_text(json.dumps(rows), encoding="utf-8")
            with mock.patch.object(briefing, "ARTICLES", feed):
                return briefing.build("morning", london(9, 5))

    def test_sponsored_articles_are_not_listed_as_stories(self) -> None:
        last_night = london(9, 5) - timedelta(hours=11)
        article = self.build([
            story("council-approves-plan", last_night),
            story("sponsored-example-plumber", last_night, sponsored=True, title="Sponsored: Example Plumber"),
        ])
        self.assertIn("council-approves-plan", article["content_html"])
        self.assertNotIn("sponsored-example-plumber", article["content_html"])
        self.assertTrue(article["excerpt"].startswith("1 new story"), article["excerpt"])

    def test_quiet_night_does_not_fall_back_to_adverts(self) -> None:
        old = london(9, 5) - timedelta(days=3)
        article = self.build([story("sponsored-example-plumber", old, sponsored=True), story("older-news", old)])
        self.assertIn("quiet night", article["content_html"])
        self.assertIn("older-news", article["content_html"])
        self.assertNotIn("sponsored-example-plumber", article["content_html"])


class FastLaneIsTheClock(unittest.TestCase):
    def test_fast_lane_starts_the_briefing_and_deep_lane_restarts_the_fast_lane(self) -> None:
        workflow = (REPO / ".github" / "workflows" / "scrape-fast.yml").read_text(encoding="utf-8")
        fast, deep = workflow.split("\n  deep-browser:", 1)
        self.assertIn("daily_briefing.py --slot morning --check-due", fast)
        self.assertIn("gh workflow run daily-briefing.yml --ref main", fast)
        self.assertIn("gh workflow run scrape-fast.yml --ref main -f chain=1", deep,
                      "17 of 21 idle gaps began when a deep run ended and nothing restarted the chain")

    def test_check_due_reports_without_writing_a_file(self) -> None:
        before = set(REPO.glob("pending_manual_briefing_*.json"))
        with mock.patch.object(sys, "argv", ["daily_briefing.py", "--slot", "morning", "--check-due"]):
            try:
                briefing.main()
            except SystemExit as stop:
                self.assertEqual(stop.code, 3)
        self.assertEqual(set(REPO.glob("pending_manual_briefing_*.json")), before)


if __name__ == "__main__":
    unittest.main()
