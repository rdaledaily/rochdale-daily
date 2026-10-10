"""Regression: old published records survive newsroom runs; orphaned ledger entries recover safely.

Run: PYTHONPATH=scraper python -m unittest scraper.test_newsroom_archive_recovery
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import scraper as core


class ArchiveAndLedgerRecovery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.object(core, "REWRITE_LEDGER_FILE", Path(self.tmp.name) / "rewrite_ledger.json")
        patch.start()
        self.addCleanup(patch.stop)
        core.reset_rewrite_ledger()
        self.addCleanup(core.reset_rewrite_ledger)

    def article(self):
        return {
            "slug": "historic-community-news",
            "title": "Rochdale community news from September",
            "excerpt": "The community initiative opened in Rochdale.",
            "content_html": "<p>The organisers confirmed the local programme took place in Rochdale during September.</p>",
            "source_name": "Rochdale Borough Council",
            "source_url": "https://www.rochdale.gov.uk/news/article/432/historic-community-news",
            "source_urls": [],
            "source_kind": "article",
            "published_at": "2026-09-01T10:00:00Z",
            "category": "community",
            "area": "rochdale",
            "editorial_lock": True,
        }

    def test_historic_story_is_not_pruned_by_discovery_age(self):
        article = self.article()
        with mock.patch.object(core, "load_json_list", return_value=[article]), \
             mock.patch.object(core, "is_fresh", return_value=False), \
             mock.patch.object(core, "article_passes_locality", return_value=True), \
             mock.patch.object(core, "dedupe_article_records", side_effect=lambda rows: rows):
            archived = core.recent_existing_articles()
        self.assertEqual(len(archived), 1)
        self.assertEqual(archived[0]["slug"], article["slug"])

    def test_missing_published_source_is_reopened_but_not_infinitely(self):
        url = self.article()["source_url"]
        from datetime import datetime, timezone
        item = core.Candidate(
            source_name="Rochdale Borough Council",
            source_url=url,
            source_title="Rochdale community news",
            source_summary="The local programme was announced in Rochdale.",
            source_published_at=datetime.now(timezone.utc).isoformat(),
            area="rochdale", category="community",
        )
        core.record_rewrite_attempt(item, "published")
        self.assertFalse(core.candidate_is_rewrite_eligible(item, {}))

        state = core.reconcile_rewrite_ledger_with_feed([])
        self.assertEqual(state["queued_for_retry"], 1)
        self.assertTrue(core.candidate_is_rewrite_eligible(item, {}))

        core.record_rewrite_attempt(item, "published")
        state = core.reconcile_rewrite_ledger_with_feed([])
        self.assertEqual(state["queued_for_retry"], 1)
        core.record_rewrite_attempt(item, "published")
        state = core.reconcile_rewrite_ledger_with_feed([])
        self.assertEqual(state["recovery_limit_reached"], 1)
        self.assertFalse(core.candidate_is_rewrite_eligible(item, {}))

    def test_published_source_still_in_archive_is_held(self):
        item = core.Candidate(
            source_name="Rochdale Borough Council",
            source_url=self.article()["source_url"],
            source_title="Rochdale community news",
            source_summary="Programme announced in Rochdale.",
            source_published_at=core.iso_utc(core.utc_now()),
            area="rochdale", category="community",
        )
        core.record_rewrite_attempt(item, "published")
        state = core.reconcile_rewrite_ledger_with_feed([self.article()])
        self.assertEqual(state["missing_from_feed"], 0)
        self.assertFalse(core.candidate_is_rewrite_eligible(item, {}))


if __name__ == "__main__":
    unittest.main()
