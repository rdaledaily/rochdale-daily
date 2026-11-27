"""Health check judges search coverage on the full alternating rotation (27 Nov 2026).

Every fast run from 24 Nov 21:47 failed check_scraper_health.py with
"search plan missed required categories/wards", because search_plan.py
(24 Nov) runs half the rotating searches per run and groups wards into
OR-searches, while the check still expected every search in every run.
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("OPENAI_API_KEY", "")

import check_scraper_health as health  # noqa: E402
import run_fast_local_pipeline as fast  # noqa: E402
from search_queries import CATEGORY_QUERIES, ROCHDALE_WARDS  # noqa: E402


def records(specs):
    return [{"label": s.label, "query": s.query, "category": s.category, "ward": s.ward} for s in specs]


class HealthRotation(unittest.TestCase):
    def check(self, now):
        fast.configure_searches(now)
        one_run = records(fast.core.SEARCH_QUERY_SPECS)
        rotation = records(fast.core.SEARCH_PLAN_ROTATION)
        need_c = {c.lower() for c, _ in CATEGORY_QUERIES}
        need_w = set(ROCHDALE_WARDS)
        cats, wards = health.plan_coverage(rotation, need_w)
        self.assertEqual(need_c - cats, set())
        self.assertEqual(need_w - wards, set())
        # The single run really is only half: the old check would fail here.
        self.assertLess(len(one_run), len(rotation))

    def test_shard_zero(self):
        self.check(datetime(2026, 11, 27, 9, 0, tzinfo=timezone.utc))

    def test_shard_one(self):
        self.check(datetime(2026, 11, 27, 9, 20, tzinfo=timezone.utc))

    def test_real_gap_still_fails(self):
        cats, wards = health.plan_coverage(
            [{"label": "wards:1", "query": '("Bamford" OR "Norden") x', "category": "news"}],
            set(ROCHDALE_WARDS),
        )
        self.assertEqual(wards, {"Bamford", "Norden"})
        self.assertNotIn("sport", cats)


if __name__ == "__main__":
    unittest.main()
