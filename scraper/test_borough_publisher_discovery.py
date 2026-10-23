"""All Rochdale borough townships are local; publisher intake must not require Rochdale town.

PYTHONPATH=scraper python scraper/test_borough_publisher_discovery.py
"""
import re
import unittest
from pathlib import Path
from unittest.mock import patch

import locality_rules
import run_fast_local_pipeline as fast
import scraper as core


class BoroughPublisherCoverage(unittest.TestCase):
    def test_radio_requires_article_level_locality(self):
        url = "https://www.rochvalleyradio.com/news-features/142/news/100/story"
        for name, source_url in (
            ("Roch Valley Radio", ""),
            ("Roch Valley Radio Local News", url),
            ("Unknown Publisher", url),
            ("rochvalleyradio.com", "https://news.google.com/rss/articles/example"),
        ):
            with self.subTest(name=name, url=source_url):
                self.assertFalse(locality_rules.source_is_trusted_local(name, source_url))
                for text in ("Library opens in Bury town centre",
                             "Police appeal after crash in Bolton",
                             "Community festival announced"):
                    self.assertFalse(core.source_text_is_local(text, name, source_url))
                    self.assertEqual(locality_rules.detect_area(text, "rochdale", name, source_url), "")
                for place in ("Rochdale", "Middleton", "Heywood", "Littleborough", "Milnrow"):
                    self.assertTrue(core.source_text_is_local(
                        f"Festival announced in {place} town centre", name, source_url))
                self.assertFalse(core.source_text_is_local(
                    "Crash in Middleton, Nova Scotia on Highway 101", name, source_url))

    def test_radio_pre_rewrite_gate_rejects_non_local_candidates(self):
        # An accepting downstream stub proves rejection happens before rewriting.
        with patch.object(core, "candidate_is_rewrite_eligible", return_value=True) as downstream:
            fast.configure_pre_rewrite_locality_gate()
            for name in ("Roch Valley Radio", "Roch Valley Radio Local News"):
                for place, expected in (("Bury", False), ("Bolton", False),
                                        ("Middleton", True), ("Heywood", True),
                                        ("Littleborough", True)):
                    candidate = core.Candidate(
                        source_name=name,
                        source_url="https://www.rochvalleyradio.com/news-features/142/news/100/story",
                        source_title=f"Festival announced in {place} town centre",
                        source_summary="Residents are invited to attend the event.",
                        source_published_at="2026-10-10T12:00:00Z",
                        area="rochdale", category="news",
                    )
                    with self.subTest(name=name, place=place):
                        downstream.reset_mock()
                        self.assertEqual(core.candidate_is_rewrite_eligible(candidate, {}), expected)
                        self.assertEqual(downstream.called, expected)

    def test_middleton_news_is_rochdale_borough_news_from_three_publishers(self):
        cases=(
            ("Rochdale Times","https://www.rochdaletimes.co.uk/news/middleton-school","School funding announced in Middleton, Greater Manchester"),
            ("Manchester Evening News — Middleton","https://www.manchestereveningnews.co.uk/news/greater-manchester-news/middleton-town-centre-4000","Middleton town centre road closure announced"),
            ("Roch Valley Radio","https://www.rochvalleyradio.com/news-features/142/news/100/middleton-community","Festival announced in Middleton town centre"),
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
        self.assertFalse(source.get("trusted_local", False))
        self.assertEqual(source["default_area"], "")
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

