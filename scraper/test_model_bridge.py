from __future__ import annotations

import json
import tempfile
from pathlib import Path

import model_bridge


def test_verdict_parser() -> None:
    assert model_bridge.verdict("x\nVERDICT: APPROVE") == "APPROVE"
    assert model_bridge.verdict("VERDICT: REVISE because tests") == "REVISE"
    assert model_bridge.verdict("no verdict") == "REVISE"


def test_round_bound_and_approval(monkeypatch) -> None:
    proposals = []

    def fake_openai(prompt: str, model: str) -> str:
        proposals.append(prompt)
        return "proposal"

    def fake_anthropic(prompt: str, model: str) -> str:
        return "looks safe\nVERDICT: APPROVE"

    monkeypatch.setattr(model_bridge, "ask_openai", fake_openai)
    monkeypatch.setattr(model_bridge, "ask_anthropic", fake_anthropic)
    result = model_bridge.run_bridge("task", "openai-test", "claude-test", 99)
    assert result["max_rounds"] == model_bridge.MAX_ROUNDS
    assert result["rounds_completed"] == 1
    assert result["verdict"] == "APPROVE"
    assert len(result["turns"]) == 2
    assert result["safety"]["autonomous_repo_write"] is False


def test_revision_stops_at_bound(monkeypatch) -> None:
    def fake_openai(prompt: str, model: str) -> str:
        return "proposal"

    def fake_anthropic(prompt: str, model: str) -> str:
        return "needs work\nVERDICT: REVISE"

    monkeypatch.setattr(model_bridge, "ask_openai", fake_openai)
    monkeypatch.setattr(model_bridge, "ask_anthropic", fake_anthropic)
    result = model_bridge.run_bridge("task", "o", "a", 2)
    assert result["rounds_completed"] == 2
    assert result["verdict"] == "REVISE"
    assert len(result["turns"]) == 4


def test_output_is_serialisable(monkeypatch) -> None:
    monkeypatch.setattr(model_bridge, "ask_openai", lambda prompt, model: "proposal")
    monkeypatch.setattr(model_bridge, "ask_anthropic", lambda prompt, model: "VERDICT: APPROVE")
    result = model_bridge.run_bridge("task", "o", "a", 1)
    encoded = json.dumps(result)
    assert "ANTHROPIC_API_KEY" not in encoded
    assert "OPENAI_API_KEY" not in encoded


if __name__ == "__main__":
    test_verdict_parser()
    print("Model bridge unit checks passed.")
