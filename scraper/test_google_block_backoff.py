"""After repeated Google News block pages the run stops asking Google."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import scraper as core  # noqa: E402


def blocked_feed(*_a, **_k):
    return SimpleNamespace(bozo=True, bozo_exception="not well-formed (invalid token)", entries=[], feed={}, headers={}, status=200, href="")


class GoogleBlockBackoff(unittest.TestCase):
    def test_stops_after_limit_and_reports(self):
        sources = [{"name": f"Google News — q{i}", "url": f"https://news.google.com/rss/search?q={i}",
                    "aggregator": "google", "default_area": "rochdale"} for i in range(10)]
        calls = []

        def parse(url, **kw):
            calls.append(url)
            return blocked_feed()

        with mock.patch.object(core, "RSS_SOURCES", []), \
             mock.patch.object(core, "google_news_sources", lambda: sources), \
             mock.patch.object(core.feedparser, "parse", parse), \
             mock.patch.object(core, "clean_ip_fetch", None), \
             mock.patch.object(core.time, "sleep", lambda *_: None):
            core.collect_rss_candidates()
        self.assertEqual(len(calls), core.GOOGLE_NEWS_BLOCK_LIMIT)
        self.assertIn("Google News", core.RSS_FEED_FAILURES)
        self.assertIn("7 searches skipped", core.RSS_FEED_FAILURES["Google News"])


if __name__ == "__main__":
    unittest.main()
