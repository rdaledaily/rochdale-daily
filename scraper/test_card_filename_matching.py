#!/usr/bin/env python3
import unittest
from pathlib import Path

from ensure_article_images import filename_match_score


class CardFilenameMatchingTests(unittest.TestCase):
    def score(self, title: str, filename: str, **extra) -> int:
        article = {"title": title, "slug": title, **extra}
        return filename_match_score(article, Path(filename))

    def test_single_distinctive_word_matches_headline(self):
        self.assertGreater(
            self.score("Woman poisoned in Rochdale incident", "poisoned.jpeg"),
            0,
        )

    def test_multiword_filename_matches_phrase_with_underscores(self):
        self.assertGreater(
            self.score("2 men taken to hospital after crash", "taken_to_hospital.jpeg"),
            0,
        )

    def test_leading_the_is_ignored(self):
        self.assertGreater(
            self.score("Resilient Roach Project launches new scheme", "the_resilient_roach.jpg"),
            0,
        )

    def test_multiword_specific_match_beats_broad_single_word(self):
        article = {"title": "2 men taken to hospital after crash", "slug": "2-men-taken-to-hospital-after-crash"}
        specific = filename_match_score(article, Path("taken_to_hospital.jpeg"))
        broad = filename_match_score(article, Path("hospital.jpeg"))
        self.assertGreater(specific, broad)

    def test_excerpt_can_match_when_headline_does_not(self):
        article = {
            "title": "Emergency incident investigated in Rochdale",
            "slug": "emergency-incident-investigated-rochdale",
            "excerpt": "A resident was poisoned and taken for treatment.",
        }
        self.assertGreater(filename_match_score(article, Path("poisoned.jpeg")), 0)

    def test_generic_town_filename_is_not_used_alone(self):
        self.assertLess(
            self.score("Council announces new Rochdale scheme", "rochdale.jpg"),
            0,
        )


if __name__ == "__main__":
    unittest.main()