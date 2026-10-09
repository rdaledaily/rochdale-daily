#!/usr/bin/env python3
"""Sponsored articles never take a top-story position.

Measured 9 October 2026: three sponsored spotlights published at 16:21 sat at
positions 2, 3 and 4 of the homepage feed, directly under the lead story.

Run:  PYTHONPATH=scraper python scraper/test_sponsored_frontpage_floor.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ensure_manual_frontpage as guard  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


def story(slug: str, minutes_ago: int, *, sponsored: bool = False, manual: bool = False) -> dict:
    when = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")
    row = {"id": slug, "slug": slug, "title": slug, "status": "published", "category": "business",
           "published_at": when, "first_published_at": when, "last_updated_at": when}
    if manual or sponsored:
        row.update(manual_article=True, source_kind="editorial")
    if sponsored:
        row["sponsored"] = True
    return row


class DemoteSponsored(unittest.TestCase):
    def test_sponsored_rows_move_below_the_ninth_position_in_order(self):
        rows = [story("lead", 1), story("ad-a", 2, sponsored=True), story("ad-b", 3, sponsored=True)]
        rows += [story(f"news-{i}", 10 + i) for i in range(12)]
        slugs = [r["slug"] for r in guard.demote_sponsored(rows)]
        self.assertEqual(slugs[:9], ["lead"] + [f"news-{i}" for i in range(8)])
        self.assertEqual(slugs[9:11], ["ad-a", "ad-b"])
        self.assertEqual(sorted(slugs), sorted(r["slug"] for r in rows), "nothing is dropped")

    def test_feed_without_sponsored_rows_is_untouched(self):
        rows = [story(f"news-{i}", i) for i in range(15)]
        self.assertEqual(guard.demote_sponsored(rows), rows)

    def test_short_feed_puts_sponsored_after_the_news_it_has(self):
        rows = [story("ad", 1, sponsored=True), story("news-0", 2), story("news-1", 3)]
        self.assertEqual([r["slug"] for r in guard.demote_sponsored(rows)], ["news-0", "news-1", "ad"])

    def test_manual_non_sponsored_story_keeps_its_place(self):
        rows = [story("lead", 1), story("editor-story", 2, manual=True)] + [story(f"n{i}", 5 + i) for i in range(10)]
        self.assertEqual(guard.demote_sponsored(rows)[1]["slug"], "editor-story")


class GuardEndToEnd(unittest.TestCase):
    def test_restored_sponsored_manual_article_lands_at_position_ten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "articles").mkdir()
            news = [story(f"news-{i}", 30 + i) for i in range(12)]
            ad = story("sponsored-spotlight", 5, sponsored=True)
            (root / "articles" / "frontpage.json").write_text(json.dumps({"articles": news}), encoding="utf-8")
            (root / "articles.json").write_text(json.dumps(news + [ad]), encoding="utf-8")
            old = (guard.FRONTPAGE, guard.ARTICLES, guard.TARGET, guard.FRESH_HOURS)
            guard.FRONTPAGE, guard.ARTICLES = root / "articles" / "frontpage.json", root / "articles.json"
            guard.TARGET, guard.FRESH_HOURS = 30, 36
            try:
                guard.main()
            finally:
                guard.FRONTPAGE, guard.ARTICLES, guard.TARGET, guard.FRESH_HOURS = old
            out = json.loads((root / "articles" / "frontpage.json").read_text(encoding="utf-8"))["articles"]
            slugs = [r["slug"] for r in out]
            self.assertEqual(slugs.index("sponsored-spotlight"), 9)
            self.assertEqual([r["frontpage_rank"] for r in out], list(range(len(out))))
            self.assertEqual(out[0]["slot"], "lead")


class LiveFeedFunction(unittest.TestCase):
    """The Pages Function decides the order readers receive, so test it too."""

    def test_request_time_feed_holds_sponsored_below_the_top_nine(self):
        script = r"""
const fs = require('fs'), path = require('path'), os = require('os');
const repo = process.argv[process.argv.length - 1];
const src = fs.readFileSync(path.join(repo, 'functions/articles/frontpage.json.js'), 'utf8')
  .replace(/export async function onRequest/, 'async function onRequest');
const file = path.join(os.tmpdir(), 'fn_' + Math.random().toString(36).slice(2) + '.cjs');
fs.writeFileSync(file, src + '\nmodule.exports = { onRequest };');
const { onRequest } = require(file); fs.unlinkSync(file);
const now = Date.now();
const at = m => new Date(now - m * 60000).toISOString();
const row = (slug, m, extra) => Object.assign({ id: slug, slug, title: slug, category: 'business',
  published_at: at(m), first_published_at: at(m) }, extra || {});
const articles = [row('ad-newest', 1, { sponsored: true }), row('ad-second', 2, { sponsored: true })];
for (let i = 0; i < 12; i++) articles.push(row('news-' + i, 10 + i));
const files = { '/articles/frontpage.json': { articles, count: articles.length } };
const env = { ASSETS: { fetch: async url => {
  const key = new URL(String(url)).pathname;
  if (!(key in files)) return { ok: false, status: 404, json: async () => ({}), text: async () => '' };
  return { ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(files[key])), text: async () => JSON.stringify(files[key]) };
} } };
onRequest({ request: new Request('https://example.test/articles/frontpage.json'), env }).then(async res => {
  const data = await res.json();
  console.log(JSON.stringify(data.articles.map(a => [a.slug, a.frontpage_rank, a.slot])));
}).catch(e => { console.error(e); process.exit(1); });
"""
        done = subprocess.run(["node", "-e", script, "--", str(REPO)], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        rows = json.loads(done.stdout.strip().splitlines()[-1])
        slugs = [r[0] for r in rows]
        self.assertEqual(slugs[:9], [f"news-{i}" for i in range(9)])
        self.assertEqual(slugs[9:11], ["ad-newest", "ad-second"])
        self.assertEqual(rows[0][2], "lead")
        self.assertEqual([r[1] for r in rows], list(range(len(rows))))
        self.assertEqual(len(slugs), 14)


if __name__ == "__main__":
    unittest.main()
