"""A manual event keeps its first publication time instead of being re-stamped every run."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import manual_events as me  # noqa: E402


class ManualEventPublishTime(unittest.TestCase):
    def _run(self, events, articles, now):
        with tempfile.TemporaryDirectory() as d:
            ev = Path(d) / "manual_events.json"
            ar = Path(d) / "articles.json"
            ev.write_text(json.dumps(events))
            ar.write_text(json.dumps(articles))
            with mock.patch.object(me, "MANUAL_EVENTS_PATH", ev), mock.patch.object(me, "ARTICLES_PATH", ar):
                return me.load_manual_event_records(now)

    def test_missing_published_at_keeps_existing_first_publication(self):
        events = [{"title": "Breakfast with Santa", "event_start_at": "2026-12-12T10:30:00Z"}]
        articles = [{"slug": "breakfast-with-santa", "story_key": "manual-event:breakfast-with-santa",
                     "first_published_at": "2026-11-17T20:12:10Z"}]
        now = datetime(2026, 11, 24, 20, 30, tzinfo=timezone.utc)
        rec = self._run(events, articles, now)[0]
        self.assertEqual(rec["first_published_at"], "2026-11-17T20:12:10Z")
        self.assertEqual(rec["published_at"], "2026-11-17T20:12:10Z")

    def test_explicit_published_at_wins(self):
        events = [{"title": "Carols", "event_start_at": "2026-12-20T09:30:00Z", "published_at": "2026-11-18T12:48:55Z"}]
        now = datetime(2026, 11, 24, 20, 30, tzinfo=timezone.utc)
        self.assertEqual(self._run(events, [], now)[0]["first_published_at"], "2026-11-18T12:48:55Z")

    def test_brand_new_event_uses_now_once(self):
        events = [{"title": "New Event", "event_start_at": "2026-12-20T09:30:00Z"}]
        now = datetime(2026, 11, 24, 20, 30, tzinfo=timezone.utc)
        self.assertTrue(self._run(events, [], now)[0]["first_published_at"].startswith("2026-11-24T20:30"))


if __name__ == "__main__":
    unittest.main()
