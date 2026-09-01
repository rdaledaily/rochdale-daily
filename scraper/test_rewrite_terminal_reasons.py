"""Every None from request_article must carry its terminal reason to on_skip,
exactly once, so scraper_status.json can tell an OpenAI outage from a correct
editorial-gate rejection from a quality gate the model could not satisfy."""
import json
import logging
import unittest
from types import SimpleNamespace
from unittest import mock

import editorial_upgrade as eu


class FakeClient:
    def __init__(self, behaviour):
        self.behaviour = behaviour  # callable(attempt) -> dict draft or raises
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        attempt = self.calls
        self.calls += 1
        draft = self.behaviour(attempt)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(draft)))])


def run(client, issues_by_attempt):
    """Drive request_article with quality_issues stubbed per attempt."""
    skips = []
    calls = {"n": 0}

    def fake_quality(draft, source_text, source_kind=""):
        i = min(calls["n"], len(issues_by_attempt) - 1)
        calls["n"] += 1
        return list(issues_by_attempt[i])

    with mock.patch.object(eu, "quality_issues", fake_quality), \
         mock.patch.object(eu, "normalise_draft", lambda d: d):
        result = eu.request_article(
            client=client, model="test", schema={}, candidate=SimpleNamespace(source_url="u", source_name="s"),
            source_records=[], social_context=[], source_text="x " * 200, sensitive=False,
            right_to_reply_email="n@x", logger=logging.getLogger("t"), on_skip=skips.append,
        )
    return result, skips


DRAFT = {"title": "t", "excerpt": "e", "paragraphs": ["p"]}


class RewriteSkipReasons(unittest.TestCase):
    def test_all_api_attempts_fail(self):
        client = FakeClient(lambda a: (_ for _ in ()).throw(TimeoutError("slow")))
        result, skips = run(client, [[]])
        self.assertIsNone(result)
        self.assertEqual(client.calls, 4)
        self.assertEqual(skips, ["OpenAI: all 4 attempts failed (TimeoutError)"])

    def test_editorial_gate_rejection_is_terminal_and_named(self):
        client = FakeClient(lambda a: DRAFT)
        result, skips = run(client, [["REJECTED_LISTING: this is a directory page"]])
        self.assertIsNone(result)
        self.assertEqual(client.calls, 1)
        self.assertEqual(skips, ["editorial gate: REJECTED_LISTING"])

    def test_integrity_issue_after_four_repairs(self):
        client = FakeClient(lambda a: DRAFT)
        issue = "Ground the report more clearly in the sources"
        result, skips = run(client, [[issue]] * 4)
        self.assertIsNone(result)
        self.assertEqual(client.calls, 4)
        self.assertEqual(len(skips), 1)
        self.assertTrue(skips[0].startswith("quality gate after 4 repairs: Ground the report"))

    def test_style_only_issues_still_publish_without_skip(self):
        client = FakeClient(lambda a: DRAFT)
        result, skips = run(client, [["Tighten the report to fewer than 110 body words."]] * 4)
        self.assertIsNotNone(result)
        self.assertEqual(skips, [])

    def test_clean_draft_first_time(self):
        client = FakeClient(lambda a: DRAFT)
        result, skips = run(client, [[]])
        self.assertEqual(result, DRAFT)
        self.assertEqual(skips, [])

    def test_no_callback_is_safe(self):
        client = FakeClient(lambda a: (_ for _ in ()).throw(RuntimeError("x")))
        with mock.patch.object(eu, "quality_issues", lambda *a, **k: []), mock.patch.object(eu, "normalise_draft", lambda d: d):
            result = eu.request_article(
                client=client, model="test", schema={}, candidate=SimpleNamespace(source_url="u"),
                source_records=[], social_context=[], source_text="x", sensitive=False,
                right_to_reply_email="n@x", logger=logging.getLogger("t"),
            )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
