"""Regression: a manual article's supplied cards-folder photo must survive
ensure_article_images in every lane, not only the publish lane."""
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

import ensure_article_images as images


class ManualPhotoSurvivesAllLanes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        cards = self.root / "assets" / "img" / "cards"
        cards.mkdir(parents=True)
        # Noise so the file is comfortably above the 4 KB "real image" floor.
        Image.effect_noise((1200, 675), 64).convert("RGB").save(cards / "jen-daker-gym-selfie.webp", quality=95)

    def tearDown(self):
        self.tmp.cleanup()

    def manual(self, **extra):
        a = {
            "manual_article": True,
            "source_kind": "editorial",
            "title": "Rochdale personal trainer opens new studio",
            "slug": "rochdale-personal-trainer-opens-new-studio",
            "image_url": "assets/img/cards/jen-daker-gym-selfie.webp",
            "image_credit": "Photo supplied by Jen Daker",
        }
        a.update(extra)
        return a

    def test_manual_photo_kept_without_status_marker(self):
        # Source JSON predates image_status; the injector hard-replaces the record each run.
        a = self.manual()
        self.assertEqual(images.enforce_article(a, self.root), "kept-existing")
        self.assertEqual(a["image_url"], "assets/img/cards/jen-daker-gym-selfie.webp")
        self.assertEqual(a["image_status"], "editorial-photo")
        self.assertEqual(a["image_credit"], "Photo supplied by Jen Daker")

    def test_manual_photo_kept_when_previous_pass_marked_it_generated(self):
        a = self.manual(image_status="cards-generated", image_backfill_method="cards-generated")
        self.assertEqual(images.enforce_article(a, self.root), "kept-existing")
        self.assertEqual(a["image_status"], "editorial-photo")

    def test_missing_manual_file_still_falls_back(self):
        a = self.manual(image_url="assets/img/cards/does-not-exist.webp")
        self.assertNotEqual(images.enforce_article(a, self.root), "kept-existing")
        self.assertIn("generated-card", a["image_url"])

    def test_manual_pointing_at_generated_card_is_not_treated_as_photo(self):
        a = self.manual()
        images.set_generated(a, self.root)  # simulate a clobbered record
        a["manual_article"] = True
        result = images.enforce_article(a, self.root)
        self.assertNotEqual(a["image_status"], "editorial-photo")

    def test_scraped_article_unchanged(self):
        a = {"title": "Something", "slug": "something", "image_url": "assets/img/cards/jen-daker-gym-selfie.webp"}
        # Not manual: the old rule stands (no status marker -> not meaningful).
        self.assertFalse(images.existing_meaningful_image(a, self.root))


if __name__ == "__main__":
    unittest.main()
