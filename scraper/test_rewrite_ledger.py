"""One rewrite per piece of source material.

Measured 2-8 October 2026: 5,347 rewrite attempts over 692 runs covered 175
distinct source links and produced 46 new stories. A published story was
rewritten again on every run (its stored story_key is recomputed from the
rewritten text, so the candidate's key never matched it), and a rejected
candidate was sent back to the model every run. These tests pin the fix.

Run:  PYTHONPATH=scraper python scraper/test_rewrite_ledger.py
"""
import json
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import scraper as core  # noqa: E402
import run_newspaper_pipeline as rnp  # noqa: E402

URL = "https://www.example-police.uk/news/2026/october/man-arrested-in-rochdale/"


def candidate(url=URL, title="Man arrested following incident in Rochdale", related=None, **extra):
    return core.Candidate(
        source_name="Example Police",
        source_url=url,
        source_title=title,
        source_summary="Officers were called to Drake Street, Rochdale, at 9pm on Thursday.",
        source_published_at=core.iso_utc(core.utc_now()),
        area="rochdale",
        category="crime",
        related_sources=list(related or []),
        **extra,
    )


def stored(url=URL, key="hard-news-v3-stored-key-from-rewritten-text", **extra):
    article = {
        "id": "abc123",
        "slug": "man-arrested-following-incident-in-rochdale",
        "title": "Man Arrested Following Incident in Rochdale",
        "story_key": key,
        "source_url": url,
        "source_urls": [url],
        "editorial_style_version": core.STYLE_VERSION,
        "first_published_at": "2026-10-08T12:47:00Z",
    }
    article.update(extra)
    return {key: article}


