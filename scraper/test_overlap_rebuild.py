"""Regressions for copied drafts and service dashboards consuming rewrite slots."""
import ast
import json
import logging
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

import editorial_upgrade as eu
from newsroom_source_policy import is_non_article_service_page


SOURCE = (
    "Rochdale Council approved 12 new homes on Drake Street on Tuesday. "
    "The development includes affordable housing and a shared garden for residents."
)
NOTES = ["Twelve homes received council approval in Rochdale.", "Drake Street is the site of the approved housing."]
DRAFT = {"title": "Housing approved in Rochdale", "excerpt": "Council approves housing.", "paragraphs": ["New homes."]}
OVERLAP = "Rewrite the long verbatim source passage."


class Client:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        payload = next(self.responses)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])


def request(client, skips):
    return eu.request_article(
        client=client, model="test", schema={}, candidate=SimpleNamespace(source_url="https://example.com/news/homes"),
        source_records=[{"url": "https://example.com/news/homes", "body_excerpt": SOURCE}],
        social_context=[{"text": "Original social prose"}], source_text=SOURCE,
        sensitive=False, right_to_reply_email="news@example.com",
        logger=logging.getLogger("test"), on_skip=skips.append,
    )


class OverlapRebuild(unittest.TestCase):
    def test_copied_draft_is_rebuilt_without_source_prose_or_previous_draft(self):
        client, skips = Client([DRAFT, DRAFT]), []
        with mock.patch.object(eu, "quality_issues", side_effect=[[OVERLAP], []]) as quality, \
             mock.patch.object(eu, "extract_fact_notes", return_value=NOTES) as extract:
            self.assertIsNotNone(request(client, skips))
        extract.assert_called_once()
        payload = json.loads(client.calls[1]["messages"][1]["content"])
        self.assertEqual(payload["verified_fact_notes"], NOTES)
        self.assertEqual(payload["source_records"], [])
        self.assertEqual(payload["social_context"], [])
        self.assertNotIn("previous_draft", payload)
        self.assertNotIn(SOURCE, json.dumps(payload))
        # The validator still receives the complete original evidence.
        self.assertEqual(quality.call_args_list[1].args[1], SOURCE)
        self.assertEqual(skips, [])

    def test_persistent_copying_still_fails_and_extraction_is_bounded(self):
        client, skips = Client([DRAFT] * 4), []
        with mock.patch.object(eu, "quality_issues", return_value=[OVERLAP]), \
             mock.patch.object(eu, "extract_fact_notes", return_value=NOTES) as extract:
            self.assertIsNone(request(client, skips))
        self.assertEqual(len(client.calls), 4)
        extract.assert_called_once()
        self.assertEqual(len(skips), 1)
        self.assertIn("long verbatim source passage", skips[0])

    def test_failed_fact_extraction_stops_without_publishing_copied_draft(self):
        client, skips = Client([DRAFT]), []
        with mock.patch.object(eu, "quality_issues", return_value=[OVERLAP]), \
             mock.patch.object(eu, "extract_fact_notes", return_value=[]):
            self.assertIsNone(request(client, skips))
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(len(skips), 1)

    def test_ordinary_style_repairs_do_not_extract_facts(self):
        client, skips = Client([DRAFT, DRAFT]), []
        with mock.patch.object(eu, "quality_issues", side_effect=[["Tighten the standfirst."], []]), \
             mock.patch.object(eu, "extract_fact_notes") as extract:
            self.assertIsNotNone(request(client, skips))
        extract.assert_not_called()
        self.assertIn("previous_draft", json.loads(client.calls[1]["messages"][1]["content"]))

    def test_real_overlap_checker_still_rejects_copied_source(self):
        self.assertTrue(eu.contains_long_verbatim_phrase(SOURCE, SOURCE))
        self.assertIn(OVERLAP, eu.quality_issues({
            "publishable": True, "title": "Council approves housing on Drake Street in Rochdale",
            "excerpt": "The housing development was approved by the council.",
            "paragraphs": [SOURCE],
        }, SOURCE))

    def test_fact_extraction_discards_unverifiable_copied_and_invented_number_notes(self):
        valid = {"fact": "Drake Street housing includes a communal garden.", "evidence": SOURCE}
        invalid = [
            {"fact": "Homes are complete.", "evidence": "The homes are complete."},
            {"fact": SOURCE, "evidence": SOURCE},
            {"fact": "The council approved 99 homes.", "evidence": SOURCE},
            {"fact": "No evidence."},
        ]
        client = Client([{"facts": invalid + [valid, valid]}])
        notes = eu.extract_fact_notes(client, "test", SOURCE, logging.getLogger("test"))
        self.assertEqual(notes, [valid["fact"]])


class ServiceDashboard(unittest.TestCase):
    def test_tracking_and_live_fragments_cannot_reopen_the_dashboard(self):
        for suffix in ("", "/", "?utm_source=search", "#live-one", "?x=1#live-two"):
            self.assertTrue(is_non_article_service_page("https://www.northernrailway.co.uk/service-updates" + suffix))

    def test_real_northern_news_and_health_news_remain_eligible(self):
        for url in (
            "https://media.northernrailway.co.uk/news/new-trains-for-rochdale",
            "https://www.northerncarealliance.nhs.uk/nca-news/hospital-update",
            "https://northernrailway.co.uk/service-updates/a-specific-notice",
            "https://northernrailway.co.uk.example.org/service-updates",
        ):
            self.assertFalse(is_non_article_service_page(url))

    def test_request_guard_spends_zero_model_calls(self):
        client, skips = Client([]), []
        result = eu.request_article(
            client=client, model="test", schema={},
            candidate=SimpleNamespace(source_url="https://www.northernrailway.co.uk/service-updates#live-old"),
            source_records=[], social_context=[], source_text=SOURCE,
            sensitive=False, right_to_reply_email="", logger=logging.getLogger("test"), on_skip=skips.append,
        )
        self.assertIsNone(result)
        self.assertEqual(client.calls, [])
        self.assertEqual(skips, ["editorial gate: REJECTED_NON_NEWS"])

    def test_dashboard_removed_from_both_collectors(self):
        tree = ast.parse(Path(__file__).with_name("scraper.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and key.value == "url" and isinstance(value, ast.Constant):
                        self.assertNotEqual(value.value, "https://www.northernrailway.co.uk/service-updates")


if __name__ == "__main__":
    unittest.main()
