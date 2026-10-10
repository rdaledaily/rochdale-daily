"""Tests for exact-field official council notice rewriting.

PYTHONPATH=scraper python scraper/test_structured_official_notices.py
"""
from __future__ import annotations

import unittest
from claim_evidence import evidence_issues
from prepare_publication_evidence import enrich
from structured_official_notices import verified_notice

BRANDLEHOW_URL = "https://www.rochdale.gov.uk/directory-record/2580/brandlehow-drive-roadworks-in-middleton-on-12-october-2026"
BRANDLEHOW_SOURCE = (
    "Brandlehow Drive, roadworks in Middleton on 12 October 2026 | Rochdale Borough Council "
    "Search Search View menu Accessibility and translate Brandlehow Drive, roadworks in Middleton on 12 October 2026 "
    "Area Middleton Expected start and finish 8.30am–4pm on Monday, 12 October 2026 "
    "Reason To carry out maintenance on the substation. "
    "Restriction and location The part of Brandlehow Drive between the junctions of Latrigg Crescent and Lingholme Drive "
    "will be temporarily closed. Alternative route Latrigg Crescent, Windermere Road and Brandlehow Drive. "
    "Organised by Rochdale Borough Council Directions Get directions to Brandlehow Drive on Google Maps "
    "View roadworks on a map Was this page helpful?"
)
RUGBY_URL = "https://www.rochdale.gov.uk/directory-record/2623/rugby-road-temporary-prohibition-of-waiting-in-rochdale-from-15-october-2026"
RUGBY_SOURCE = (
    "Rugby Road, temporary prohibition of waiting in Rochdale from 15 October 2026 | Rochdale Borough Council "
    "Search Search View menu Accessibility and translate Rugby Road, temporary prohibition of waiting in Rochdale from 15 October 2026 "
    "Area Rochdale Expected start and finish 12midnight on Thursday, 15 October 2026–11.59pm on Monday, 19 October 2026 "
    "Reason To work on road markings. Restriction and location Part of the westerly side of Rugby Road will have a temporary "
    "restriction of no waiting at any time. The restriction will start at the junction with Yorkshire Street and end 190 metres "
    "along the road. Organised by Rochdale Borough Council Directions Get directions to Rugby Road on Google Maps "
    "View roadworks on a map Was this page helpful?"
)


def article(url, source, headline="Invented generic headline"):
    return {
        "slug":"test-council-notice","source_url":url,
        "source_name":"Rochdale Borough Council","source_kind":"primary_data",
        "title":headline,"category":"traffic","area":"rochdale",
        "content_html":"<p>This generic draft contains unwarranted claims about fines and traffic jams.</p>",
        "published_at":"2026-10-10T20:20:00Z",
        "evidence_sources":[{"url":url,"captured_text":source}],
    }


class OfficialNoticeRewrites(unittest.TestCase):
    def test_brandlehow_grounded_not_substation_assumptions(self):
        a=article(BRANDLEHOW_URL,BRANDLEHOW_SOURCE)
        self.assertTrue(verified_notice(a))
        self.assertIn("Brandlehow Drive",a["title"])
        self.assertIn("8.30am–4pm",a["content_html"])
        self.assertIn("Latrigg Crescent",a["content_html"])
        self.assertIn("substation",a["content_html"])
        self.assertNotIn("fines",a["content_html"])
        self.assertNotIn("road safety",a["content_html"])
        self.assertEqual(a["verification_method"],"structured-official-directory-record")
        self.assertTrue(a["source_review_verified"])
        self.assertTrue(a["primary_source_verified"])
        self.assertEqual(evidence_issues(a),[])
        self.assertGreater(len(a["content_html"].split()),50)

    def test_rugby_road_cannot_invent_a_diversion(self):
        a=article(RUGBY_URL,RUGBY_SOURCE)
        self.assertTrue(verified_notice(a))
        self.assertIn("road markings",a["content_html"])
        self.assertIn("190 metres",a["content_html"])
        self.assertIn("does not list a separate alternative route",a["content_html"])
        self.assertNotIn("fines",a["content_html"])
        self.assertEqual(evidence_issues(a),[])

    def test_enrich_calls_deterministic_evidence_no_ai_model(self):
        a=article(BRANDLEHOW_URL,BRANDLEHOW_SOURCE)
        a.pop("evidence_sources")
        a.pop("ingested_at",None)
        def fake_fetch(row):
            return {"evidence_sources":[{"url":BRANDLEHOW_URL,"captured_text":BRANDLEHOW_SOURCE}]}
        def no_ai(_):
            self.fail("The exact, official structured notice must not call the AI verifier")
        self.assertGreater(enrich([a],fake_fetch,no_ai),0)
        self.assertTrue(a["primary_source_verified"])

    def test_never_override_a_nonofficial_publisher(self):
        a=article("https://www.rochdaletimes.co.uk/story",BRANDLEHOW_SOURCE)
        self.assertFalse(verified_notice(a))
        self.assertFalse(a.get("source_review_verified",False))

    def test_reject_invalid_organiser_or_missing_location(self):
        for source in (
            BRANDLEHOW_SOURCE.replace("Organised by Rochdale Borough Council","Organised by Private Contractor"),
            BRANDLEHOW_SOURCE.replace("Area Middleton","Area Nova Scotia"),
            BRANDLEHOW_SOURCE.replace("Restriction and location","Unknown section"),
            BRANDLEHOW_SOURCE.replace("The part of Brandlehow Drive", "The part of Another Road"),
        ):
            a=article(BRANDLEHOW_URL,source)
            self.assertFalse(verified_notice(a))
            self.assertIn("unwarranted",a["content_html"])
            self.assertFalse(a.get("primary_source_verified",False))

    def test_title_and_labelled_area_must_agree(self):
        # Both values are individually valid borough locations, but disagree.
        # The conflict must never be certified as a primary source.
        mismatched=BRANDLEHOW_SOURCE.replace("Area Middleton", "Area Rochdale")
        a=article(BRANDLEHOW_URL,mismatched)
        self.assertFalse(verified_notice(a))
        self.assertFalse(a.get("source_review_verified",False))
        self.assertIn("unwarranted",a["content_html"])

    def test_title_without_location_or_multiple_locations_rejected(self):
        for changed in (
            BRANDLEHOW_SOURCE.replace("roadworks in Middleton", "roadworks at the borough"),
            BRANDLEHOW_SOURCE.replace("roadworks in Middleton", "roadworks in Middleton and in Rochdale"),
        ):
            a=article(BRANDLEHOW_URL,changed)
            self.assertFalse(verified_notice(a))

    def test_prevent_malicious_arbitrary_primary_url(self):
        a=article(
            "https://www.rochdale.gov.uk.evil.example/directory-record/2580/roadworks",
            BRANDLEHOW_SOURCE
        )
        self.assertFalse(verified_notice(a))


if __name__ == "__main__":
    unittest.main()
