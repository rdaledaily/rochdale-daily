"""Alt text, tags and image metadata must never be empty on a live article."""
import unittest

import generate_pages as gp


class SeoImageMetadata(unittest.TestCase):
    def test_supplied_alt_wins(self):
        a = {"title": "Headline", "image_alt": "Jen Daker at The Hybrid Hut gym"}
        self.assertEqual(gp.image_alt_text(a, "assets/img/cards/x.jpg"), "Jen Daker at The Hybrid Hut gym")

    def test_photo_falls_back_to_headline(self):
        a = {"title": "Tram services disrupted in Rochdale this weekend"}
        self.assertEqual(gp.image_alt_text(a, "assets/img/cards/tram.jpg"), a["title"])

    def test_generated_card_is_described_as_a_card(self):
        a = {"title": "Council approves plan"}
        self.assertEqual(gp.image_alt_text(a, "assets/img/cards/x-generated-card.jpg"), "Rochdale Daily headline card: Council approves plan")

    def test_never_empty(self):
        self.assertTrue(gp.image_alt_text({}, ""))

    def test_hero_markup_carries_alt(self):
        a = {"title": "A & B <test>", "image_credit": "Photo: someone"}
        html = gp.hero_image_markup(a, "https://rochdaledaily.co.uk/assets/img/cards/p.jpg")
        self.assertIn('alt="A &amp; B &lt;test&gt;"', html)
        self.assertNotIn('alt=""', html)

    def test_tags_are_distinct_and_titled(self):
        a = {"ward": "north_heywood", "area": "heywood", "category": "crime", "tags": ["Heywood", "GMP"]}
        self.assertEqual(gp.seo_tag_list(a), ["North Heywood", "Heywood", "Crime", "GMP"])
        self.assertIn('property="article:tag" content="GMP"', gp.article_tag_markup(a))


if __name__ == "__main__":
    unittest.main()
