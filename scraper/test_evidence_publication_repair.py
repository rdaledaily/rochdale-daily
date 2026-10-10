"""Regression tests for draft-to-publication accounting and local source evidence.

Run: PYTHONPATH=scraper python scraper/test_evidence_publication_repair.py
"""
import tempfile
import unittest
from pathlib import Path

from claim_evidence import (
    approved_evidence_source, is_local_publisher, evidence_issues,
)
from prepare_publication_evidence import enrich
from independent_fact_review import verify
from audit_published_news import audit


SOURCE="https://www.rochdaletimes.co.uk/community-plan-confirmed/"
CAPTURED=(
    "Rochdale Times reported that a community scheme was approved after "
    "a public meeting on Saturday. Organisers said the scheme opens in November."
)
QUOTE="Rochdale Times reported that a community scheme was approved after a public meeting on Saturday."


def accepted_review(row):
    return {"approved": True, "claims": [
        {"claim": "Rochdale community scheme was approved at a public meeting",
         "source_url":row["source_url"],"supporting_excerpt":QUOTE}
    ],"reasons":[]}


class PublishingRepair(unittest.TestCase):
    def test_trusted_publisher_not_misrepresented_as_official(self):
        self.assertTrue(approved_evidence_source(SOURCE))
        self.assertTrue(is_local_publisher(SOURCE))
        self.assertFalse(approved_evidence_source("https://www.rochdaletimes.co.uk.evil.test/story"))
        self.assertFalse(approved_evidence_source("http://www.rochdaletimes.co.uk/story"))
        self.assertFalse(approved_evidence_source("https://unknownpaper.example/story"))

    def test_missing_ingestion_time_is_added_before_capture_and_check(self):
        row={
            "source_url":SOURCE,"published_at":"2026-10-10T19:11:12Z",
            "title":"Community scheme approved after public meeting",
            "content_html":"<p>Rochdale Times reported that the new community scheme was approved.</p>",
        }
        def capture(article):
            self.assertTrue(article.get("ingested_at"))
            return {"evidence_sources":[{"url":SOURCE,"captured_text":CAPTURED}]}
        result=enrich([row],capture,accepted_review)
        self.assertGreater(result,0)
        self.assertTrue(row["source_review_verified"])
        self.assertFalse(row["primary_source_verified"])
        self.assertEqual(row["verification_source_type"],"attributed-publisher")
        self.assertEqual(evidence_issues(row),[])

    def test_secondary_source_not_automatically_primary_verified(self):
        row={"source_review_verified":True,"primary_source_verified":True,
             "evidence_sources":[{"url":SOURCE,"captured_text":CAPTURED}],
             "verified_claims":[{"claim":"Scheme approved at meeting",
                                 "source_url":SOURCE,"supporting_excerpt":QUOTE}]}
        self.assertTrue(evidence_issues(row))

    def test_publisher_story_requires_actual_source_quotation(self):
        row={"source_review_verified":True,"primary_source_verified":False,
             "evidence_sources":[{"url":SOURCE,"captured_text":CAPTURED}],
             "verified_claims":[{"claim":"Unverified extra event","source_url":SOURCE,
                                 "supporting_excerpt":"Invented prize winnings of three million pounds."}]}
        self.assertTrue(evidence_issues(row))

    def test_sensitive_publisher_story_needs_human(self):
        item={"title":"Urgent appeal for missing girl aged 16",
              "evidence_sources":[{"url":SOURCE,"captured_text":CAPTURED}]}
        self.assertFalse(verify(item)["approved"])
        self.assertIn("human",verify(item)["reasons"][0])

    def test_metrics_count_only_real_pages_after_gate(self):
        with tempfile.TemporaryDirectory() as t:
            pages=Path(t)
            (pages/"published-article.html").write_text("published",encoding="utf-8")
            status={"drafted_articles":[
                {"slug":"published-article","source_url":SOURCE},
                {"slug":"dropped-article","source_url":"https://www.rochdale.gov.uk/news/123"},
            ],"new_articles":2}
            articles=[{"slug":"published-article","source_url":SOURCE}]
            result=audit(status,articles,pages)
            self.assertEqual(result["new_articles"],1)
            self.assertEqual(result["draft_rewrites_created"],2)
            self.assertEqual(result["drafts_not_published"],1)
            self.assertEqual(result["publication_health"],"partial")


if __name__=="__main__":
    unittest.main()
