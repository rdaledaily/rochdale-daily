from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import model_bridge


class ModelBridgeTests(unittest.TestCase):
    def test_verdict_parser(self) -> None:
        self.assertEqual(model_bridge.verdict("x\nVERDICT: APPROVE"), "APPROVE")
        self.assertEqual(model_bridge.verdict("VERDICT: REVISE because tests"), "REVISE")
        self.assertEqual(model_bridge.verdict("no verdict"), "REVISE")

    def test_round_bound_and_approval(self) -> None:
        with patch.object(model_bridge, "ask_openai", return_value="proposal"), patch.object(
            model_bridge, "ask_anthropic", return_value="looks safe\nVERDICT: APPROVE"
        ):
            result = model_bridge.run_bridge("task", "openai-test", "claude-test", 99)
        self.assertEqual(result["max_rounds"], model_bridge.MAX_ROUNDS)
        self.assertEqual(result["rounds_completed"], 1)
        self.assertEqual(result["verdict"], "APPROVE")
        self.assertEqual(len(result["turns"]), 2)
        self.assertFalse(result["safety"]["autonomous_repo_write"])

    def test_revision_stops_at_bound(self) -> None:
        with patch.object(model_bridge, "ask_openai", return_value="proposal"), patch.object(
            model_bridge, "ask_anthropic", return_value="needs work\nVERDICT: REVISE"
        ):
            result = model_bridge.run_bridge("task", "o", "a", 2)
        self.assertEqual(result["rounds_completed"], 2)
        self.assertEqual(result["verdict"], "REVISE")
        self.assertEqual(len(result["turns"]), 4)

    def test_output_is_serialisable_without_secret_names(self) -> None:
        with patch.object(model_bridge, "ask_openai", return_value="proposal"), patch.object(
            model_bridge, "ask_anthropic", return_value="VERDICT: APPROVE"
        ):
            result = model_bridge.run_bridge("task", "o", "a", 1)
        encoded = json.dumps(result)
        self.assertNotIn("ANTHROPIC_API_KEY", encoded)
        self.assertNotIn("OPENAI_API_KEY", encoded)


if __name__ == "__main__":
    unittest.main()
