"""Minimal dual-agent GitHub consensus bridge.

This workflow-facing module reads a GitHub issue, pull request, or structured
task payload, asks one model to lead with a proposal/review, asks the other to
critique it, and emits a comment-only consensus artifact.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol
from urllib import error, request

MAX_FILES = 12
MAX_PATCH_CHARS = 1600
MAX_TEXT_CHARS = 12000
MAX_LIST_ITEMS = 8
MAX_ROUNDS = 3
ALLOWED_TARGET_TYPES = {"issue", "pull_request", "task"}
ALLOWED_RECOMMENDATIONS = {"proceed", "revise", "needs_human"}
COMMENT_MARKER = "<!-- dual-agent-bridge -->"


@dataclass(frozen=True)
class ChangedFile:
    filename: str
    status: str
    additions: int
    deletions: int
    patch_excerpt: str = ""


@dataclass(frozen=True)
class TaskPayload:
    target_type: str
    repository: str
    title: str
    body: str
    source_number: int | None = None
    url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    changed_files: list[ChangedFile] = field(default_factory=list)


@dataclass(frozen=True)
class AgentResponse:
    summary: str
    recommendation: str
    key_points: list[str]
    risks: list[str]
    follow_ups: list[str]
    destructive_change_detected: bool


@dataclass(frozen=True)
class BridgeRound:
    round_number: int
    lead_response: AgentResponse
    critic_response: AgentResponse


class ModelClient(Protocol):
    provider: str
    model: str

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        ...


class OpenAIModelClient:
    provider = "openai"

    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key)
        response = client.responses.create(
            model=self.model,
            instructions=system_prompt,
            input=user_prompt,
            max_output_tokens=1200,
        )
        text = getattr(response, "output_text", "") or ""
        if text.strip():
            return text
        raise ValueError("OpenAI response did not include output_text.")


class AnthropicModelClient:
    provider = "anthropic"

    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "model": self.model,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
            "max_tokens": 1200,
            "temperature": 0.2,
        }
        data = http_json(
            "https://api.anthropic.com/v1/messages",
            method="POST",
            headers={
                "content-type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            payload=payload,
        )
        blocks = data.get("content")
        if not isinstance(blocks, list):
            raise ValueError("Anthropic response did not include a content list.")
        text_chunks = []
        for block in blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    text_chunks.append(text)
        text = "\n".join(chunk.strip() for chunk in text_chunks if chunk.strip())
        if text:
            return text
        raise ValueError("Anthropic response did not include any text blocks.")


class GitHubClient:
    def __init__(self, repository: str, token: str) -> None:
        self.repository = repository
        self.token = token
        self.base_url = f"https://api.github.com/repos/{repository}"

    def get_json(self, path: str) -> Any:
        return http_json(
            f"{self.base_url}{path}",
            method="GET",
            headers=self._headers(),
        )

    def post_json(self, path: str, payload: dict[str, Any]) -> Any:
        return http_json(
            f"{self.base_url}{path}",
            method="POST",
            headers=self._headers(),
            payload=payload,
        )

    def add_issue_comment(self, number: int, comment: str) -> None:
        self.post_json(f"/issues/{number}/comments", {"body": comment})

    def _headers(self) -> dict[str, str]:
        return {
            "accept": "application/vnd.github+json",
            "authorization": f"Bearer {self.token}",
            "x-github-api-version": "2022-11-28",
        }


def http_json(
    url: str,
    *,
    method: str,
    headers: dict[str, str],
    payload: dict[str, Any] | None = None,
) -> Any:
    body = None
    merged_headers = {"user-agent": "rd-dual-agent-bridge"}
    merged_headers.update(headers)
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=body, headers=merged_headers, method=method)
    try:
        with request.urlopen(req, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} for {url}: {message}") from exc


def trim_text(value: str, limit: int) -> str:
    text = " ".join((value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def normalize_text_list(value: Any, *, name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list of strings.")
    items: list[str] = []
    for item in value[:MAX_LIST_ITEMS]:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{name} must contain only non-empty strings.")
        items.append(trim_text(item, 400))
    return items


def require_text(value: Any, *, name: str, limit: int = MAX_TEXT_CHARS) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string.")
    return trim_text(value, limit)


def parse_task_json(raw: str, *, repository: str) -> TaskPayload:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"task_json is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("task_json must decode to an object.")

    title = require_text(data.get("title"), name="title", limit=200)
    objective = require_text(data.get("objective"), name="objective")
    acceptance = normalize_text_list(
        data.get("acceptance_criteria"), name="acceptance_criteria"
    )
    constraints = normalize_text_list(data.get("constraints"), name="constraints")
    referenced_files = normalize_text_list(
        data.get("changed_files"), name="changed_files"
    )

    body_lines = [objective]
    if acceptance:
        body_lines.append("Acceptance criteria:")
        body_lines.extend(f"- {item}" for item in acceptance)
    if constraints:
        body_lines.append("Constraints:")
        body_lines.extend(f"- {item}" for item in constraints)

    changed_files = [
        ChangedFile(
            filename=filename,
            status="referenced",
            additions=0,
            deletions=0,
            patch_excerpt="",
        )
        for filename in referenced_files
    ]
    return TaskPayload(
        target_type="task",
        repository=repository,
        title=title,
        body="\n".join(body_lines),
        metadata={"acceptance_criteria": acceptance, "constraints": constraints},
        changed_files=changed_files,
    )


def validate_agent_response(raw: str) -> AgentResponse:
    text = raw.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 3:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("model response did not contain a JSON object.")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("model response JSON must be an object.")

    summary = require_text(data.get("summary"), name="summary", limit=1200)
    recommendation = require_text(
        data.get("recommendation"), name="recommendation", limit=40
    )
    if recommendation not in ALLOWED_RECOMMENDATIONS:
        raise ValueError(
            "recommendation must be one of proceed, revise, or needs_human."
        )
    destructive = data.get("destructive_change_detected")
    if not isinstance(destructive, bool):
        raise ValueError("destructive_change_detected must be a boolean.")
    return AgentResponse(
        summary=summary,
        recommendation=recommendation,
        key_points=normalize_text_list(data.get("key_points"), name="key_points"),
        risks=normalize_text_list(data.get("risks"), name="risks"),
        follow_ups=normalize_text_list(data.get("follow_ups"), name="follow_ups"),
        destructive_change_detected=destructive,
    )


def safe_agent_response(client: ModelClient, *, system_prompt: str, user_prompt: str) -> AgentResponse:
    raw = client.generate(system_prompt=system_prompt, user_prompt=user_prompt)
    try:
        return validate_agent_response(raw)
    except Exception as exc:
        return AgentResponse(
            summary=(
                f"{client.provider} returned an invalid structured payload and the "
                "run has been downgraded to human review."
            ),
            recommendation="needs_human",
            key_points=[],
            risks=[trim_text(str(exc), 300)],
            follow_ups=["Re-run the bridge after checking model availability and prompts."],
            destructive_change_detected=False,
        )


def build_system_prompt() -> str:
    return (
        "You are one half of a secure dual-agent GitHub review bridge.\n"
        "You must ground your answer only in the supplied GitHub context.\n"
        "This run is comment-only: you cannot merge, push, edit files, delete data, "
        "change secrets, or approve destructive operations.\n"
        "If the task suggests destructive, privileged, or repo-mutating actions, set "
        'destructive_change_detected to true and recommendation to "needs_human".\n'
        "Return JSON only with this exact shape:\n"
        "{\n"
        '  "summary": string,\n'
        '  "recommendation": "proceed" | "revise" | "needs_human",\n'
        '  "key_points": string[],\n'
        '  "risks": string[],\n'
        '  "follow_ups": string[],\n'
        '  "destructive_change_detected": boolean\n'
        "}\n"
        "Keep lists short and concrete."
    )


def task_prompt(task: TaskPayload) -> str:
    payload = asdict(task)
    return json.dumps(payload, indent=2)


def build_lead_prompt(task: TaskPayload, previous_critique: AgentResponse | None) -> str:
    prompt = [
        "Review or propose the next action for this GitHub task.",
        "Prefer auditable, minimal changes and explicitly note test gaps.",
        "GitHub source of truth:",
        task_prompt(task),
    ]
    if previous_critique is not None:
        prompt.extend(
            [
                "Previous critique to address:",
                json.dumps(asdict(previous_critique), indent=2),
            ]
        )
    return "\n\n".join(prompt)


def build_critic_prompt(task: TaskPayload, lead_response: AgentResponse) -> str:
    return "\n\n".join(
        [
            "Critique the lead response for security, missing tests, bad assumptions, "
            "and unsafe/destructive suggestions.",
            "Ask for revision when the lead response is incomplete or risky.",
            "GitHub source of truth:",
            task_prompt(task),
            "Lead response:",
            json.dumps(asdict(lead_response), indent=2),
        ]
    )


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def build_decision(rounds: list[BridgeRound], termination_reason: str) -> dict[str, Any]:
    latest = rounds[-1]
    lead = latest.lead_response
    critic = latest.critic_response
    blocking = dedupe(critic.risks)
    next_steps = dedupe(critic.follow_ups + lead.follow_ups)

    if lead.destructive_change_detected or critic.destructive_change_detected:
        status = "needs_human"
        blocking = dedupe(
            ["Potential destructive or privileged change detected."] + blocking
        )
        summary = (
            "A model flagged potentially destructive or privileged work. The bridge "
            "stayed in comment-only mode and requires explicit human review."
        )
    elif critic.recommendation == "revise":
        status = "revise"
        if termination_reason == "round_limit":
            summary = (
                "The critic continued to request changes until the configured round "
                "limit was reached. Human follow-up is required before any code work."
            )
        else:
            summary = (
                "The critic requested changes before the task should proceed to normal "
                "human review."
            )
    elif lead.recommendation == "needs_human" or critic.recommendation == "needs_human":
        status = "needs_human"
        summary = (
            "At least one model requested a human decision instead of continuing the "
            "bridge automatically."
        )
    else:
        status = "proceed"
        summary = (
            "The critique did not request further revisions. The task can proceed to "
            "ordinary human review, but the bridge still cannot merge or push changes."
        )

    if status == "revise" and not blocking:
        blocking = ["The critic requested a revision before human approval."]
    return {
        "status": status,
        "summary": summary,
        "blocking_issues": blocking,
        "next_steps": next_steps,
        "merge_allowed": False,
        "push_allowed": False,
        "human_review_required": True,
    }


def run_bridge(
    *,
    task: TaskPayload,
    lead_client: ModelClient,
    critic_client: ModelClient,
    max_rounds: int,
) -> dict[str, Any]:
    if max_rounds < 1 or max_rounds > MAX_ROUNDS:
        raise ValueError(f"max_rounds must be between 1 and {MAX_ROUNDS}.")

    system_prompt = build_system_prompt()
    rounds: list[BridgeRound] = []
    previous_critique: AgentResponse | None = None
    termination_reason = "round_limit"

    for round_number in range(1, max_rounds + 1):
        lead_response = safe_agent_response(
            lead_client,
            system_prompt=system_prompt,
            user_prompt=build_lead_prompt(task, previous_critique),
        )
        critic_response = safe_agent_response(
            critic_client,
            system_prompt=system_prompt,
            user_prompt=build_critic_prompt(task, lead_response),
        )
        rounds.append(
            BridgeRound(
                round_number=round_number,
                lead_response=lead_response,
                critic_response=critic_response,
            )
        )
        previous_critique = critic_response

        if critic_response.destructive_change_detected:
            termination_reason = "destructive_change_detected"
            break
        if critic_response.recommendation != "revise":
            termination_reason = "critic_stopped"
            break

    return {
        "version": 1,
        "task": asdict(task),
        "lead_provider": lead_client.provider,
        "lead_model": lead_client.model,
        "critic_provider": critic_client.provider,
        "critic_model": critic_client.model,
        "rounds_completed": len(rounds),
        "termination_reason": termination_reason,
        "decision": build_decision(rounds, termination_reason),
        "rounds": [
            {
                "round_number": item.round_number,
                "lead_response": asdict(item.lead_response),
                "critic_response": asdict(item.critic_response),
            }
            for item in rounds
        ],
    }


def render_comment(artifact: dict[str, Any]) -> str:
    task = artifact["task"]
    decision = artifact["decision"]
    latest_round = artifact["rounds"][-1]
    lead = latest_round["lead_response"]
    critic = latest_round["critic_response"]

    lines = [
        COMMENT_MARKER,
        "## Dual-agent bridge consensus",
        "",
        f"- Target: `{task['target_type']}`"
        + (
            f" #{task['source_number']}"
            if task.get("source_number") is not None
            else " structured task"
        ),
        f"- Lead: `{artifact['lead_provider']}` (`{artifact['lead_model']}`)",
        f"- Critic: `{artifact['critic_provider']}` (`{artifact['critic_model']}`)",
        f"- Status: `{decision['status']}`",
        "- Guardrails: comment only, no merge, no push, human follow-up required",
        "",
        "### Consensus",
        decision["summary"],
    ]
    if decision["blocking_issues"]:
        lines.extend(["", "### Blocking issues"])
        lines.extend(f"- {item}" for item in decision["blocking_issues"])
    if decision["next_steps"]:
        lines.extend(["", "### Next steps"])
        lines.extend(f"- {item}" for item in decision["next_steps"])
    if lead["key_points"]:
        lines.extend(["", "### Lead notes"])
        lines.extend(f"- {item}" for item in lead["key_points"])
    if critic["key_points"]:
        lines.extend(["", "### Critic notes"])
        lines.extend(f"- {item}" for item in critic["key_points"])
    lines.extend(
        [
            "",
            "<details><summary>Structured artifact</summary>",
            "",
            "```json",
            json.dumps(artifact, indent=2),
            "```",
            "",
            "</details>",
        ]
    )
    return "\n".join(lines)


def fetch_issue_task(client: GitHubClient, issue_number: int) -> TaskPayload:
    issue = client.get_json(f"/issues/{issue_number}")
    labels = []
    for label in issue.get("labels", []):
        if isinstance(label, dict):
            name = label.get("name")
            if isinstance(name, str):
                labels.append(name)
    return TaskPayload(
        target_type="issue",
        repository=client.repository,
        title=trim_text(issue.get("title") or f"Issue #{issue_number}", 200),
        body=trim_text(issue.get("body") or "(no body provided)", MAX_TEXT_CHARS),
        source_number=issue_number,
        url=issue.get("html_url"),
        metadata={
            "state": issue.get("state"),
            "labels": labels,
            "author": issue.get("user", {}).get("login"),
        },
    )


def fetch_pull_request_task(client: GitHubClient, pr_number: int) -> TaskPayload:
    pr = client.get_json(f"/pulls/{pr_number}")
    files_data = client.get_json(f"/pulls/{pr_number}/files?per_page={MAX_FILES}")
    changed_files: list[ChangedFile] = []
    if isinstance(files_data, list):
        for item in files_data[:MAX_FILES]:
            if not isinstance(item, dict):
                continue
            changed_files.append(
                ChangedFile(
                    filename=trim_text(str(item.get("filename") or "unknown"), 200),
                    status=trim_text(str(item.get("status") or "modified"), 40),
                    additions=int(item.get("additions") or 0),
                    deletions=int(item.get("deletions") or 0),
                    patch_excerpt=trim_text(str(item.get("patch") or ""), MAX_PATCH_CHARS),
                )
            )
    return TaskPayload(
        target_type="pull_request",
        repository=client.repository,
        title=trim_text(pr.get("title") or f"PR #{pr_number}", 200),
        body=trim_text(pr.get("body") or "(no body provided)", MAX_TEXT_CHARS),
        source_number=pr_number,
        url=pr.get("html_url"),
        metadata={
            "state": pr.get("state"),
            "draft": bool(pr.get("draft")),
            "base_ref": pr.get("base", {}).get("ref"),
            "head_ref": pr.get("head", {}).get("ref"),
            "changed_files_total": pr.get("changed_files"),
        },
        changed_files=changed_files,
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--target-type", required=True, choices=sorted(ALLOWED_TARGET_TYPES))
    parser.add_argument("--target-number")
    parser.add_argument("--task-json")
    parser.add_argument("--task-json-env-var")
    parser.add_argument("--lead-provider", required=True, choices=["openai", "anthropic"])
    parser.add_argument("--openai-model", default="gpt-5")
    parser.add_argument("--anthropic-model", default="claude-sonnet-4-20250514")
    parser.add_argument("--max-rounds", type=int, default=2)
    parser.add_argument("--artifact-path", default="dual-agent-bridge-artifact.json")
    parser.add_argument("--comment-path", default="dual-agent-bridge-comment.md")
    return parser.parse_args(argv)


def load_task_from_args(args: argparse.Namespace, github: GitHubClient) -> TaskPayload:
    if args.target_type == "issue":
        if not args.target_number:
            raise ValueError("--target-number is required for issue targets.")
        return fetch_issue_task(github, int(args.target_number))
    if args.target_type == "pull_request":
        if not args.target_number:
            raise ValueError("--target-number is required for pull_request targets.")
        return fetch_pull_request_task(github, int(args.target_number))
    task_json = args.task_json or ""
    if args.task_json_env_var:
        task_json = os.getenv(args.task_json_env_var, task_json)
    if not task_json.strip():
        raise ValueError("task targets require --task-json or --task-json-env-var.")
    return parse_task_json(task_json, repository=args.repository)


def build_clients(args: argparse.Namespace) -> tuple[ModelClient, ModelClient]:
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not openai_key:
        raise ValueError("OPENAI_API_KEY is required.")
    if not anthropic_key:
        raise ValueError("ANTHROPIC_API_KEY is required.")

    openai_client = OpenAIModelClient(openai_key, args.openai_model)
    anthropic_client = AnthropicModelClient(anthropic_key, args.anthropic_model)
    if args.lead_provider == "openai":
        return openai_client, anthropic_client
    return anthropic_client, openai_client


def write_text(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    github_token = os.getenv("GITHUB_TOKEN", "").strip()
    if not github_token:
        raise ValueError("GITHUB_TOKEN is required.")

    github = GitHubClient(args.repository, github_token)
    task = load_task_from_args(args, github)
    lead_client, critic_client = build_clients(args)
    artifact = run_bridge(
        task=task,
        lead_client=lead_client,
        critic_client=critic_client,
        max_rounds=args.max_rounds,
    )
    comment = render_comment(artifact)
    write_text(args.artifact_path, json.dumps(artifact, indent=2))
    write_text(args.comment_path, comment)
    if task.target_type in {"issue", "pull_request"} and task.source_number is not None:
        github.add_issue_comment(task.source_number, comment)
    print(
        json.dumps(
            {
                "status": artifact["decision"]["status"],
                "rounds_completed": artifact["rounds_completed"],
                "termination_reason": artifact["termination_reason"],
                "artifact_path": args.artifact_path,
                "comment_path": args.comment_path,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
