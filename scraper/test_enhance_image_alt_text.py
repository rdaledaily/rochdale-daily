#!/usr/bin/env python3
import unittest

import enhance_image_alt_text as alt


class ImageAltEnhancementTests(unittest.TestCase):
    def test_article_hero_gets_headline_alt(self):
        page = '''<html><body><h1>Lift out at Derker Tram Stop</h1><figure class="article-hero-image"><img src="/assets/img/cards/tram.jpg" alt="" loading="eager"></figure></body></html>'''
        updated = alt.enhance_article_html(page)
        self.assertIn('alt="Lift out at Derker Tram Stop"', updated)

    def test_existing_article_alt_is_preserved(self):
        page = '''<h1>Example story</h1><figure class="article-hero-image"><img src="photo.jpg" alt="A tram at Derker"></figure>'''
        self.assertEqual(alt.enhance_article_html(page), page)

    def test_homepage_card_gets_its_own_headline_alt(self):
        page = '''<article class="news-card static-latest-card"><a><div><img src="photo.jpg" alt="" loading="lazy"></div><h3 class="card-headline">Road closes after water main burst</h3></a></article>'''
        updated = alt.enhance_homepage_html(page)
        self.assertIn('alt="Road closes after water main burst"', updated)

    def test_multiple_cards_receive_matching_alt_text(self):
        page = '''<article class="news-card"><img src="one.jpg" alt=""><h3 class="card-headline">First story</h3></article><article class="news-card weekly-local-card"><img src="two.jpg" alt=""><h3 class="card-headline">Second story</h3></article>'''
        updated = alt.enhance_homepage_html(page)
        self.assertIn('src="one.jpg" alt="First story"', updated)
        self.assertIn('src="two.jpg" alt="Second story"', updated)

    def test_html_entities_are_decoded_then_safely_escaped(self):
        page = '''<h1>Council says A &amp; B's plan is &quot;ready&quot;</h1><figure class="article-hero-image"><img src="photo.jpg" alt=""></figure>'''
        updated = alt.enhance_article_html(page)
        self.assertIn('alt="Council says A &amp; B&#x27;s plan is &quot;ready&quot;"', updated)

    def test_repeated_run_is_idempotent(self):
        page = '''<h1>Example story</h1><figure class="article-hero-image"><img src="photo.jpg" alt=""></figure>'''
        once = alt.enhance_article_html(page)
        twice = alt.enhance_article_html(once)
        self.assertEqual(once, twice)


if __name__ == "__main__":
    unittest.main()
