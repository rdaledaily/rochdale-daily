"""Unsupported names/dates/figures are cut from the story instead of binning it."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import editorial_upgrade as eu  # noqa: E402

FILLER = "The club confirmed the decision on its website and thanked supporters for their patience during a difficult run of results this season."


def draft(*paragraphs):
    return {"title": "Rochdale part ways with head coach", "excerpt": "Rochdale have parted company with their head coach.",
            "paragraphs": list(paragraphs)}


class StripUnsupportedDetails(unittest.TestCase):
    def test_name_sentence_removed_story_kept(self):
        d = draft(
            "Rochdale have parted company with their head coach after a defeat. The club is also linked with Jon Smith.",
            FILLER,
            "A search for a successor has begun. " + FILLER,
        )
        issue = ("Source fidelity: the name(s) Jon do not appear in the source. Name only people, places and "
                 "organisations the source names.")
        out = eu.strip_unsupported_details(d, [issue])
        self.assertIsNotNone(out)
        body = " ".join(out["paragraphs"])
        self.assertNotIn("Jon", body)
        self.assertIn("parted company", body)
        self.assertEqual(out["stripped_unsupported_sentences"], ["The club is also linked with Jon Smith."])

    def test_year_and_figure_terms_parsed(self):
        self.assertEqual(eu._strip_terms("Remove unsupported calendar year(s) 2016, 2027; source publication timestamps are not event dates."), ["2016", "2027"])
        self.assertEqual(eu._strip_terms("Source fidelity: the figure(s) 6, 45 do not appear in the source. Use only figures the source states."), ["6", "45"])
        self.assertEqual(eu._strip_terms("Source fidelity: the date(s) 23 November are neither stated nor implied by the source. Use only the source's dates."), ["23 November"])

    def test_figure_does_not_match_inside_other_numbers(self):
        d = draft("The scheme costs £6 million. It covers 16 streets.", FILLER, FILLER + " " + FILLER)
        out = eu.strip_unsupported_details(d, ["Source fidelity: the figure(s) 6 do not appear in the source. Use only figures the source states."])
        body = " ".join(out["paragraphs"])
        self.assertNotIn("£6 million", body)
        self.assertIn("16 streets", body)

    def test_invented_quote_still_blocks(self):
        d = draft("He said: \"We are delighted.\"", FILLER, FILLER)
        quote = "Source fidelity: these quotation(s) are not in the source word for word: We are delighted. Quote only exact source words."
        name = "Source fidelity: the name(s) Jon do not appear in the source. Name only people, places and organisations the source names."
        self.assertIsNone(eu.strip_unsupported_details(d, [quote]))
        self.assertIsNone(eu.strip_unsupported_details(d, [name, quote]))

    def test_attribution_status_copying_grounding_still_block(self):
        for issue in [
            "Source fidelity: these sentence(s) attribute statements the source does not contain: x. Remove them.",
            "Source fidelity: the draft says charged but the source does not.",
            "Rewrite the long verbatim source passage.",
            "Ground the report more clearly in the supplied facts.",
            eu.GATE_REJECTION_PREFIX + "NON_LOCAL: out of borough",
        ]:
            self.assertFalse(eu.strippable(issue), issue)

    def test_too_little_left_is_rejected(self):
        d = draft("Jon Smith was appointed.", "Jon Smith starts on Monday.")
        self.assertIsNone(eu.strip_unsupported_details(d, ["Source fidelity: the name(s) Jon do not appear in the source."]))


if __name__ == "__main__":
    unittest.main()
