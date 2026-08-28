from __future__ import annotations

import json

import dual_agent_bridge as bridge


class FakeClient:
    def __init__(self, provider: str, model: str, responses: list[dict[str, object]]) -> None:
        self.provider = provider
        self.model = model
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        if not self._responses:
            raise AssertionError("No fake response left for this client.")
        return json.dumps(self._responses.pop(0))


def sample_task() -> bridge.TaskPayload:
    return bridge.TaskPayload(
        target_type="pull_request",
        repository="rdaledaily/rochdale-daily",
        title="Add a comment-only dual-agent bridge",
        body="Review the workflow and confirm the guardrails are intact.",
        source_number=42,
    )


def main() -> None:
    parsed = bridge.parse_task_json(
        json.dumps(
            {
                "title": "SEO bridge review",
                "objective": "Compare two model assessments before human review.",
                "acceptance_criteria": [
                    "Return a structured artifact",
                    "Do not merge automatically",
                ],
                "constraints": ["Comment only", "Use GitHub secrets"],
                "changed_files": ["scraper/dual_agent_bridge.py", "README.md"],
            }
        ),
        repository="rdaledaily/rochdale-daily",
    )
    assert parsed.target_type == "task"
    assert parsed.title == "SEO bridge review"
    assert parsed.changed_files[0].filename == "scraper/dual_agent_bridge.py"

    try:
        bridge.parse_task_json('{"objective":"Missing title"}', repository="x/y")
        raise AssertionError("Missing title should fail schema validation.")
    except ValueError:
        pass

    response = bridge.validate_agent_response(
        json.dumps(
            {
                "summary": "The task is safe to continue with human review.",
                "recommendation": "proceed",
                "key_points": ["Comment only", "No repo writes"],
                "risks": [],
                "follow_ups": ["Check the workflow permissions"],
                "destructive_change_detected": False,
            }
        )
    )
    assert response.recommendation == "proceed"

    try:
        bridge.validate_agent_response(
            json.dumps(
                {
                    "summary": "Invalid response",
                    "recommendation": "ship_it",
                    "key_points": [],
                    "risks": [],
                    "follow_ups": [],
                    "destructive_change_detected": False,
                }
            )
        )
        raise AssertionError("Unexpected recommendation should fail schema validation.")
    except ValueError:
        pass

    lead = FakeClient(
        "openai",
        "gpt-test",
        [
            {
                "summary": "Initial proposal.",
                "recommendation": "proceed",
                "key_points": ["Read-only review"],
                "risks": [],
                "follow_ups": [],
                "destructive_change_detected": False,
            },
            {
                "summary": "Revised proposal.",
                "recommendation": "proceed",
                "key_points": ["Still read-only"],
                "risks": [],
                "follow_ups": [],
                "destructive_change_detected": False,
            },
        ],
    )
    critic = FakeClient(
        "anthropic",
        "claude-test",
        [
            {
                "summary": "Needs another pass.",
                "recommendation": "revise",
                "key_points": ["Guardrail wording is weak"],
                "risks": ["Missing explicit no-push language"],
                "follow_ups": ["Strengthen the workflow permissions note"],
                "destructive_change_detected": False,
            },
            {
                "summary": "Still needs another pass.",
                "recommendation": "revise",
                "key_points": ["Round limit should stop this loop"],
                "risks": ["Without a cap this could spin forever"],
                "follow_ups": ["Stop after the configured maximum rounds"],
                "destructive_change_detected": False,
            },
        ],
    )
    artifact = bridge.run_bridge(
        task=sample_task(),
        lead_client=lead,
        critic_client=critic,
        max_rounds=2,
    )
    assert artifact["rounds_completed"] == 2
    assert artifact["termination_reason"] == "round_limit"
    assert artifact["decision"]["status"] == "revise"

    lead_fast = FakeClient(
        "anthropic",
        "claude-test",
        [
            {
                "summary": "Proposal is already narrow and safe.",
                "recommendation": "proceed",
                "key_points": ["No merge path"],
                "risks": [],
                "follow_ups": [],
                "destructive_change_detected": False,
            }
        ],
    )
    critic_fast = FakeClient(
        "openai",
        "gpt-test",
        [
            {
                "summary": "No more changes requested.",
                "recommendation": "proceed",
                "key_points": ["Human review remains required"],
                "risks": [],
                "follow_ups": ["Run the workflow manually on a real PR"],
                "destructive_change_detected": False,
            }
        ],
    )
    fast_artifact = bridge.run_bridge(
        task=sample_task(),
        lead_client=lead_fast,
        critic_client=critic_fast,
        max_rounds=3,
    )
    assert fast_artifact["rounds_completed"] == 1
    assert fast_artifact["termination_reason"] == "critic_stopped"
    assert fast_artifact["decision"]["status"] == "proceed"

    print("Dual-agent bridge schema and loop termination tests passed.")


if __name__ == "__main__":
    main()
