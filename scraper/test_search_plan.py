"""Google News search plan: merged, rotated, nothing that found stories dropped."""
from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import search_plan  # noqa: E402


@dataclass(frozen=True)
class Q:
    label: str
    query: str
    category: str = "news"
    ward: str = ""


def make(label, query, category):
    return Q(label, query, category)


WARDS = [f"Ward {i}" for i in range(20)]
SPECS = (
    [Q("category:crime", "c"), Q("category:sport", "s"), Q("category:events", "e")]
    + [Q(f"ward:{w}", f'"{w}" x', ward=w) for w in WARDS]
    + [Q("source:manchester-evening-news", "m"), Q("fallback:men-rochdale-today", "m2")]
    + [Q(l, "p") for l in search_plan.PARTY_LABELS]
    + [Q("priority:reform-rochdale-local", "r"), Q("priority:crime-fast", "g"), Q("official-gmp:1", "g1"),
       Q("fallback:rochdale-council-today", "rc")]
)
T0 = datetime(2026, 11, 24, 21, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 11, 24, 21, 20, tzinfo=timezone.utc)


class SearchPlan(unittest.TestCase):
    def both(self):
        return search_plan.plan(SPECS, make, T0), search_plan.plan(SPECS, make, T1)

    def test_every_useful_search_runs_within_two_slots(self):
        a, b = self.both()
        labels = {s.label for s in a} | {s.label for s in b}
        for needed in ("category:crime", "category:sport", "category:events", "source:manchester-evening-news",
                       "priority:reform-rochdale-local", "parties:sites", "official:sites"):
            self.assertIn(needed, labels)
        self.assertEqual({l for l in labels if l.startswith("wards:")}, {"wards:1", "wards:2", "wards:3", "wards:4"})

    def test_merged_away_and_duplicate_searches_gone(self):
        a, b = self.both()
        labels = {s.label for s in a + b}
        self.assertFalse(any(l.startswith("ward:") for l in labels))
        self.assertNotIn("fallback:men-rochdale-today", labels)
        for l in search_plan.PARTY_LABELS:
            self.assertNotIn(l, labels)
        self.assertNotIn("official-gmp:1", labels)

    def test_breaking_searches_every_run_and_volume_down(self):
        a, b = self.both()
        for plan in (a, b):
            self.assertIn("category:crime", {s.label for s in plan})
            self.assertIn("official:sites", {s.label for s in plan})
            self.assertLess(len(plan), len(SPECS) / 2)

    def test_ward_groups_quote_every_ward(self):
        a, b = self.both()
        text = " ".join(s.query for s in a + b if s.label.startswith("wards:"))
        for w in WARDS:
            self.assertIn(f'"{w}"', text)


if __name__ == "__main__":
    unittest.main()
