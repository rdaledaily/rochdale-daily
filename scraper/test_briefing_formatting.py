#!/usr/bin/env python3
"""The Morning Briefing keeps its structure and punctuation all the way to the page.

Until 20 October 2026 the manual-article loader rebuilt every briefing from its
tag-stripped body, so the published briefing was one unpunctuated paragraph in
which each headline ran into its area and summary.
"""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import daily_briefing as db  # noqa: E402
import manual_articles as ma  # noqa: E402

BRIEFING_HTML = (
    "<p>2 new stories in the Rochdale borough since yesterday evening.</p><h2>The stories</h2><ul>"
    '<li><a href="/articles/roadworks-greenhill-road.html"><strong>Roadworks on Greenhill Road</strong></a>'
    ' <span class="brief-area">Middleton</span><br>The council says work starts on 2 November.</li>'
    '<li><a href="/articles/school-applications.html"><strong>School applications close</strong></a>'
    ' <span class="brief-area">Rochdale</span><br>Families should list five preferences</li></ul>'
    "<p><strong>Weather:</strong> Cloudy 13°C in Rochdale today.</p>"
    '<p class="brief-foot">The Morning Briefing is published every day at 9am. Got a story? '
    '<a href="/contact.html">Tell the newsdesk</a>.</p>'
)


def entry(html=BRIEFING_HTML, route="daily-briefing"):
    return {"id": "briefing-morning-briefing-19-october-2026", "slug": "morning-briefing-19-october-2026",
            "title": "Morning Briefing: Monday 19 October 2026", "content_html": html,
            "body": db.plain_text(html), "published_at": "2026-10-19T08:00:00Z",
            "publication_route": route, "briefing_slot": "morning"}


class BriefingFormattingTests(unittest.TestCase):
    def test_structure_survives_the_loader(self):
        record = ma._normalise(entry(), datetime.now(timezone.utc))
        self.assertEqual(record["content_html"], BRIEFING_HTML)
        self.assertEqual(record["briefing_slot"], "morning")

    def test_other_html_is_never_trusted(self):
        for bad in ('<p>Hi</p><script>alert(1)</script>', '<p><a href="https://evil.test">x</a></p>',
                    '<p onclick="x()">Hi</p>', '<p><img src=x></p>'):
            self.assertEqual(ma._briefing_html(entry(bad)), "", bad)
        # Only the briefing route may use it at all.
        self.assertEqual(ma._briefing_html(entry(route="editorial")), "")

    def test_plain_text_is_punctuated_sentences(self):
        text = db.plain_text(BRIEFING_HTML)
        self.assertIn("Roadworks on Greenhill Road (Middleton). The council says work starts on 2 November.", text)
        self.assertIn("School applications close (Rochdale). Families should list five preferences.", text)
        self.assertIn("The stories:", text)
        self.assertNotIn("..", text)
        # Each block is its own paragraph.
        self.assertGreaterEqual(text.count("\n\n"), 5)

    def test_summaries_end_on_a_whole_sentence(self):
        text = ("The council advises families to list five preferences and apply by Saturday 31 October. "
                "Late applications are considered only after National Offer Day on 1 March, which can considerably "
                "reduce the chance of a place at a preferred school for many families across the borough.")
        self.assertEqual(db.whole_sentences(text),
                         "The council advises families to list five preferences and apply by Saturday 31 October.")
        self.assertEqual(db.whole_sentences("Short summary without a stop"), "Short summary without a stop.")
        long_one = "word " * 80
        self.assertTrue(db.whole_sentences(long_one).endswith("…"))

    def test_plain_text_fallback_makes_paragraphs(self):
        record = ma._normalise({**entry(), "content_html": "", "publication_route": "editorial"},
                               datetime.now(timezone.utc))
        self.assertGreaterEqual(record["content_html"].count("<p>"), 5)


if __name__ == "__main__":
    unittest.main()
