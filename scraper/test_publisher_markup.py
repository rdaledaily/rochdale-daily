#!/usr/bin/env python3
"""Every page declares the full publisher, and article places sit inside Rochdale borough."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import publisher_markup as pm  # noqa: E402


def page(data):
    return f'<head><script type="application/ld+json">{json.dumps(data)}</script></head>'


def blocks(html):
    import re
    return [json.loads(b) for b in re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S)]


class PublisherMarkupTests(unittest.TestCase):
    def test_thin_publisher_becomes_full_publisher(self):
        html = pm.enrich_text(page({"@type": "NewsArticle", "publisher": {
            "@type": "NewsMediaOrganization", "name": "Rochdale Daily", "url": "https://rochdaledaily.co.uk"}}))
        pub = blocks(html)[0]["publisher"]
        for key in ("publishingPrinciples", "correctionsPolicy", "ethicsPolicy", "actionableFeedbackPolicy", "masthead"):
            self.assertTrue(pub[key].startswith("https://rochdaledaily.co.uk/"), key)

    def test_publisher_id_is_kept(self):
        html = pm.enrich_text(page({"@graph": [{"@type": "NewsMediaOrganization", "@id": "https://rochdaledaily.co.uk/#publisher",
                                                "name": "Rochdale Daily"}]}))
        self.assertEqual(blocks(html)[0]["@graph"][0]["@id"], "https://rochdaledaily.co.uk/#publisher")

    def test_place_is_inside_the_borough(self):
        html = pm.enrich_text(page({"@type": "NewsArticle", "contentLocation": {"@type": "Place", "name": "Heywood"}}))
        loc = blocks(html)[0]["contentLocation"]
        self.assertEqual(loc["name"], "Heywood")
        self.assertEqual(loc["containedInPlace"]["name"], "Metropolitan Borough of Rochdale")

    def test_idempotent_and_other_publishers_untouched(self):
        once = pm.enrich_text(page({"@type": "NewsArticle", "contentLocation": {"@type": "Place", "name": "Milnrow"},
                                    "isBasedOn": {"@type": "NewsMediaOrganization", "name": "Manchester Evening News"}}))
        self.assertEqual(pm.enrich_text(once), once)
        self.assertEqual(blocks(once)[0]["isBasedOn"], {"@type": "NewsMediaOrganization", "name": "Manchester Evening News"})

    def test_unparseable_block_left_alone(self):
        broken = '<script type="application/ld+json">{not json</script>'
        self.assertEqual(pm.enrich_text(broken), broken)


if __name__ == "__main__":
    unittest.main()
