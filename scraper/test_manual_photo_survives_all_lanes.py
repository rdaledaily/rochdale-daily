"""Regression: a manual article's supplied cards-folder photo must survive
ensure_article_images in every lane, not only the publish lane."""
import json
import os
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


class HourlyCommonsPassTests(unittest.TestCase):
    """6 Nov 2026: the hourly pass checked 145 stories and repaired none,
    searching headline words; its licence test also passed CC BY-NC."""

    def test_query_is_the_named_subject_or_nothing(self):
        import repair_generated_with_commons as hourly
        self.assertEqual(hourly.query_for({"title": "Did goblins move Rochdale Parish Church up the hill?"}),
                         "St Chad's Church Rochdale")
        self.assertEqual(hourly.query_for({"title": "Bridge Street in Heywood closed over building safety concerns"}),
                         "Bridge Street")
        self.assertEqual(hourly.query_for({"title": "Rochdale prepares for return of popular ale trail event",
                                           "area": "rochdale"}), "")

    def test_non_commercial_licence_rejected(self):
        import repair_generated_with_commons as hourly
        article = {"title": "Bridge Street in Heywood closed over building safety concerns", "area": "heywood"}
        def page(licence):
            return {"title": "File:Bridge Street, Heywood.jpg", "imageinfo": [{"mime": "image/jpeg",
                    "extmetadata": {"LicenseShortName": {"value": licence}}}]}
        self.assertTrue(hourly.acceptable(article, page("CC BY-SA 2.0"))[0])
        self.assertFalse(hourly.acceptable(article, page("CC BY-NC-SA 2.0"))[0])
        self.assertFalse(hourly.acceptable(article, page("CC BY-ND 4.0"))[0])
        other = {"title": "File:Market Street, Heywood.jpg", "imageinfo": [{"mime": "image/jpeg",
                 "extmetadata": {"LicenseShortName": {"value": "CC BY-SA 2.0"}}}]}
        self.assertFalse(hourly.acceptable(article, other)[0])


class PlaceFromStoryTests(unittest.TestCase):
    """7 Nov 2026: 77 of 159 non-crime beige stories name their place in the
    opening paragraph, 5 in the headline."""

    def test_opening_paragraph_place_after_a_locative(self):
        import image_hierarchy as ih
        story = {"title": "Community efforts revive historic mill", "category": "community", "area": "littleborough",
                 "content_html": "<p>Volunteers met at Lodge Mill on Saturday.</p><p>Later they walked to Hare Hill Park.</p>"}
        self.assertEqual(ih.subject_for(story), "Lodge Mill")
        # 7 Nov 2026: the first three paragraphs are read; a place after
        # "at"/"on" wins over one merely named first.
        later = dict(story, content_html="<p>The group met again.</p><p>Members of Hare Hill Park Friends "
                                          "gathered on Drake Street.</p>")
        self.assertEqual(ih.subject_for(later), "Drake Street")
        named = dict(story, content_html="<p>The group met again.</p><p>Hare Hill Park was busy.</p>")
        self.assertEqual(ih.subject_for(named), "Hare Hill Park")
        too_late = dict(story, content_html="<p>a</p><p>b</p><p>c</p><p>They met at Lodge Mill.</p>")
        self.assertEqual(ih.subject_for(too_late), "")

    def test_never_on_crime_sensitive_or_sponsored(self):
        import image_hierarchy as ih
        body = "<p>It happened on Halifax Road on Monday.</p>"
        self.assertEqual(ih.subject_for({"title": "Driver arrested on Milnrow Road", "category": "crime"}), "")
        self.assertEqual(ih.subject_for({"title": "Man died after crash", "category": "news", "content_html": body}), "")
        self.assertEqual(ih.subject_for({"title": "Sponsored: Hi Pilates Club offers classes", "sponsored": True}), "")

    def test_headline_names_cleaned(self):
        import image_hierarchy as ih
        self.assertEqual(ih._headline_place("Court Rules on Ownership Dispute Over Hopwood Hall"), "Hopwood Hall")
        self.assertEqual(ih._headline_place("Volunteers tackle Middleton’s Jubilee Park"), "Jubilee Park")
        self.assertEqual(ih._headline_place("Andy’s Man Club Rochdale has four groups"), "Andy’s Man Club")
        self.assertEqual(ih._headline_place("Rochdale Golf Club pair crowned"), "Rochdale Golf Club")
        self.assertEqual(ih._headline_place("Pupils at Primary School win"), "")

    def test_photo_must_be_in_this_borough(self):
        import image_hierarchy as ih
        story = {"title": "Plans for tower", "area": "rochdale"}
        def page(title, categories=""):
            return {"title": title, "imageinfo": [{"mime": "image/jpeg", "extmetadata": {
                "LicenseShortName": {"value": "CC BY-SA 2.0"}, "Categories": {"value": categories}}}]}
        self.assertFalse(ih.acceptable(page("File:Rochdale Road, Collyhurst.jpg", "Streets in Manchester"), "Rochdale Road", story))
        self.assertTrue(ih.acceptable(page("File:Lodge Mill.jpg", "Littleborough|Mills in Rochdale"), "Lodge Mill",
                                      dict(story, area="littleborough")))
        self.assertFalse(ih.acceptable(page("File:Jubilee Park, Bolton.jpg", "Parks in Bolton"), "Jubilee Park",
                                       dict(story, area="middleton")))


