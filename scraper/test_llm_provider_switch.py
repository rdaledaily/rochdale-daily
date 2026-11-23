"""LLM_PROVIDER=anthropic sends the same rewrite requests to Claude.

Same prompts, schema and gates; only the endpoint, key, model and the
request details Claude's OpenAI-compatible endpoint rejects are changed.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import editorial_upgrade as eu  # noqa: E402

LIMIT_KEYS = set(eu._CLAUDE_LIMIT_WORDS)


def _walk(node, path=""):
    if isinstance(node, dict):
        for key, value in node.items():
            yield path, key, value
            yield from _walk(value, f"{path}/{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _walk(value, f"{path}/{i}")


class FakeCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))])


class ProviderSwitchTests(unittest.TestCase):
    def test_default_is_openai_and_request_untouched(self):
        with mock.patch.dict(os.environ, {"LLM_PROVIDER": ""}):
            kwargs = {"model": "gpt-4o-mini", "temperature": 0.18, "response_format": {"type": "json_object"}}
            self.assertIs(eu.adapt_request_for_provider(kwargs), kwargs)
            self.assertEqual(eu.provider_client_options(), {})
            self.assertEqual(eu.llm_provider_label(), "OpenAI")

    def test_anthropic_client_options(self):
        env = {"LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "k", "ANTHROPIC_WORKSPACE_ID": "ws"}
        with mock.patch.dict(os.environ, env):
            options = eu.provider_client_options()
        self.assertEqual(options["api_key"], "k")
        self.assertEqual(options["base_url"], "https://api.anthropic.com/v1/")
        self.assertEqual(options["default_headers"], {"anthropic-workspace-id": "ws"})

    def test_anthropic_without_key_fails_loudly(self):
        with mock.patch.dict(os.environ, {"LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": ""}):
            with self.assertRaises(RuntimeError):
                eu.provider_client_options()

    def test_real_article_schema_is_claude_compatible_and_keeps_guidance(self):
        import scraper as core

        with mock.patch.dict(os.environ, {"LLM_PROVIDER": "anthropic", "ANTHROPIC_MODEL": ""}):
            adapted = eu.adapt_request_for_provider({
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "x"}],
                "temperature": 0.18,
                "max_tokens": 2000,
                "response_format": {"type": "json_schema", "json_schema": core.ARTICLE_SCHEMA},
            })
        self.assertEqual(adapted["model"], "claude-haiku-5-5")
        self.assertNotIn("temperature", adapted)
        self.assertEqual(adapted["max_tokens"], 2000)
        schema = adapted["response_format"]["json_schema"]
        self.assertTrue(schema["strict"])
        for path, key, value in _walk(schema["schema"]):
            if path.endswith("/properties"):
                continue  # property names, not keywords
            if key == "minItems":
                self.assertLessEqual(value, 1, path)
            else:
                self.assertNotIn(key, LIMIT_KEYS - {"minItems"}, path)
        props = schema["schema"]["properties"]
        self.assertIn("at least 4 items", props["paragraphs"]["description"])
        self.assertIn("at most 12 items", props["paragraphs"]["description"])
        self.assertIn("at most 4 items", props["useful_links"]["description"])
        # Same fields, same required list: nothing about the article changes.
        self.assertEqual(set(props), set(core.ARTICLE_SCHEMA["schema"]["properties"]))
        self.assertEqual(schema["schema"]["required"], core.ARTICLE_SCHEMA["schema"]["required"])
        # The original schema object is not mutated.
        self.assertEqual(core.ARTICLE_SCHEMA["schema"]["properties"]["paragraphs"]["minItems"], 4)

    def test_property_named_like_keyword_is_kept(self):
        schema = {"type": "object", "properties": {"maximum": {"type": "string", "maxLength": 5}}}
        out = eu.claude_schema(schema)
        self.assertIn("maximum", out["properties"])
        self.assertNotIn("maxLength", out["properties"]["maximum"])

    def test_thinking_disabled_for_claude_only(self):
        with mock.patch.dict(os.environ, {"LLM_PROVIDER": "anthropic"}):
            adapted = eu.adapt_request_for_provider({"model": "m", "max_tokens": 2000})
        self.assertEqual(adapted["extra_body"], {"thinking": {"type": "disabled"}})
        self.assertEqual(adapted["max_tokens"], 2000)
        with mock.patch.dict(os.environ, {"LLM_PROVIDER": "openai"}):
            self.assertNotIn("extra_body", eu.adapt_request_for_provider({"model": "m"}))

    def test_json_object_mode_dropped_for_claude(self):
        with mock.patch.dict(os.environ, {"LLM_PROVIDER": "anthropic"}):
            adapted = eu.adapt_request_for_provider({"model": "m", "response_format": {"type": "json_object"}})
        self.assertNotIn("response_format", adapted)

    def test_retry_wrapper_sends_adapted_request(self):
        fake = FakeCompletions()
        client = SimpleNamespace(chat=SimpleNamespace(completions=fake))
        with mock.patch.dict(os.environ, {"LLM_PROVIDER": "anthropic", "ANTHROPIC_MODEL": "claude-x"}):
            eu.create_with_rate_limit_retry(client, {"model": "gpt-4o-mini", "temperature": 0.18})
        self.assertEqual(fake.calls, [{"model": "claude-x", "extra_body": {"thinking": {"type": "disabled"}}}])
        json.dumps(fake.calls)  # plain data only


class PublishableFlagTests(unittest.TestCase):
    def _draft(self, **over):
        d = {
            "publishable": False, "content_class": "news_report", "is_about_rochdale_borough": True,
            "title": "x", "excerpt": "", "paragraphs": [],
        }
        d.update(over)
        return d

    def test_flag_trusted_by_default(self):
        with mock.patch.dict(os.environ, {"TRUST_MODEL_PUBLISHABLE_FLAG": ""}):
            self.assertEqual(eu.quality_issues(self._draft(), "source"), ["The model marked the story unpublishable."])

    def test_flag_ignored_but_other_checks_still_run(self):
        with mock.patch.dict(os.environ, {"TRUST_MODEL_PUBLISHABLE_FLAG": "false"}):
            issues = eu.quality_issues(self._draft(), "source")
        self.assertNotIn("The model marked the story unpublishable.", issues)
        self.assertTrue(issues)  # headline/standfirst/length checks still apply

    def test_advert_gate_still_applies_when_flag_ignored(self):
        with mock.patch.dict(os.environ, {"TRUST_MODEL_PUBLISHABLE_FLAG": "false"}):
            issues = eu.quality_issues(self._draft(content_class="advert_or_listing"), "source")
        self.assertTrue(any(i.startswith(eu.GATE_REJECTION_PREFIX) for i in issues), issues)


class RetryClassificationTests(unittest.TestCase):
    def test_claude_provider_failure_is_retryable(self):
        import scraper as core
        self.assertEqual(core.rewrite_outcome_for_reason("Claude: all 4 attempts failed (APIError)"), "failed")
        self.assertEqual(core.rewrite_outcome_for_reason("OpenAI: all 4 attempts failed"), "failed")


if __name__ == "__main__":
    unittest.main()
