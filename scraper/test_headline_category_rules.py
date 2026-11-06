"""Headline category rules (6 Nov 2026).

Measured on the newest 120 stories: about 1 in 8 was misfiled because the
text scored only one or two incidental words, so the rewrite's own guess
stood. The headline names what happened, so it decides first for these cases.
Run directly: PYTHONPATH=scraper python scraper/test_headline_category_rules.py
"""
from __future__ import annotations

import unittest

import frontpage_pipeline as fp


class HeadlineCategoryRules(unittest.TestCase):
    def check(self, title: str, expected: str) -> None:
        self.assertEqual(fp.headline_category_rule(title), expected, title)

    def test_live_misfiles_are_corrected(self) -> None:
        self.check("Resident escapes fire at Lonsdale Court sheltered housing in Middleton", "news")
        self.check("Three-year-old boy remains critical in hospital after incident at Middleton nursery", "news")
        self.check("Patrick Whelan, 62, dies in roadside work incident in Rochdale", "news")
        self.check("Banned driver leads police on high-speed chase through Rochdale", "crime")
        self.check("Rochdale Council awards contract for Queen's Park SEND improvement project", "business")
        self.check("Middleton council completes purchase of Warwick Mill to boost regeneration", "business")
        self.check("Rochdale and Bury see significant increases in driving test pass rates", "transport")

    def test_exclusions(self) -> None:
        # A coroner's finding is not a criminal case.
        self.check("Inquest Jury Clears Police Following Fatal High-Speed Chase in Rochdale", "")
        # Collisions stay traffic; moorland and waste-site fires stay environment.
        self.check("Man dies after crash on M62", "")
        self.check("Moorland blaze near Watergrove", "")
        self.check("Investigation Launched After Fire at Illegal Waste Site in Rochdale", "")
        # Not an emergency at all.
        self.check("Ignite Fire Festival returns to Rochdale Town Hall Square", "")
        self.check("Community efforts revive historic Lodge Mill after devastating fire", "")

    def test_rule_decides_over_text_scoring(self) -> None:
        article = {
            "title": "Resident escapes fire at Lonsdale Court sheltered housing in Middleton",
            "content_html": "<p>Local families were supported by Rochdale Homes.</p>",
            "category": "community",
        }
        fp.clear_category_cache()
        self.assertEqual(fp.article_category(article), "news")

    def test_editorial_lock_still_wins(self) -> None:
        article = {
            "title": "Resident escapes fire at Lonsdale Court",
            "category": "community",
            "editorial_lock": True,
        }
        self.assertEqual(fp.apply_category_rules(dict(article))["category"], "community")


if __name__ == "__main__":
    unittest.main()