class CommonsCacheLocalityTests(unittest.TestCase):
    """7 Nov 2026 review: the Commons cache was keyed by place name alone and
    reused without the borough check, so a Heywood "Jubilee Park" photo went
    on a Middleton story; matches cached that way had also put Tom Quad,
    Oxford on Christ Church Healey."""

    def setUp(self):
        import tempfile
        from PIL import Image
        self.root = Path(tempfile.mkdtemp())
        cards = self.root / "assets/img/cards"
        cards.mkdir(parents=True)
        Image.new("RGB", (800, 500), "green").save(cards / "heywoodpark-commons-photo.jpg")
        page = {"title": "File:Jubilee Park, Heywood.jpg", "imageinfo": [{"mime": "image/jpeg", "extmetadata": {
            "LicenseShortName": {"value": "CC BY-SA 2.0"}, "Categories": {"value": "Heywood, Greater Manchester"}}}]}
        self.cache = {
            "jubilee park|heywood": {"status": "matched", "subject": "Jubilee Park", "page": page,
                                     "image_url": "assets/img/cards/heywoodpark-commons-photo.jpg"},
            # Old shape: keyed by name alone, no file details to check.
            "jubilee park": {"status": "matched", "subject": "Jubilee Park",
                             "image_url": "assets/img/cards/heywoodpark-commons-photo.jpg"},
        }
        (cards / "commons_image_candidates.json").write_text(json.dumps(self.cache))

    def story(self, area):
        return {"slug": f"jubilee-{area}", "title": f"Volunteers tidy {area.title()}’s Jubilee Park",
                "category": "community", "area": area, "image_url": "", "image_status": "place-generated-card"}

    def test_cache_key_carries_the_town(self):
        import image_hierarchy as ih
        self.assertEqual(ih.commons_cache_key("Jubilee Park", self.story("middleton")), "jubilee park|middleton")
        self.assertEqual(ih.commons_cache_key("Rochdale Town Hall", self.story("middleton")), "rochdale town hall")

    def test_heywood_photo_never_reaches_middleton(self):
        import image_hierarchy as ih
        middleton = self.story("middleton")
        ih.choose_image(middleton, self.root, allow_network=False)
        self.assertNotIn("heywoodpark", middleton["image_url"])
        heywood = self.story("heywood")
        ih.choose_image(heywood, self.root, allow_network=False)
        self.assertIn("heywoodpark", heywood["image_url"])
        self.assertEqual(heywood["commons_validated_for"], "jubilee park|heywood#c" + str(ih.COMMONS_MATCH_VERSION))

    def test_unchecked_commons_photo_is_redecided(self):
        import ensure_article_images as images
        story = dict(self.story("heywood"), image_url="assets/img/cards/heywoodpark-commons-photo.jpg",
                     image_status="commons-photo-cached", image_backfill_method="wikimedia-commons")
        self.assertFalse(images.existing_meaningful_image(dict(story), self.root))
        checked = dict(story, commons_validated_for="jubilee park|heywood#c" + str(image_hierarchy.COMMONS_MATCH_VERSION))
        self.assertTrue(images.existing_meaningful_image(checked, self.root))
        # An editor's own photo is never re-decided.
        own = dict(story, manual_article=True, editorial_lock=True, image_backfill_method="manual-editorial-photo",
                   image_status="editorial-photo")
        self.assertTrue(images.existing_meaningful_image(own, self.root))


