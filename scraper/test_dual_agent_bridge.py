from __future__ import annotations

from pathlib import Path

import dual_agent_bridge as bridge

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "dual-agent-bridge.yml"


def sample_task() -> dict[str, object]:
    return {
        "task": "Increase fresh-story supply without weakening the 14-hour newest-story requirement.",
        "constraints": [
            "Do not weaken the 14-hour newest-story requirement.",
            "Do not propose autonomous merging or pushing.",
        ],
        "acceptance_criteria": [
            "Recommendations must be measurable.",
        ],
        "context": "Rochdale Daily already has automated publishing workflows.",
    }


def test_normalise_task_accepts_plain_string() -> None:
    task = bridge.normalise_task_payload("Find better fresh-story supply ideas.")
    assert task["task"] == "Find better fresh-story supply ideas."
    assert task["constraints"] == []


def test_issue_body_prefers_embedded_json() -> None:
    payload = bridge.extract_task_from_issue_body(
        "[bridge] Ignore the title fallback",
        """
        Please run the bridge.

        ```json
        {
          "task": "Review fresh-story supply options.",
          "constraints": ["Keep the 14-hour rule."],
          "context": "Use only source and workflow ideas."
        }
        ```
        """,
    )
    assert payload["task"] == "Review fresh-story supply options."
    assert payload["constraints"] == ["Keep the 14-hour rule."]


def test_redaction_replaces_known_secret_values() -> None:
    text = "openai=sk-live-123 anthropic=secret-456"
    redacted = bridge.redact_text(text, ["sk-live-123", "secret-456"])
    assert "sk-live-123" not in redacted
    assert "secret-456" not in redacted
    assert redacted.count("[redacted]") == 2


def test_optional_integer_parsing_handles_empty_values() -> None:
    assert bridge.parse_optional_int("") is None
    assert bridge.parse_optional_int(None) is None
    assert bridge.parse_optional_int("17") == 17


def test_exchange_stops_when_reviewer_accepts() -> None:
    calls = {"proposal": 0, "review": 0}

    def proposer(_: str) -> dict[str, object]:
        calls["proposal"] += 1
        return {
            "summary": "Focus on measurable source expansion.",
            "recommendations": [
                {
                    "title": "Probe new source classes",
                    "action": "Run a yield probe for candidate council, community, and sports feeds.",
                    "why": "Measured additions protect freshness quality.",
                    "freshness_guard": "Keep the 14-hour newest-story rule untouched.",
                    "evidence_to_watch": "Daily recent-item yield by source class.",
                    "effort": "medium",
                }
            ],
            "risks": ["Some sources may add low-yield noise."],
            "keep": ["Keep the 14-hour newest-story rule untouched."],
        }

    def reviewer(_: str) -> dict[str, object]:
        calls["review"] += 1
        return {
            "summary": "Accepted: the idea increases inputs without relaxing freshness rules.",
            "strengths": ["Uses measurement before wiring in more collectors."],
            "concerns": [],
            "missing_guards": [],
            "revision_requests": [],
            "consensus_points": ["Keep the 14-hour newest-story rule untouched."],
            "accept": True,
        }

    report = bridge.run_exchange(sample_task(), proposer, reviewer, max_rounds=2)
    assert report["terminated_reason"] == "reviewer_accepted"
    assert len(report["rounds"]) == 1
    assert calls == {"proposal": 1, "review": 1}


def test_exchange_stops_at_round_limit() -> None:
    def proposer(_: str) -> dict[str, object]:
        return {
            "summary": "Add more measured sources.",
            "recommendations": [
                {
                    "title": "Add source probes",
                    "action": "Measure candidate feeds first.",
                    "why": "Measured inputs reduce stale volume.",
                    "freshness_guard": "Keep the 14-hour newest-story rule untouched.",
                    "evidence_to_watch": "Recent items per day.",
                    "effort": "low",
                }
            ],
            "risks": ["Some feeds may stay stale."],
            "keep": ["Keep the 14-hour newest-story rule untouched."],
        }

    def reviewer(_: str) -> dict[str, object]:
        return {
            "summary": "Promising but not yet tight enough.",
            "strengths": ["It is measurable."],
            "concerns": ["It should prioritise highest-yield official feeds first."],
            "missing_guards": ["Spell out that stale feeds should be dropped quickly."],
            "revision_requests": ["Rank source classes by recent yield after the probe."],
            "consensus_points": ["Keep the 14-hour newest-story rule untouched."],
            "accept": False,
        }

    report = bridge.run_exchange(sample_task(), proposer, reviewer, max_rounds=2)
    assert report["terminated_reason"] == "max_rounds_reached"
    assert len(report["rounds"]) == 2
    assert report["final"]["status"] == "accepted-with-cautions"


def test_comment_mentions_run_and_artifact() -> None:
    report = bridge.run_exchange(
        sample_task(),
        lambda _: {
            "summary": "Build source probes before new collectors.",
            "recommendations": [
                {
                    "title": "Measure before building",
                    "action": "Probe yield before adding new source collectors.",
                    "why": "This avoids stale filler.",
                    "freshness_guard": "Keep the 14-hour newest-story rule untouched.",
                    "evidence_to_watch": "14-day recent-item counts per source.",
                    "effort": "low",
                }
            ],
            "risks": [],
            "keep": ["Keep the 14-hour newest-story rule untouched."],
        },
        lambda _: {
            "summary": "Accepted with clear guardrails.",
            "strengths": ["It protects freshness quality."],
            "concerns": [],
            "missing_guards": [],
            "revision_requests": [],
            "consensus_points": ["Keep the 14-hour newest-story rule untouched."],
            "accept": True,
        },
        max_rounds=1,
    )
    comment = bridge.build_comment_markdown(
        report,
        "https://github.com/rdaledaily/rochdale-daily/actions/runs/123",
        "dual-agent-bridge-report-123",
    )
    assert "actions/runs/123" in comment
    assert "dual-agent-bridge-report-123" in comment


def test_workflow_is_secret_backed_and_comment_only() -> None:
    body = WORKFLOW.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}" in body
    assert "ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}" in body
    assert "contents: read" in body
    assert "issues: write" in body
    assert "pull-requests: write" in body
    assert "actions/upload-artifact@v4" in body
    for forbidden in ("contents: write", "git push", "git merge", "gh workflow run"):
        assert forbidden not in body


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
    print(f"Dual-agent bridge checks passed ({len(tests)} tests).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())