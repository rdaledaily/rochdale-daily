from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from openai import OpenAI


DEFAULT_OPENAI_MODEL = os.getenv("BRIDGE_OPENAI_MODEL", "gpt-5-mini")
DEFAULT_ANTHROPIC_MODEL = os.getenv("BRIDGE_ANTHROPIC_MODEL", "claude-sonnet-5")
MAX_ROUNDS = 2


@dataclass
class Turn:
    round: int
    role: str
    model: str
    text: str


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _extract_openai_text(response: Any) -> str:
    text = getattr(response, "output_text", None)
    if text:
        return str(text).strip()
    output = getattr(response, "output", None) or []
    parts: list[str] = []
    for item in output:
        for content in getattr(item, "content", None) or []:
            value = getattr(content, "text", None)
            if value:
                parts.append(str(value))
    return "\n".join(parts).strip()


def ask_openai(prompt: str, model: str) -> str:
    client = OpenAI(api_key=_require_env("OPENAI_API_KEY"))
    response = client.responses.create(
        model=model,
        input=prompt,
    )
    text = _extract_openai_text(response)
    if not text:
        raise RuntimeError("OpenAI returned an empty response")
    return text


def _anthropic_error_message(response: requests.Response) -> str:
    """Return Anthropic's useful error message without echoing request headers/secrets."""
    try:
        payload = response.json()
    except ValueError:
        return (response.text or response.reason or "unknown error").strip()[:1000]
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        message = str(error.get("message") or "").strip()
        error_type = str(error.get("type") or "").strip()
        if message:
            return f"{error_type}: {message}" if error_type else message
    return json.dumps(payload, ensure_ascii=False)[:1000]


def ask_anthropic(prompt: str, model: str) -> str:
    key = _require_env("ANTHROPIC_API_KEY")
    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 2400,
            "thinking": {"type": "disabled"},
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=120,
    )
    if not response.ok:
        raise RuntimeError(
            f"Anthropic API returned HTTP {response.status_code}: {_anthropic_error_message(response)}"
        )
    payload = response.json()
    parts = [
        block.get("text", "")
        for block in payload.get("content", [])
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    text = "\n".join(p for p in parts if p).strip()
    if not text:
        raise RuntimeError("Anthropic returned an empty response")
    return text


def build_openai_prompt(task: str, critique: str | None = None) -> str:
    base = (
        "You are the proposing engineer for Rochdale Daily. Produce a concise, implementable plan. "
        "Protect newsroom freshness, factual reliability and current production behaviour. "
        "Do not claim to have made changes. Do not expose secrets.\n\n"
        f"TASK:\n{task.strip()}"
    )
    if critique:
        base += (
            "\n\nClaude reviewed your previous proposal. Revise only where the critique is valid, "
            "and explicitly resolve disagreements.\n\nCLAUDE CRITIQUE:\n" + critique.strip()
        )
    return base


def build_anthropic_prompt(task: str, proposal: str) -> str:
    return (
        "You are the critical reviewer for Rochdale Daily. Review the OpenAI proposal below. "
        "Look for production risk, stale-news regressions, unnecessary workflow churn, false assumptions, "
        "security issues, and missing tests. Be specific. End with exactly one line beginning "
        "'VERDICT:' followed by APPROVE or REVISE. Do not expose secrets.\n\n"
        f"TASK:\n{task.strip()}\n\nOPENAI PROPOSAL:\n{proposal.strip()}"
    )


def verdict(text: str) -> str:
    for line in reversed(text.splitlines()):
        if line.strip().upper().startswith("VERDICT:"):
            value = line.split(":", 1)[1].strip().upper()
            if value.startswith("APPROVE"):
                return "APPROVE"
            if value.startswith("REVISE"):
                return "REVISE"
    return "REVISE"


def run_bridge(task: str, openai_model: str, anthropic_model: str, max_rounds: int) -> dict[str, Any]:
    max_rounds = max(1, min(max_rounds, MAX_ROUNDS))
    turns: list[Turn] = []
    critique: str | None = None
    final_verdict = "REVISE"

    for round_no in range(1, max_rounds + 1):
        proposal = ask_openai(build_openai_prompt(task, critique), openai_model)
        turns.append(Turn(round_no, "proposer", openai_model, proposal))

        review = ask_anthropic(build_anthropic_prompt(task, proposal), anthropic_model)
        turns.append(Turn(round_no, "reviewer", anthropic_model, review))
        final_verdict = verdict(review)
        if final_verdict == "APPROVE":
            break
        critique = review

    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "task": task,
        "max_rounds": max_rounds,
        "rounds_completed": max(t.round for t in turns) if turns else 0,
        "verdict": final_verdict,
        "turns": [asdict(t) for t in turns],
        "safety": {
            "autonomous_repo_write": False,
            "secrets_embedded": False,
            "bounded_rounds": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded OpenAI ↔ Claude review bridge")
    parser.add_argument("--task", required=True)
    parser.add_argument("--output", default="reports/model_bridge_review.json")
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--openai-model", default=DEFAULT_OPENAI_MODEL)
    parser.add_argument("--anthropic-model", default=DEFAULT_ANTHROPIC_MODEL)
    args = parser.parse_args()

    result = run_bridge(args.task, args.openai_model, args.anthropic_model, args.rounds)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(out), "verdict": result["verdict"], "rounds": result["rounds_completed"]}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"bridge error: {exc}", file=sys.stderr)
        raise
