#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sync_homepage_top_story as mod


SAMPLE_INDEX = '''<!doctype html>
<html><body>
<div class="breaking-bar">
  <div class="wrap breaking-row">
    <div class="breaking-label">Breaking</div>
    <div class="breaking-copy" id="breaking-copy" aria-label="Old live event">
      <div class="breaking-track" id="breaking-track">
        <span class="breaking-segment"><span class="breaking-text">Old live event</span></span>
        <span class="breaking-segment"><span class="breaking-text">Old live event</span></span>
      </div>
    </div>
  </div>
</div>
<div class="traffic-bar"></div>
<article class="lead-story" id="lead-story" data-content-slot="lead"><a>Old live event</a></article>
<script>
          setBreakingTicker(stripMarkdownText(breakingMessage));
</script>
</body></html>'''


class HomepageTopStorySyncTests(unittest.TestCase):
    def run_sync(self, payload):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index = root / "index.html"
            frontpage = root / "frontpage.json"
            index.write_text(SAMPLE_INDEX, encoding="utf-8")
            frontpage.write_text(json.dumps(payload), encoding="utf-8")
            with patch.object(mod, "INDEX", index), patch.object(mod, "FRONTPAGE", frontpage):
                mod.main()
            return index.read_text(encoding="utf-8")

    def article(self):
        return {
            "title": "Fresh Rochdale story & update",
            "slug": "fresh-rochdale-story",
            "excerpt": "Current verified local reporting.",
            "category": "community",
            "area": "rochdale",
            "byline": "Rochdale Daily Newsdesk",
            "first_published_at": "2026-08-16T12:30:00Z",
            "image_url": "assets/img/cards/fresh.jpg",
        }

    def test_replaces_stale_static_special_lead(self):
        out = self.run_sync({"articles": [self.article()], "breaking": ""})
        self.assertIn('/articles/fresh-rochdale-story.html', out)
        self.assertIn('Fresh Rochdale story &amp; update', out)
        self.assertNotIn('<a>Old live event</a>', out)
        self.assertIn('alt="Fresh Rochdale story &amp; update"', out)

    def test_non_breaking_ticker_is_labelled_latest(self):
        out = self.run_sync({"articles": [self.article()], "breaking": ""})
        self.assertIn('<div class="breaking-label">Latest</div>', out)
        self.assertIn('aria-label="Fresh Rochdale story &amp; update"', out)
        self.assertEqual(out.count('<span class="breaking-text">Fresh Rochdale story &amp; update</span>'), 2)

    def test_real_breaking_message_keeps_breaking_label(self):
        out = self.run_sync({"articles": [self.article()], "breaking": "Road closed after serious collision"})
        self.assertIn('<div class="breaking-label">Breaking</div>', out)
        self.assertEqual(out.count('<span class="breaking-text">Road closed after serious collision</span>'), 2)

    def test_dynamic_label_sync_is_installed_once(self):
        out = self.run_sync({"articles": [self.article()], "breaking": ""})
        self.assertEqual(out.count(mod.LABEL_SYNC_MARKER), 1)
        # Run the transformation a second time against its own output.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index = root / "index.html"
            frontpage = root / "frontpage.json"
            index.write_text(out, encoding="utf-8")
            frontpage.write_text(json.dumps({"articles": [self.article()], "breaking": ""}), encoding="utf-8")
            with patch.object(mod, "INDEX", index), patch.object(mod, "FRONTPAGE", frontpage):
                mod.main()
            second = index.read_text(encoding="utf-8")
        self.assertEqual(second.count(mod.LABEL_SYNC_MARKER), 1)

    def test_no_current_article_leaves_html_unchanged(self):
        out = self.run_sync({"articles": [], "breaking": ""})
        self.assertEqual(out, SAMPLE_INDEX)


if __name__ == "__main__":
    unittest.main()
