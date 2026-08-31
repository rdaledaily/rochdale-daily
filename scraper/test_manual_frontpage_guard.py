#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import ensure_manual_frontpage as guard


class ManualFrontpageGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.old_frontpage = guard.FRONTPAGE
        self.old_articles = guard.ARTICLES
        self.old_target = guard.TARGET
        self.old_hours = guard.FRESH_HOURS
        guard.FRONTPAGE = self.root / "articles" / "frontpage.json"
        guard.ARTICLES = self.root / "articles.json"
        guard.TARGET = 2
        guard.FRESH_HOURS = 36
        guard.FRONTPAGE.parent.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        guard.FRONTPAGE = self.old_frontpage
        guard.ARTICLES = self.old_articles
        guard.TARGET = self.old_target
        guard.FRESH_HOURS = self.old_hours
        self.temp.cleanup()

    @staticmethod
    def article(slug: str, *, manual: bool = False) -> dict:
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return {
            "id": slug,
            "slug": slug,
            "title": slug.replace("-", " ").title(),
            "status": "published",
            "category": "news",
            "source_kind": "editorial" if manual else "scrape",
            "manual_article": manual,
            "published_at": now,
            "first_published_at": now,
            "last_updated_at": now,
        }

    def test_missing_manual_story_is_restored_without_displacing_lead(self) -> None:
        lead = self.article("automatic-lead")
        other = self.article("automatic-other")
        manual = self.article("editor-story", manual=True)
        guard.ARTICLES.write_text(json.dumps([lead, other, manual]), encoding="utf-8")
        guard.FRONTPAGE.write_text(json.dumps({"articles": [lead, other]}), encoding="utf-8")

        self.assertEqual(guard.main(), 0)
        payload = json.loads(guard.FRONTPAGE.read_text(encoding="utf-8"))
        slugs = [row["slug"] for row in payload["articles"]]

        self.assertEqual(slugs, ["automatic-lead", "editor-story"])
        self.assertEqual(payload["manual_frontpage_guard"]["restored_manual"], 1)

    def test_all_fresh_manual_stories_are_protected_even_above_target(self) -> None:
        lead = self.article("automatic-lead")
        first = self.article("editor-one", manual=True)
        second = self.article("editor-two", manual=True)
        guard.ARTICLES.write_text(json.dumps([lead, first, second]), encoding="utf-8")
        guard.FRONTPAGE.write_text(json.dumps({"articles": [lead]}), encoding="utf-8")

        self.assertEqual(guard.main(), 0)
        payload = json.loads(guard.FRONTPAGE.read_text(encoding="utf-8"))
        slugs = [row["slug"] for row in payload["articles"]]

        self.assertEqual(slugs[0], "automatic-lead")
        self.assertIn("editor-one", slugs)
        self.assertIn("editor-two", slugs)
        self.assertEqual(len(slugs), 3)


if __name__ == "__main__":
    unittest.main()
