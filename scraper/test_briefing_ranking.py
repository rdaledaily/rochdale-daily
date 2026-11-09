#!/usr/bin/env python3
"""Morning Briefing: no traffic notices, the whole day since the last briefing,
and the big story first (9 November 2026).

On 9 Nov the briefing window still started at 6pm (left over from the retired
Evening Wrap-Up), so every Remembrance Sunday story published that day was in
no briefing at all, and two overnight roadworks notices sat in the list instead.
"""
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import daily_briefing as db  # noqa: E402


def story(slug, title, category, published, body_words=250):
    return {
        "id": slug, "slug": slug, "title": title, "category": category,
        "status": "published", "published_at": published, "first_published_at": published,
        "excerpt": f"{title}.", "body": "word " * body_words, "area": "rochdale",
    }


STORIES = [
    story("remembrance-parades", "Remembrance Sunday: parades at eight war memorials", "news", "2026-11-08T10:38:00Z"),
    story("remembrance-castleton", "Castleton Remembrance Sunday service draws big crowd", "community", "2026-11-08T11:28:00Z"),
    story("remembrance-mp", "MP attends Middleton Remembrance service", "politics", "2026-11-08T19:50:00Z"),
    story("breakfast-club", "Veterans breakfast club receives donation", "community", "2026-11-08T21:54:00Z", 120),
    story("salons", "The best beauty salons ranked", "business", "2026-11-08T20:58:00Z", 150),
    story("schofield-street", "Part of Schofield Street in Heywood to close for roadworks", "traffic", "2026-11-09T03:21:00Z"),
    story("roadworks-various", "Roadworks to begin on various streets", "traffic", "2026-11-09T03:21:00Z"),
    story("mislabelled", "Temporary traffic lights on Edenfield Road", "news", "2026-11-09T04:00:00Z"),
    story("too-old", "Yesterday morning's story", "news", "2026-11-08T08:30:00Z"),
]


class BriefingRankingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name) / "articles.json"
        path.write_text(json.dumps(STORIES), encoding="utf-8")
        self._articles = db.ARTICLES
        db.ARTICLES = path
        self.entry = db.build("morning", datetime(2026, 11, 9, 9, 5, tzinfo=db.LONDON))
        self.html = self.entry["content_html"]

    def tearDown(self):
        db.ARTICLES = self._articles
        self.tmp.cleanup()

    def test_traffic_notices_never_listed(self):
        for slug in ("schofield-street", "roadworks-various", "mislabelled"):
            self.assertNotIn(slug, self.html)

    def test_window_covers_the_day_since_the_last_briefing(self):
        self.assertIn("remembrance-parades", self.html)       # 10:38 yesterday
        self.assertIn("remembrance-castleton", self.html)     # 11:28 yesterday
        self.assertNotIn("too-old", self.html)                # before 9am yesterday
        self.assertIn("5 new stories", self.html)
        self.assertIn("since yesterday morning", self.html)

    def test_big_story_leads_small_late_items(self):
        order = [self.html.index(slug) for slug in
                 ("remembrance-parades", "remembrance-mp", "remembrance-castleton", "breakfast-club", "salons")]
        self.assertEqual(order, sorted(order))

    def test_ordinary_closures_are_not_traffic(self):
        for title in ("Rochdale shop to close after 40 years", "School closure consultation opens"):
            self.assertFalse(db.is_traffic_notice({"title": title, "category": "news"}), title)


if __name__ == "__main__":
    unittest.main()