class GeographStreetPhotoTests(unittest.TestCase):
    """7 Nov 2026: Geograph covers the streets Commons does not."""

    RSS = ('<?xml version="1.0"?><rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"><channel>'
           '<item><title>Drake Street, Rochdale</title><link>https://www.geograph.org.uk/photo/123</link>'
           '<dc:creator>Jane Smith</dc:creator>'
           '<enclosure url="https://s0.geograph.org.uk/geophotos/00/01/23/123_abcd_120x120.jpg" type="image/jpeg"/></item>'
           '<item><title>Bus stop</title><link>https://www.geograph.org.uk/photo/124</link>'
           '<description>&lt;img src="https://s0.geograph.org.uk/x/124_ef_120x90.jpg"&gt;</description></item>'
           '</channel></rss>')

    def test_feed_parsed_and_full_size_derived(self):
        import geograph_images as g
        rows = g.parse_rss(self.RSS)
        self.assertEqual([r["title"] for r in rows], ["Drake Street, Rochdale", "Bus stop"])
        no_image = self.RSS.replace('<enclosure url="https://s0.geograph.org.uk/geophotos/00/01/23/123_abcd_120x120.jpg" type="image/jpeg"/>', '')
        self.assertEqual(g.parse_rss(no_image)[0]["thumb"], "")   # counted, never used
        self.assertEqual(rows[0]["author"], "Jane Smith")
        self.assertEqual(g.full_size(rows[0]["thumb"]), "https://s0.geograph.org.uk/geophotos/00/01/23/123_abcd.jpg")
        self.assertTrue(g.title_matches("Drake Street", "Drake Street, Rochdale"))
        self.assertFalse(g.title_matches("Drake Street", "Bus stop"))
        self.assertEqual(g.town_for({"area": "milnrow-and-newhey"}), "milnrow")
        self.assertEqual(g.town_for({"area": ""}), "rochdale")

    def test_place_name_in_order_in_title(self):
        """First live run, 7 Nov 2026: real Geograph titles, right and wrong."""
        import geograph_images as g
        wrong = [("Norden Road", "784 to 768 Edenfield Road, Norden"),
                 ("Rochdale House", '"Craig Lee House" 25 Church Lane, Rochdale'),
                 ("Heywood Park", "Sunset over Queen's Park Heywood"), ("Queen’s Park", "Queen's Park Road"),
                 ("Rochdale Library", "Former library, The Esplanade, Rochdale")]
        right = [("St Andrew’s Church", "St Andrew's Parish Church, Dearnley"), ("Drake Street", "Rochdale, Drake Street"),
                 ("Jubilee Park", "Bandstand, Jubilee Park, Middleton"), ("Bury Old Road", "Bury Old Road. Heywood"),
                 ("Rochdale AFC", "Spotland, the home of Rochdale AFC"),
                 ("Manchester Road", "Rochdale Canal, Manchester Road Bridge")]
        for subject, title in wrong:
            self.assertFalse(g.title_matches(subject, title), (subject, title))
        for subject, title in right:
            self.assertTrue(g.title_matches(subject, title), (subject, title))

    def test_no_key_no_search(self):
        import geograph_images as g
        with patch.dict(os.environ, {"GEOGRAPH_API_KEY": ""}):
            self.assertEqual(g.search("Drake Street", {"area": "rochdale"}), [])

    def test_geograph_photo_used_and_credited(self):
        import tempfile
        import image_hierarchy as ih
        import geograph_images as g
        root = Path(tempfile.mkdtemp())
        (root / "assets/img/cards").mkdir(parents=True)
        story = {"slug": "homes", "title": "Plans approved for 27 affordable homes", "category": "environment",
                 "area": "rochdale", "content_html": "<p>The homes will be built on Drake Street.</p>",
                 "image_url": "", "image_status": "place-generated-card"}
        row = g.parse_rss(self.RSS)[0]
        def fake_download(url, target, timeout):
            Image.new("RGB", (640, 480), "grey").save(target)
            return True
        with patch.dict(os.environ, {"GEOGRAPH_API_KEY": "k"}), \
             patch.object(ih, "commons_search", return_value={"status": "searched", "pages": []}), \
             patch.object(g, "search", return_value=[row]), \
             patch("repair_generated_with_commons.download", side_effect=fake_download):
            self.assertEqual(ih.choose_image(story, root), "commons")
        self.assertEqual(story["image_backfill_method"], "geograph")
        self.assertEqual(story["image_credit"], "Jane Smith / Geograph (CC BY-SA 2.0)")
        self.assertEqual(story["image_credit_url"], "https://www.geograph.org.uk/photo/123")
        self.assertTrue(story["image_alt"].startswith("File image: Drake Street."))


