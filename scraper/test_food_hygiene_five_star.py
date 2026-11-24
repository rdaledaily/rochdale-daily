"""5-out-of-5 ratings: baseline first, then one good-news story per new rating, capped per run."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import food_hygiene as fh  # noqa: E402
import scraper as core  # noqa: E402


def rec(i, rating=5, day=1):
    return {"fhrs_id": 1000 + i, "name": f"Cafe {i}", "business_type": "Restaurant/Cafe/Canteen",
            "address": "1 Yorkshire Street, Rochdale, OL16 1AA", "rating": rating,
            "rating_date": datetime(2026, 11, day, tzinfo=timezone.utc)}


class FiveStar(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "five.json"
        self.patches = [mock.patch.object(core, "FOOD_HYGIENE_FIVE_STATE_FILE", self.state),
                        mock.patch.object(core, "_food_hygiene_published_urls", lambda: set())]
        for p in self.patches:
            p.start()
        core.FOOD_HYGIENE_REPORT.clear()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_first_run_is_baseline_only(self):
        now = datetime(2026, 11, 24, 22, tzinfo=timezone.utc)
        self.assertEqual(core._five_star_candidates([rec(1), rec(2)], now), [])
        self.assertEqual(core.FOOD_HYGIENE_REPORT["five_star"]["status"], "baseline taken")

    def test_new_five_stars_published_capped_newest_first(self):
        now = datetime(2026, 11, 24, 22, tzinfo=timezone.utc)
        core._five_star_candidates([rec(1)], now)
        new = [rec(i, day=i) for i in range(2, 8)]
        with mock.patch.dict(os.environ, {"FOOD_HYGIENE_FIVE_STAR_PER_RUN": "3"}):
            out = core._five_star_candidates([rec(1)] + new, now)
        self.assertEqual(len(out), 3)
        self.assertEqual([c.source_title for c in out][0], "Cafe 7 awarded 5 out of 5 food hygiene rating")
        self.assertTrue(all(c.deterministic_draft and c.category == "business" for c in out))
        self.assertEqual(json.loads(self.state.read_text())["baseline"], [fh.rating_key(rec(1))])

    def test_story_states_only_fsa_facts(self):
        story = fh.five_star_story(rec(3, day=3), checked_at=datetime(2026, 11, 24, tzinfo=timezone.utc))
        text = " ".join(story["paragraphs"])
        self.assertIn("5 out of 5", story["title"])
        self.assertIn("3 November 2026", text)
        self.assertIn("https://ratings.food.gov.uk/business/1003", text)
        self.assertNotIn("delicious", text.lower())


if __name__ == "__main__":
    unittest.main()