class LedgerCase(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.path = Path(self._dir.name) / "rewrite_ledger.json"
        patcher = mock.patch.object(core, "REWRITE_LEDGER_FILE", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        core.reset_rewrite_ledger()
        self.addCleanup(core.reset_rewrite_ledger)


class Identity(LedgerCase):
    def test_tracking_parameters_and_trailing_slash_do_not_change_identity(self):
        self.assertEqual(
            core.candidate_identity(candidate(URL + "?utm_source=x")),
            core.candidate_identity(candidate(URL.rstrip("/"))),
        )

    def test_live_alert_fragment_is_part_of_identity(self):
        page = "https://tfgm.com/travel-updates/travel-alerts?ContensisTextOnly=true"
        first = core.candidate_identity(candidate(page + "#live-aaa"))
        second = core.candidate_identity(candidate(page + "#live-bbb"))
        self.assertNotEqual(first, second, "two alerts on one page must not be treated as one story")


class PublishedStoryIsNotRewrittenAgain(LedgerCase):
    def test_same_source_url_matches_even_though_story_keys_differ(self):
        """The production bug: key lookup misses, so the story looked new every run."""
        item = candidate()
        existing = stored()
        self.assertNotIn(core.build_story_key(item), existing)
        self.assertFalse(core.candidate_is_rewrite_eligible(item, existing))

    def test_genuinely_new_source_reopens_the_story_and_keeps_its_stored_key(self):
        other = "https://www.example-paper.co.uk/news/arrest-after-drake-street-incident"
        item = candidate(url=other, related=[{"name": "Example Police", "url": URL}])
        existing = stored(source_urls=[URL, other])
        existing_key = next(iter(existing))
        # Same story, already carrying both sources: nothing new.
        self.assertFalse(core.candidate_is_rewrite_eligible(item, existing))
        # A third outlet arrives: that is new material.
        third = candidate(related=[{"name": "Third", "url": "https://third.example/story"}])
        self.assertTrue(core.candidate_is_rewrite_eligible(third, existing))
        self.assertEqual(third.story_key, existing_key, "slug/id preservation depends on the stored key")

    def test_locked_manual_article_from_same_source_is_not_shadowed_by_a_rewrite(self):
        existing = stored(key="manual-article:man-arrested", editorial_lock=True, manual_article=True)
        self.assertFalse(core.candidate_is_rewrite_eligible(candidate(), existing))

    def test_published_outcome_holds_the_candidate_when_no_stored_article_matches(self):
        """Backstop: even if a later step strips the article's source URLs."""
        item = candidate()
        core.record_rewrite_attempt(item, "published")
        self.assertFalse(core.candidate_is_rewrite_eligible(candidate(), {}))
        self.assertIn("already published", core.rewrite_ledger_block_reason(candidate()))


class RejectionIsRemembered(LedgerCase):
    def test_rejection_is_retried_up_to_the_limit_then_held_with_its_reason(self):
        reason = "editorial gate: REJECTED_NON_LOCAL"
        for attempt in range(1, core.REWRITE_REJECTION_ATTEMPT_LIMIT + 1):
            self.assertTrue(core.candidate_is_rewrite_eligible(candidate(), {}), f"attempt {attempt} must be allowed")
            core.record_rewrite_attempt(candidate(), core.rewrite_outcome_for_reason(reason), reason)
        self.assertFalse(core.candidate_is_rewrite_eligible(candidate(), {}))
        held = list(core.REWRITE_LEDGER_HELD.values())
        self.assertEqual(len(held), 1)
        self.assertIn("REJECTED_NON_LOCAL", held[0]["held_because"])
        self.assertEqual(held[0]["attempts"], core.REWRITE_REJECTION_ATTEMPT_LIMIT)

    def test_provider_failure_is_never_held_against_a_story(self):
        reason = "OpenAI: all 4 attempts failed (RateLimitError)"
        self.assertEqual(core.rewrite_outcome_for_reason(reason), "failed")
        self.assertEqual(core.rewrite_outcome_for_reason("worker crashed: KeyError"), "failed")
        for _ in range(10):
            core.record_rewrite_attempt(candidate(), "failed", reason)
        self.assertTrue(core.candidate_is_rewrite_eligible(candidate(), {}))

    def test_new_source_material_reopens_a_rejected_story_with_a_fresh_count(self):
        reason = "quality check: Rewrite the long verbatim source passage."
        for _ in range(core.REWRITE_REJECTION_ATTEMPT_LIMIT):
            core.record_rewrite_attempt(candidate(), "rejected", reason)
        self.assertFalse(core.candidate_is_rewrite_eligible(candidate(), {}))
        richer = candidate(related=[{"name": "Council", "url": "https://council.example/statement"}])
        self.assertTrue(core.candidate_is_rewrite_eligible(richer, {}))
        core.record_rewrite_attempt(richer, "rejected", reason)
        self.assertEqual(core.load_rewrite_ledger()[core.candidate_identity(richer)]["attempts"], 1)

    def test_skip_reason_is_attributed_to_the_candidate_being_processed(self):
        captured = []
        core._REWRITE_SKIP_CAPTURE.reasons = captured
        try:
            core.note_rewrite_skip("editorial gate: REJECTED_NON_NEWS")
        finally:
            core._REWRITE_SKIP_CAPTURE.reasons = None
        self.assertEqual(captured, ["editorial gate: REJECTED_NON_NEWS"])


class Persistence(LedgerCase):
    def test_ledger_round_trips_through_disk(self):
        core.record_rewrite_attempt(candidate(), "published")
        core.save_rewrite_ledger()
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(payload["count"], 1)
        core.reset_rewrite_ledger()
        self.assertFalse(core.candidate_is_rewrite_eligible(candidate(), {}))

    def test_entries_expire_after_the_retention_window(self):
        core.record_rewrite_attempt(candidate(), "published")
        entry = core.load_rewrite_ledger()[core.candidate_identity(candidate())]
        entry["last_attempt_at"] = core.iso_utc(
            core.utc_now() - timedelta(hours=core.REWRITE_LEDGER_RETENTION_HOURS + 1)
        )
        core.save_rewrite_ledger()
        core.reset_rewrite_ledger()
        self.assertEqual(core.load_rewrite_ledger(), {})

    def test_retention_outlasts_the_candidate_reservoir(self):
        """Otherwise a candidate would be forgotten while it is still being offered."""
        self.assertGreater(core.REWRITE_LEDGER_RETENTION_HOURS, 96)

    def test_unreadable_ledger_never_stops_the_newsroom(self):
        self.path.write_text("{ this is not json", encoding="utf-8")
        core.reset_rewrite_ledger()
        self.assertEqual(core.load_rewrite_ledger(), {})
        self.assertTrue(core.candidate_is_rewrite_eligible(candidate(), {}))


class LiveUpdateBypass(LedgerCase):
    def test_unchanged_page_is_not_a_material_update(self):
        item = candidate()
        self.assertTrue(core.source_material_changed_since_last_attempt(item), "never attempted")
        core.record_rewrite_attempt(item, "published")
        self.assertFalse(core.source_material_changed_since_last_attempt(candidate()))
        changed = candidate(title="Man charged following incident in Rochdale")
        self.assertTrue(core.source_material_changed_since_last_attempt(changed))

    def test_production_gate_refuses_the_bypass_when_the_page_is_unchanged(self):
        item = candidate()
        core.record_rewrite_attempt(item, "published")
        with mock.patch.object(core, "candidate_is_rewrite_eligible", core.candidate_is_rewrite_eligible), \
                mock.patch.object(rnp, "_same_source_live_update", lambda c, e: True), \
                mock.patch.object(rnp, "_source_is_temporally_suspect", lambda c: False), \
                mock.patch.object(rnp, "_looks_like_commercial_landing_page", lambda c: False):
            rnp.configure_editorial_newsworthiness_gate()
            self.assertFalse(core.candidate_is_rewrite_eligible(candidate(), stored()))
            changed = candidate(title="Man charged following incident in Rochdale")
            self.assertTrue(core.candidate_is_rewrite_eligible(changed, stored()))
            self.assertEqual(core.REWRITE_LEDGER_HELD, {}, "a bypassed story must not be reported as held")


class LanesCommitTheLedger(unittest.TestCase):
    def test_publish_script_stages_and_carries_the_ledger(self):
        """A fresh checkout starts every run: an uncommitted ledger remembers nothing."""
        script = (Path(__file__).resolve().parent / "publish_newsroom_snapshot.sh").read_text(encoding="utf-8")
        stage = script.split("stage_newsroom() {", 1)[1].split("}", 1)[0]
        self.assertIn("rewrite_ledger.json", stage)
        self.assertEqual(script.count("newsroom_candidates.json rewrite_ledger.json live_source_state.json"), 2)


if __name__ == "__main__":
    unittest.main()
