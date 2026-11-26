#!/usr/bin/env python3
"""Public photos over 600 KB are shrunk in place, once (optimise_images.py).

Ahrefs, 26 Nov 2026: 19 card images of 1-5.9 MB (camera originals, photos
saved as PNG).

Run:  PYTHONPATH=scraper python scraper/test_optimise_images.py
"""
from __future__ import annotations

import random
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import optimise_images as oi  # noqa: E402


def noisy(size, mode="RGB"):
    rng = random.Random(7)
    image = Image.new(mode, size)
    image.putdata([tuple(rng.randrange(256) for _ in mode) for _ in range(size[0] * size[1])])
    return image


class Optimise(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cards = self.root / "assets" / "img" / "cards"
        self.cards.mkdir(parents=True)
        noisy((2400, 1600)).save(self.cards / "camera.jpg", "JPEG", quality=100)
        noisy((900, 600)).save(self.cards / "photo.png", "PNG")
        noisy((300, 200)).save(self.cards / "small.jpg", "JPEG", quality=90)

    def tearDown(self):
        self.tmp.cleanup()

    def test_large_images_shrink_keep_name_and_format_small_ones_untouched(self):
        small_before = (self.cards / "small.jpg").read_bytes()
        self.assertGreater((self.cards / "camera.jpg").stat().st_size, oi.LIMIT_BYTES)
        self.assertGreater((self.cards / "photo.png").stat().st_size, oi.LIMIT_BYTES)
        oi.optimise(self.root)
        with Image.open(self.cards / "camera.jpg") as image:
            self.assertEqual(image.format, "JPEG")
            self.assertLessEqual(max(image.size), oi.MAX_EDGE)
        with Image.open(self.cards / "photo.png") as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.size, (900, 600))
        self.assertLess((self.cards / "photo.png").stat().st_size,
                        900 * 600 * 3)  # smaller than the raw RGB photo
        self.assertEqual((self.cards / "small.jpg").read_bytes(), small_before)

    def test_second_run_writes_nothing(self):
        oi.optimise(self.root)
        before = {p.name: p.read_bytes() for p in self.cards.iterdir()}
        oi.optimise(self.root)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.cards.iterdir()})

    def test_check_changes_nothing(self):
        before = {p.name: p.read_bytes() for p in self.cards.iterdir()}
        over = oi.optimise(self.root, check=True)
        self.assertEqual({Path(r[0]).name for r in over}, {"camera.jpg", "photo.png"})
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.cards.iterdir()})


if __name__ == "__main__":
    unittest.main()
