#!/usr/bin/env python3
"""Generated cards are drawn in the paper's own palette and typefaces.

Run:  PYTHONPATH=scraper python scraper/test_generated_card_style.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ensure_article_images as cards  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
OLD_SLAB = (13, 19, 28)
OLD_CYAN = (37, 164, 201)


def near(a, b, tolerance=10):
    return all(abs(x - y) <= tolerance for x, y in zip(a, b))


class CardStyle(unittest.TestCase):
    def draw(self, title="Council approves new homes on Halifax Road", category="news", **kw):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "x-generated-card.jpg"
        cards.draw_generated_card(path, title, category, **kw)
        return Image.open(path).convert("RGB")

    def test_site_typefaces_ship_with_the_repo(self):
        for name in ("LibreBaskerville-wght.ttf", "InstrumentSans-wdth-wght.ttf"):
            self.assertTrue((REPO / cards.FONT_DIR / name).is_file(), name)
        self.assertIn("Baskerville", " ".join(cards.card_font("serif", 40).getname()))

    def test_card_is_paper_and_ink_with_no_trace_of_the_old_palette(self):
        image = self.draw()
        self.assertEqual(image.size, (cards.WIDTH, cards.HEIGHT))
        for point in ((5, 5), (600, 5), (1195, 670), (600, 40)):
            self.assertTrue(near(image.getpixel(point), cards.CARD_PAPER), point)
        small = image.resize((300, 169))
        counted = small.getcolors(maxcolors=100000)
        total = sum(n for n, _ in counted)
        paper = sum(n for n, c in counted if near(c, cards.CARD_PAPER, 14))
        dark = sum(n for n, c in counted if sum(c) < 240)
        self.assertGreater(paper / total, 0.75, "the card must be mostly paper, not a dark slab")
        self.assertLess(dark / total, 0.15, "ink is for type only")
        self.assertFalse(any(near(c, OLD_CYAN, 28) for _, c in counted), "old cyan present")
        self.assertTrue(any(near(c, cards.CARD_INK, 28) for _, c in counted), "no ink drawn")

    def test_long_headline_stays_inside_the_card(self):
        image = self.draw("Every secondary school in Rochdale ranked " * 6)
        for x in range(cards.WIDTH - cards.CARD_MARGIN + 6, cards.WIDTH):
            self.assertTrue(near(image.getpixel((x, 340)), cards.CARD_PAPER), "text ran into the right margin")

    def test_sponsored_prefix_becomes_the_kicker(self):
        plain = self.draw("SJF Granite supplies worktops", "business", sponsored=True)
        prefixed = self.draw("Sponsored: SJF Granite supplies worktops", "business")
        self.assertLess(sum(abs(a - b) for a, b in zip(plain.resize((60, 34)).tobytes(), prefixed.resize((60, 34)).tobytes())), 400)


class RestyleOnce(unittest.TestCase):
    def test_existing_cards_are_redrawn_once_and_orphans_are_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / cards.CARDS_DIR
            folder.mkdir(parents=True)
            for slug in ("live-story", "archived-story", "orphan-story"):
                Image.new("RGB", (cards.WIDTH, cards.HEIGHT), OLD_SLAB).save(folder / f"{slug}-generated-card.jpg")
            Image.new("RGB", (cards.WIDTH, cards.HEIGHT), (200, 30, 30)).save(folder / "a-real-photo.jpg")
            (root / "archive-index.json").write_text(json.dumps(
                [{"slug": "archived-story", "title": "Archived story", "category": "Sport"}]), encoding="utf-8")
            rows = [{"slug": "live-story", "title": "Live story", "category": "news"}]

            first = cards.restyle_generated_cards(root, rows)
            self.assertEqual((first["redrawn"], first["no_article"]), (2, 1))
            corner = lambda name: Image.open(folder / name).convert("RGB").getpixel((5, 5))
            self.assertTrue(near(corner("live-story-generated-card.jpg"), cards.CARD_PAPER))
            self.assertTrue(near(corner("archived-story-generated-card.jpg"), cards.CARD_PAPER))
            self.assertTrue(near(corner("orphan-story-generated-card.jpg"), OLD_SLAB), "no headline to draw: left as it was")
            self.assertTrue(near(corner("a-real-photo.jpg"), (200, 30, 30)), "photographs are never touched")

            before = (folder / "live-story-generated-card.jpg").stat().st_mtime_ns
            second = cards.restyle_generated_cards(root, rows)
            self.assertEqual(second["redrawn"], 0)
            self.assertEqual((folder / "live-story-generated-card.jpg").stat().st_mtime_ns, before)


if __name__ == "__main__":
    unittest.main()
