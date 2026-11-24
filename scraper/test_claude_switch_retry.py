"""Stories rejected during the 23 Nov Claude-switch faults get one fresh set of attempts."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import scraper as core  # noqa: E402


def entry(**over):
    e = {
        "outcome": "rejected",
        "reason": "quality gate after 4 repairs: The model marked the story unpublishable.",
        "attempts": core.REWRITE_REJECTION_ATTEMPT_LIMIT,
        "last_attempt_at": "2026-11-23T18:41:00Z",
        "policy_epoch": core.NEWSROOM_RETRY_POLICY_EPOCH,
        "overlap_rebuild_epoch": core.OVERLAP_REBUILD_POLICY_EPOCH,
    }
    e.update(over)
    return e


class ClaudeSwitchRetryTests(unittest.TestCase):
    def test_rejection_in_fault_window_reopens_once(self):
        self.assertTrue(core._claude_switch_retry(entry()))
        self.assertFalse(core._claude_switch_retry(entry(claude_switch_epoch=core.CLAUDE_SWITCH_RETRY_EPOCH)))

    def test_rejections_outside_window_untouched(self):
        self.assertFalse(core._claude_switch_retry(entry(last_attempt_at="2026-11-22T10:00:00Z")))
        self.assertFalse(core._claude_switch_retry(entry(last_attempt_at="2026-11-24T10:00:00Z")))
        self.assertTrue(core._claude_switch_retry(entry(last_attempt_at="2026-11-24T05:13:00Z")))
        self.assertTrue(core._claude_switch_retry(entry(claude_switch_epoch="2026-11-23-claude-switch-v1")))

    def test_published_and_failed_untouched(self):
        self.assertFalse(core._claude_switch_retry(entry(outcome="published")))
        self.assertFalse(core._claude_switch_retry(entry(outcome="failed")))


if __name__ == "__main__":
    unittest.main()