class TownPhotoTests(unittest.TestCase):
    """Editor's decision, 7 Nov 2026: stories naming no place get a varied
    Geograph photo of their town; never crime, police, sensitive, sponsored."""

    def pool(self, n):
        return [{"title": f"Market Street {i}, Heywood", "page_url": f"https://www.geograph.org.uk/photo/{i}",
                 "author": "A N Other", "thumb": f"https://s0.geograph.org.uk/x/{i}_ab_120x90.jpg"} for i in range(n)]

    def test_photos_are_varied(self):
        import geograph_images as g
        pool, used = self.pool(3), {}
        for slug in ("a", "b", "c", "d", "e", "f"):
            row = g.pick_town_photo(pool, used, slug)
            used.setdefault(row["page_url"], []).append(slug)
        self.assertTrue(all(len(v) <= g.TOWN_PHOTO_MAX_USES for v in used.values()))
        self.assertIsNone(g.pick_town_photo(pool, used, "g"))           # pool full: the card stays
        self.assertEqual(g.pick_town_photo(pool, used, "a")["page_url"],
                         next(u for u, s in used.items() if "a" in s))  # a story keeps its photo

    def test_only_scenes_not_private_houses(self):
        import geograph_images as g
        self.assertTrue(g.suitable_town_photo("Market Street, Heywood", "heywood"))
        self.assertTrue(g.suitable_town_photo("St Luke's Church", "heywood"))
        self.assertFalse(g.suitable_town_photo("784 to 768 Edenfield Road, Norden", "norden"))
        self.assertFalse(g.suitable_town_photo("No. 12 and its garden", "heywood"))

    def test_town_photo_set_and_never_on_crime(self):
        import tempfile
        import image_hierarchy as ih
        import geograph_images as g
        root = Path(tempfile.mkdtemp())
        (root / "assets/img/cards").mkdir(parents=True)
        def fake_download(url, target, timeout):
            Image.new("RGB", (640, 480), "grey").save(target)
            return True
        story = {"slug": "awards", "title": "Volunteers honoured at awards night", "category": "community",
                 "area": "heywood", "content_html": "<p>Volunteers were thanked.</p>",
                 "image_url": "", "image_status": "place-generated-card"}
        crime = dict(story, slug="theft", title="Man charged after theft", category="crime")
        with patch.dict(os.environ, {"GEOGRAPH_API_KEY": "k"}), \
             patch.object(g, "town_pool", return_value=self.pool(5)), \
             patch("repair_generated_with_commons.download", side_effect=fake_download):
            self.assertEqual(ih.choose_image(story, root), "town-photo")
            self.assertEqual(ih.choose_image(crime, root), "place-card")
        self.assertEqual(story["image_status"], "town-file-photo")
        self.assertEqual(story["image_alt"], "File photo: Heywood. Not a photograph of this event.")
        self.assertEqual(story["image_credit"], "A N Other / Geograph (CC BY-SA 2.0)")
        self.assertNotIn("town", crime["image_url"])

    def test_note_is_visible_in_every_caption(self):
        """7 Nov 2026 review: the file-photo note was only in alt text."""
        import generate_pages as gp
        import archive_quality as aq
        story = {"title": "Volunteers honoured", "image_status": "town-file-photo", "image_backfill_method": "geograph-town",
                 "image_alt": "File photo: Heywood. Not a photograph of this event.",
                 "image_credit": "A N Other / Geograph (CC BY-SA 2.0)", "image_credit_url": "https://www.geograph.org.uk/photo/1",
                 "image_license_url": "https://creativecommons.org/licenses/by-sa/2.0/"}
        markup = gp.hero_image_markup(story, "/assets/img/cards/x-town-photo.jpg")
        caption = markup.split("<figcaption", 1)[1]
        self.assertIn("File photo: Heywood. Not a photograph of this event.", caption)
        self.assertIn("A N Other / Geograph (CC BY-SA 2.0)", caption)
        self.assertIn("Not a photograph of this event.", aq._image_note_html(story))
        own = dict(story, image_status="editorial-photo", image_backfill_method="manual-editorial-photo",
                   image_alt="Volunteers at the awards")
        self.assertNotIn("Not a photograph", gp.hero_image_markup(own, "/assets/img/cards/own.jpg"))

    def test_sensitive_from_the_text_gets_no_place_photo(self):
        """A story the scraper marked sensitive from its source text."""
        import image_hierarchy as ih
        story = {"slug": "s", "title": "Family thanks community", "category": "community", "area": "heywood",
                 "content_html": "<p>They gathered at Heywood Library.</p>", "sensitive_story": True}
        self.assertFalse(ih.town_photo_allowed(story))
        self.assertEqual(ih.subject_for(story), "")
        self.assertEqual(ih.subject_for(dict(story, sensitive_story=False)), "Heywood Library")

    def test_town_photo_never_becomes_an_editor_photo(self):
        """On a manual article a town photo stays a pipeline fallback."""
        import tempfile
        import ensure_article_images as images
        root = Path(tempfile.mkdtemp())
        (root / "assets/img/cards").mkdir(parents=True)
        Image.effect_noise((800, 500), 64).convert("RGB").save(root / "assets/img/cards/abcd-town-photo.jpg", quality=95)
        story = {"slug": "own", "title": "Volunteers honoured", "manual_article": True, "editorial_lock": True,
                 "source_kind": "editorial", "image_url": "assets/img/cards/abcd-town-photo.jpg",
                 "image_status": "town-file-photo", "image_backfill_method": "geograph-town"}
        self.assertFalse(images.existing_meaningful_image(story, root))
        self.assertEqual(story["image_status"], "town-file-photo")

    def test_archive_read_back_keeps_the_note_and_never_stacks_it(self):
        """7 Nov 2026: archived pages lost the note (247 pages) because the
        read-back dropped alt text and image kind; the note must also never be
        read back into the credit (as 'Image source' once stacked 106 times)."""
        import tempfile
        import archive_quality as aq
        root = Path(tempfile.mkdtemp())
        (root / "articles").mkdir()
        (root / "articles.json").write_text("[]")
        real = Path(__file__).resolve().parent.parent / "articles"
        page = next(p for p in sorted(real.glob("*.html")) if "article-hero-image" in p.read_text(encoding="utf-8"))
        html_text = page.read_text(encoding="utf-8")
        figure = ('<figure class="article-hero-image"><img src="/assets/img/cards/ab12-town-photo.jpg" '
                  'alt="File photo: Heywood. Not a photograph of this event." loading="eager"><figcaption>'
                  '<span class="article-image-note">File photo: Heywood. Not a photograph of this event.</span> '
                  'A N Other / Geograph (CC BY-SA 2.0) <a href="https://www.geograph.org.uk/photo/1" '
                  'rel="noopener noreferrer">Image source</a></figcaption></figure>')
        import re as _re
        html_text = _re.sub(r'<figure\b[^>]*class=["\']article-hero-image["\'][^>]*>.*?</figure>', lambda _: figure, html_text,
                            count=1, flags=_re.S)
        html_text = _re.sub(r'(<meta\b[^>]*property=["\']og:image["\'][^>]*content=["\']).*?(["\'])',
                            lambda m: m.group(1) + "https://rochdaledaily.co.uk/assets/img/cards/ab12-town-photo.jpg" + m.group(2),
                            html_text, count=1)
        (root / "articles" / page.name).write_text(html_text, encoding="utf-8")
        row = next(r for r in aq.scan(root) if r["slug"] == page.stem)
        self.assertEqual(row["image_status"], "town-file-photo")
        self.assertEqual(row["image_alt"], "File photo: Heywood. Not a photograph of this event.")
        self.assertEqual(row["image_credit"], "A N Other / Geograph (CC BY-SA 2.0)")
        self.assertIn("Not a photograph of this event.", aq._image_note_html(row))

    def test_facebook_posts_town_photos(self):
        """Editor, 7 Nov 2026: a town photo is part of the article, so it posts."""
        import post_facebook_article as fb
        story = {"image_url": "assets/img/cards/abcd-town-photo.jpg", "image_status": "town-file-photo"}
        self.assertTrue(fb.has_story_photo(story, fb.image_usage([story])))


if __name__ == "__main__":
    unittest.main()

