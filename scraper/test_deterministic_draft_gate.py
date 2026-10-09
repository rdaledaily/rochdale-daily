#!/usr/bin/env python3
"""A deterministic draft is not judged by the gate built for model rewrites.

Measured 9 October 2026: the October food hygiene roundup (65 businesses) was
rejected three times with "Remove unsupported calendar year(s) 2025" and then
held for the month. The years were the FSA's own inspection dates. The gate
compares a rewrite with its source text, and the roundup's only "source text"
is a 900-character summary of itself.

Run:  PYTHONPATH=scraper python scraper/test_deterministic_draft_gate.py
"""
from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scraper as core  # noqa: E402
from food_hygiene import roundup_paragraphs  # noqa: E402

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)


def roundup_candidate(count: int = 65) -> core.Candidate:
    records = [{
        "fhrs_id": 1000 + i,
        "name": f"Example Takeaway {i}",
        "rating": i % 2,
        "rating_date": NOW - timedelta(days=20 + i * 9),   # reaches back into 2025
        "address": f"{i + 1} Drake Street, Rochdale, OL16 1PA",
        "business_type": "Takeaway/sandwich shop",
        "url": f"https://ratings.food.gov.uk/business/{1000 + i}",
    } for i in range(count)]
    detailed = roundup_paragraphs(records, now=NOW)
    return core.Candidate(
        source_name="Food Standards Agency",
        source_url="https://ratings.food.gov.uk/open-data#rochdale-2026-10",
        source_title=detailed["title"][:160],
        source_summary=detailed["summary"][:900],
        source_published_at=core.iso_utc(NOW),
        area="rochdale",
        category="health",
        source_body_excerpt=detailed["summary"][:900],
        source_kind="food_hygiene_roundup",
        deterministic_draft={
            "title": detailed["title"],
            "excerpt": detailed["summary"],
            "paragraphs": detailed["paragraphs"],
        },
    )


def rewrite(candidate: core.Candidate):
    reasons: list[str] = []
    core._REWRITE_SKIP_CAPTURE.reasons = reasons
    try:
        with mock.patch.object(core, "enrich_source_records", lambda records: records), \
                mock.patch.object(core, "is_disallowed_image_source", lambda url: True):
            article = core.rewrite_candidate(candidate, None)
    finally:
        core._REWRITE_SKIP_CAPTURE.reasons = None
    return article, reasons


class DeterministicDraftGate(unittest.TestCase):
    def test_roundup_with_last_years_inspection_dates_is_published_whole(self) -> None:
        candidate = roundup_candidate()
        years = {y for p in candidate.deterministic_draft["paragraphs"] for y in ("2025", "2026") if y in p}
        self.assertEqual(years, {"2025", "2026"}, "the fixture must reproduce the rejected case")
        article, reasons = rewrite(candidate)
        self.assertEqual(reasons, [])
        self.assertIsNotNone(article)
        text = json.dumps(article)
        missing = [i for i in range(65) if f"Example Takeaway {i} " not in text and f"Example Takeaway {i}," not in text]
        self.assertEqual(missing, [], "every business must survive, none dropped or cut")

    def test_roundup_keeps_the_collectors_category(self) -> None:
        article, _ = rewrite(roundup_candidate(6))
        self.assertEqual(article["category"], "health")

    def test_the_gate_itself_still_rejects_an_invented_year_in_a_rewrite(self) -> None:
        draft = {"publishable": True, "title": "Road to close in Rochdale",
                 "excerpt": "A road will close.",
                 "paragraphs": ["Drake Street in Rochdale will close for resurfacing in March 2019, the council said."]}
        source = "Rochdale Borough Council said Drake Street in Rochdale will close for resurfacing next month."
        issues = core.editorial_quality_issues(draft, source, "")
        self.assertTrue(any("unsupported calendar year" in issue for issue in issues), issues)


if __name__ == "__main__":
    unittest.main()
