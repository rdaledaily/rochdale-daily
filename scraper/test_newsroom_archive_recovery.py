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

    def test_story_lost_to_a_briefing_is_reopened_once(self):
        # 16 Nov 2026: stories absorbed by a Morning Briefing were written off
        # as "missing from feed". After the fix each gets exactly one retry.
        url = "https://www.rochvalleyradio.com/news-features/142/community/1440/man-who-died-in-flat-fire-named"
        ledger = core.load_rewrite_ledger()
        ledger[url] = {
            "first_attempt_at": "2026-11-15T14:20:11Z",
            "last_attempt_at": "2026-11-15T16:16:27Z",
            "attempts": 1, "urls": [url],
            "outcome": "rejected",
            "reason": "missing from feed after repeated publication attempts; review required",
            "title": "Man who died in flat fire named",
            "source_name": "Roch Valley Radio Local News",
            "recovery_attempts": 2, "evidence_recovery_policy": 1,
        }
        core.save_rewrite_ledger()
        state = core.reconcile_rewrite_ledger_with_feed([])
        self.assertEqual(state["reopened_after_briefing_absorb_fix"], 1)
        entry = core.load_rewrite_ledger()[url]
        self.assertEqual(entry["outcome"], "failed")
        # Lost again: the normal limit applies, no second briefing reopen.
        entry.update(outcome="rejected", reason="missing from feed after repeated publication attempts; review required")
        core.save_rewrite_ledger()
        state = core.reconcile_rewrite_ledger_with_feed([])
        self.assertEqual(state["reopened_after_briefing_absorb_fix"], 0)

    def test_new_losses_after_the_fix_get_no_extra_reopen(self):
        url = "https://example.org/story-lost-after-the-fix"
        ledger = core.load_rewrite_ledger()
        ledger[url] = {
            "first_attempt_at": "2026-11-17T09:00:00Z", "last_attempt_at": "2026-11-17T09:00:00Z",
            "attempts": 1, "urls": [url], "outcome": "rejected",
            "reason": "missing from feed after repeated publication attempts; review required",
            "title": "Later story", "source_name": "Example", "evidence_recovery_policy": 1,
        }
        core.save_rewrite_ledger()
        state = core.reconcile_rewrite_ledger_with_feed([])
        self.assertEqual(state["reopened_after_briefing_absorb_fix"], 0)


if __name__ == "__main__":
    unittest.main()
