"""Regression: a manual article's supplied cards-folder photo must survive
ensure_article_images in every lane, not only the publish lane."""
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from PIL import Image

import ensure_article_images as images
import image_hierarchy


class ManualPhotoSurvivesAllLanes(unittest.TestCase):
    def setUp(self):
        # Unit tests must not depend on Commons availability or live results.
        commons_patch = patch.object(image_hierarchy, "commons_search", return_value={
            "status": "service-unavailable", "pages": [],
        })
        self.commons = commons_patch.start()
        self.addCleanup(commons_patch.stop)
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
        self.assertTrue((self.root / a["image_url"]).is_file())
        self.assertEqual(a["image_status"], "place-generated-card")

    def test_missing_manual_file_can_use_licensed_commons_photo(self):
        # The story must NAME the subject: a generic town view is never used.
        self.commons.return_value = {"status": "searched", "pages": [{
            "title": "File:Hollingworth Lake.jpg",
            "imageinfo": [{
                "mime": "image/jpeg", "url": "https://example.org/skyline.jpg",
                "descriptionurl": "https://commons.wikimedia.org/wiki/File:Hollingworth_Lake.jpg",
                "extmetadata": {
                    "LicenseShortName": {"value": "CC BY-SA 4.0"},
                    "Artist": {"value": "Test photographer"},
                    "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0/"},
                },
            }],
        }]}
        def download_fixture(url, target, timeout):
            Image.new("RGB", (1200, 675), "blue").save(target, "JPEG")
            return True
        a = self.manual(image_url="assets/img/cards/does-not-exist.webp",
                        title="Rochdale personal trainer opens studio at Hollingworth Lake")
        with patch("repair_generated_with_commons.download", side_effect=download_fixture) as download:
            self.assertEqual(images.enforce_article(a, self.root), "kept-existing")
        download.assert_called_once()
        self.assertTrue((self.root / a["image_url"]).is_file())
        self.assertEqual(a["image_status"], "commons-photo-cached")
        self.assertIn("CC BY-SA 4.0", a["image_credit"])
        self.assertEqual(a["source_image_reuse_status"], "commons-free-license")

    def test_pipeline_pick_on_manual_story_is_not_protected(self):
        # Live case: rochdale_afc.jpg chosen from excerpt words on a Sleep Out story.
        cards = self.root / "assets" / "img" / "cards"
        Image.effect_noise((1200, 675), 64).convert("RGB").save(cards / "rochdale_afc.jpg", quality=95)
        a = self.manual(title="Rochdale Sleep Out raises almost 10,000",
                        slug="rochdale-sleep-out-nearly-10000",
                        image_url="assets/img/cards/rochdale_afc.jpg",
                        image_status="editorial-photo", image_match_score=8252)
        images.enforce_article(a, self.root)
        self.assertNotEqual(a["image_url"], "assets/img/cards/rochdale_afc.jpg")

    def test_pipeline_pick_that_names_the_subject_is_kept(self):
        cards = self.root / "assets" / "img" / "cards"
        Image.effect_noise((1200, 675), 64).convert("RGB").save(cards / "norden_cricket_club.jpg", quality=95)
        a = self.manual(title="Norden Cricket Club festival brings community together",
                        slug="norden-cricket-club-festival",
                        image_url="assets/img/cards/norden_cricket_club.jpg", image_match_score=15127)
        self.assertEqual(images.enforce_article(a, self.root), "kept-existing")

    def test_no_named_subject_gets_place_card_not_a_skyline(self):
        self.commons.side_effect = AssertionError("no subject = no Commons search")
        a = self.manual(image_url="assets/img/cards/does-not-exist.webp")
        images.enforce_article(a, self.root)
        self.assertEqual(a["image_status"], "place-generated-card")
        self.assertEqual(a["commons_image_search"], "no-specific-subject")

    def test_existing_skyline_image_is_replaced(self):
        cards = self.root / "assets" / "img" / "cards"
        skyline = cards / "5c4b8c73f2d8a375-commons-photo.jpg"
        Image.effect_noise((1200, 675), 64).convert("RGB").save(skyline, quality=95)
        (cards / "commons_image_candidates.json").write_text(json.dumps({"rochdale skyline": {
            "status": "matched", "image_url": "assets/img/cards/5c4b8c73f2d8a375-commons-photo.jpg"}}))
        a = {"title": "Two Rochdale men among ten charged", "slug": "ten-charged", "category": "crime",
             "image_url": "assets/img/cards/5c4b8c73f2d8a375-commons-photo.jpg",
             "image_status": "commons-photo-cached", "image_credit": "R lee / Wikimedia Commons (CC BY-SA 2.0)",
             "image_alt": "File image: Rochdale skyline. Not a photograph of this event."}
        self.assertNotEqual(images.enforce_article(a, self.root), "kept-existing")
        self.assertNotIn("commons", a["image_url"])

    def test_named_commons_photo_is_still_kept(self):
        cards = self.root / "assets" / "img" / "cards"
        lake = cards / "aaaa-commons-photo.jpg"
        Image.effect_noise((1200, 675), 64).convert("RGB").save(lake, quality=95)
        a = {"title": "Hollingworth Lake documentary", "slug": "lake-doc", "category": "events",
             "image_url": "assets/img/cards/aaaa-commons-photo.jpg", "image_status": "commons-photo-cached",
             "image_alt": "File image: Hollingworth Lake. Not a photograph of this event."}
        self.assertEqual(images.enforce_article(a, self.root), "kept-existing")

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

