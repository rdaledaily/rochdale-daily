#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import unittest

import homepage_discovery_metadata as mod


SAMPLE = '''<!doctype html>
<html><head><title>Rochdale Daily</title></head><body>
<p id="feed-status">Article slots ready</p>
<div class="news-grid" id="news-grid">
<!-- STATIC_LATEST_START -->
<article class="news-card static-latest-card">
<a class="story-link" href="/articles/first-story.html">
<h3 class="card-headline">First &amp; Local Story</h3>
<time datetime="2026-08-16T03:12:27Z">16 Aug 2026</time>
</a></article>
<article class="news-card static-latest-card">
<a class="story-link" href="/articles/second-story.html">
<h3 class="card-headline">Second Story</h3>
<time datetime="2026-08-16T02:00:00Z">16 Aug 2026</time>
</a></article>
<!-- STATIC_LATEST_END -->
</div></body></html>'''


class HomepageDiscoveryMetadataTests(unittest.TestCase):
    def test_extracts_visible_static_latest_in_order(self):
        items = mod.extract_items(SAMPLE)
        self.assertEqual([item["title"] for item in items], ["First & Local Story", "Second Story"])
        self.assertEqual(items[0]["url"], "https://rochdaledaily.co.uk/articles/first-story.html")

    def test_enhance_adds_rss_and_itemlist(self):
        enhanced = mod.enhance(SAMPLE)
        self.assertIn(mod.RSS_TAG, enhanced)
        match = re.search(r'<script type="application/ld\+json" id="latest-news-itemlist">(.*?)</script>', enhanced)
        self.assertIsNotNone(match)
        payload = json.loads(match.group(1))
        self.assertEqual(payload["@type"], "ItemList")
        self.assertEqual(payload["numberOfItems"], 2)
        self.assertEqual(payload["itemListElement"][0]["position"], 1)
        self.assertEqual(payload["itemListElement"][0]["item"]["headline"], "First & Local Story")
        self.assertEqual(payload["itemListElement"][0]["item"]["datePublished"], "2026-08-16T03:12:27Z")

    def test_replaces_legacy_feed_status(self):
        enhanced = mod.enhance(SAMPLE)
        self.assertNotIn(mod.LEGACY_FEED_STATUS, enhanced)
        self.assertIn(mod.CURRENT_FEED_STATUS, enhanced)

    def test_enhance_is_idempotent(self):
        once = mod.enhance(SAMPLE)
        twice = mod.enhance(once)
        self.assertEqual(once, twice)
        self.assertEqual(twice.count('id="latest-news-itemlist"'), 1)
        self.assertEqual(twice.count(mod.RSS_TAG), 1)
        self.assertEqual(twice.count(mod.CURRENT_FEED_STATUS), 1)

    def test_refuses_missing_static_latest(self):
        with self.assertRaises(ValueError):
            mod.enhance("<html><head></head><body></body></html>")


if __name__ == "__main__":
    unittest.main()
