"""All Rochdale borough townships are local; publisher intake must not require Rochdale town.

PYTHONPATH=scraper python scraper/test_borough_publisher_discovery.py
"""
import re
import unittest
from pathlib import Path

import locality_rules
import run_fast_local_pipeline as fast
import scraper as core


class BoroughPublisherCoverage(unittest.TestCase):
    def test_middleton_news_is_rochdale_borough_news_from_three_publishers(self):
        cases=(
            ("Rochdale Times","https://www.rochdaletimes.co.uk/news/middleton-school","School funding announced in Middleton, Greater Manchester"),
            ("Manchester Evening News — Middleton","https://www.manchestereveningnews.co.uk/news/greater-manchester-news/middleton-town-centre-4000","Middleton town centre road closure announced"),
            ("Roch Valley Radio","https://www.rochvalleyradio.com/news-features/142/news/100/middleton-community","New Middleton town centre festival announced"),
        )
        for source,url,title in cases:
            with self.subTest(source=source):
                self.assertTrue(locality_rules.is_local(title,source,url))
                self.assertFalse(locality_rules.has_disqualifying_evidence(title,source,url))
                self.assertEqual(locality_rules.detect_area(title,"",source,url),"middleton")

    def test_heywood_and_littleborough_also_borough_news(self):
        for title,place in (
            ("New parking restrictions announced in Heywood","heywood"),
            ("Road works in Littleborough town centre","littleborough"),
        ):
            with self.subTest(place=place):
                self.assertTrue(locality_rules.is_local(
                    title,"Manchester Evening News",
                    "https://www.manchestereveningnews.co.uk/news/greater-manchester-news/example"))
                self.assertEqual(locality_rules.detect_area(title),place)

    def test_not_an_open_licence_to_publish_other_middletons(self):
        self.assertFalse(locality_rules.is_local(
            "Crash in Middleton, Nova Scotia on Highway 101",
            "Unknown Publisher","https://example.net/local/story"))

    def test_radio_discovery_pattern_matches_real_article_structure(self):
        fast.configure_sources()
        source=next(x for x in core.DISCOVERY_PAGES
                    if x.get("name")=="Roch Valley Radio Local News")
        self.assertEqual(source["url"],"https://www.rochvalleyradio.com/")
        self.assertTrue(re.search(source["link_pattern"],"/news-features/142/community/908/a-local-story"))
        self.assertFalse(re.search(source["link_pattern"],"/news/local-news/"))

    def test_competitors_are_sources_not_blocked_by_name(self):
        for name,url in (
            ("Rochdale Times","https://www.rochdaletimes.co.uk/news/middleton"),
            ("Roch Valley Radio","https://www.rochvalleyradio.com/news-features/1/news/2/middleton"),
            ("Manchester Evening News","https://www.manchestereveningnews.co.uk/news/greater-manchester-news/example"),
        ):
            self.assertFalse(core.source_is_denied(name,url))


if __name__=="__main__":
    unittest.main()
