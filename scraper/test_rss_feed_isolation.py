#!/usr/bin/env python3
"""One failing feed must not stop every other feed from being read.

Measured 19 October 2026: from 14:23 UTC every newsroom run collected 0 items
from RSS and Google News, because one feed's server closed the connection and
feedparser raised http.client.RemoteDisconnected out of the whole collector.

Run:  PYTHONPATH=scraper python scraper/test_rss_feed_isolation.py
"""
from __future__ import annotations

import http.client
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scraper as core  # noqa: E402

GOOD = {"name": "Good Feed", "url": "https://good.example/feed", "default_area": "rochdale", "rss_only": True}
BAD = {"name": "Dropped Feed", "url": "https://bad.example/feed", "default_area": "rochdale", "rss_only": True}


def fake_parse(url, agent=None):
    if "bad.example" in url:
        raise http.client.RemoteDisconnected("Remote end closed connection without response")
    entry = types.SimpleNamespace(link="https://good.example/story", title="Council opens new library in Rochdale town centre",
                                  summary="Rochdale Borough Council opened a library on Drake Street, Rochdale.",
                                  published="Mon, 19 Oct 2026 10:00:00 GMT")
    entry.get = lambda key, default=None: getattr(entry, key, default)
    return types.SimpleNamespace(bozo=False, entries=[entry])


class FeedIsolation(unittest.TestCase):
    def test_a_dropped_connection_skips_that_feed_and_the_rest_are_read(self):
        reached = []

        def parse(url, agent=None):
            reached.append(url)
            return fake_parse(url, agent)

        with mock.patch.object(core, "RSS_SOURCES", [BAD, GOOD]), \
                mock.patch.object(core, "google_news_sources", lambda: []), \
                mock.patch.object(core, "men_newsletter_sources", lambda: []), \
                mock.patch.object(core.feedparser, "parse", parse):
            core.collect_rss_candidates()          # must not raise
        self.assertEqual(reached, [BAD["url"], GOOD["url"]], "the feed after the failure must still be read")
        self.assertIn("Dropped Feed", core.RSS_FEED_FAILURES)
        self.assertIn("RemoteDisconnected", core.RSS_FEED_FAILURES["Dropped Feed"])
        self.assertNotIn("Good Feed", core.RSS_FEED_FAILURES)

    def test_failures_are_reported_in_the_run_status(self):
        source = (Path(__file__).resolve().parent / "scraper.py").read_text(encoding="utf-8")
        self.assertIn("'rss_feed_failures': dict(RSS_FEED_FAILURES)", source)


if __name__ == "__main__":
    unittest.main()
