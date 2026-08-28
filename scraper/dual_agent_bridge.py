"""Minimal OpenAI/Anthropic bridge for GitHub issue and PR reviews.

This bridge is deliberately comment-only. It reads a structured task, asks one
model to propose improvements, asks the other to critique them, then writes a
structured consensus report for GitHub Actions to upload and optionally post as
an issue/PR comment. It never commits, pushes, merges, or dispatches other
workflows.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import textwrap
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT / "reports"

DEFAULT_TASK = {
    "task": (
        "Improve Rochdale Daily's fresh-story supply without weakening the "
        "14-hour newest-story requirement."
    ),
    "constraints": [
        "Do not weaken or bypass the 14-hour newest-story requirement.",
        "Prefer measurable source-discovery, workflow, or editorial-process improvements.",
        "Do not propose autonomous publishing, merging, or pushing to the repository.",
    ],
    "acceptance_criteria": [
        "Recommendations should increase high-quality fresh inputs, not stale volume.",
        "Recommendations should be testable with clear signals or experiments.",
    ],
    "context": (
        "Rochdale Daily is an automated local news site with existing GitHub "
        "Actions publishing workflows and a strict freshness guard."
    ),
}

ISSUE_MARKER = "<!-- dual-agent-bridge -->"
USER_AGENT = "RochdaleDailyDualAgentBridge/1.0"
GITHUB_API = "https://api.github.com"
OPENAI_API = "https://api.openai.com/v1/responses"
ANTHROPIC_API = "https://api.anthropic.com/v1/messages"
DEFAULT_OPENAI_MODEL = "gpt-5.2"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"
MAX_TEXT_CHARS = 4000
MAX_LIST_ITEMS = 8
MAX_ROUNDS = 3


class BridgeError(RuntimeError):
    """Raised when the bridge cannot produce a safe, structured result."""


def trim_text(value: Any, *, default: str = "", limit: int = MAX_TEXT_CHARS) -> str:
    text = str(value or default).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def normalise_string_list(value: Any, *, limit: int = MAX_LIST_ITEMS) -> list[str]:
    if value in (None, "", []):
        return []
    items = value if isinstance(value, list) else [value]
    cleaned: list[str] = []
    for item in items:
        text = trim_text(item)
        if text and text not in cleaned:
            cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def redact_text(text: str, secrets: list[str]) -> str:
    redacted = text
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[redacted]")
    return redacted


def redact_value(value: Any, secrets: list[str]) -> Any:
    if isinstance(value, str):
        return redact_text(value, secrets)
    if isinstance(value, list):
        return [redact_value(item, secrets) for item in value]
    if isinstance(value, dict):
        return {key: redact_value(item, secrets) for key, item in value.items()}
    return value


def extract_first_json_object(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    while start >= 0:
        depth = 0
        in_string = False
        escaping = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaping:
                    escaping = False
                elif char == "\\":
                    escaping = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : index + 1]
                    try:
                        data = json.loads(candidate)
                    except json.JSONDecodeError:
                        break
                    if isinstance(data, dict):
                        return data
                    break
        start = text.find("{", start + 1)
    return None


def load_json_text(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = extract_first_json_object(text)
    if not isinstance(data, dict):
        raise BridgeError("Expected a JSON object from the bridge payload.")
    return data


def parse_optional_int(value: Any) -> int | None:
    if value in (None, "", "null"):
        return None
    try:
        return int(str(value).strip())
    except ValueError as error:
        raise BridgeError(f"Expected an integer value, got {value!r}.") from error


def normalise_task_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, str):
        payload = {"task": payload}
    if not isinstance(payload, dict):
        raise BridgeError("Task payload must be a string or JSON object.")

    task = trim_text(payload.get("task"))
    if not task:
        raise BridgeError("Task payload is missing a non-empty 'task' field.")

    context = payload.get("context", "")
    if isinstance(context, (dict, list)):
        context = json.dumps(context, ensure_ascii=False, indent=2)

    constraints = normalise_string_list(payload.get("constraints"))
    acceptance = normalise_string_list(payload.get("acceptance_criteria"))
    return {
        "task": task,
        "constraints": constraints,
        "acceptance_criteria": acceptance,
        "context": trim_text(context, default=""),
    }


def extract_task_from_issue_body(title: str, body: str) -> dict[str, Any]:
    match = re.search(r"```json\s*(\{.*?\})\s*```", body, flags=re.DOTALL | re.IGNORECASE)
    if match:
        return normalise_task_payload(load_json_text(match.group(1)))
    if ISSUE_MARKER in body:
        after_marker = body.split(ISSUE_MARKER, 1)[1]
        data = extract_first_json_object(after_marker)
        if data:
            return normalise_task_payload(data)
    cleaned_title = title
    if cleaned_title.lower().startswith("[bridge]"):
        cleaned_title = cleaned_title[8:].strip()
    return normalise_task_payload(
        {
            "task": cleaned_title,
            "context": trim_text(body, default=""),
        }
    )


def request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request_headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise BridgeError(f"HTTP {error.code} from {url}: {detail}") from error
    except urllib.error.URLError as error:
        raise BridgeError(f"Network error calling {url}: {error.reason}") from error

    try:
        decoded = json.loads(body)
    except json.JSONDecodeError as error:
        raise BridgeError(f"Could not decode JSON response from {url}.") from error
    if not isinstance(decoded, dict):
        raise BridgeError(f"Unexpected JSON response type from {url}.")
    return decoded


def github_api_request(
    repository: str,
    path: str,
    *,
    token: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    del repository
    return request_json(
        f"{GITHUB_API}{path}",
        method=method,
        payload=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Accept": "application/vnd.github+json",
        },
    )


def fetch_issue_source(repository: str, issue_number: int, token: str) -> dict[str, Any]:
    payload = github_api_request(
        repository,
        f"/repos/{repository}/issues/{issue_number}",
        token=token,
    )
    title = trim_text(payload.get("title"))
    body = payload.get("body") or ""
    task = extract_task_from_issue_body(title, body)
    return {
        "kind": "pr" if "pull_request" in payload else "issue",
        "number": issue_number,
        "title": title,
        "url": payload.get("html_url"),
        "task": task,
    }


def fetch_pr_source(repository: str, pr_number: int, token: str) -> dict[str, Any]:
    payload = github_api_request(
        repository,
        f"/repos/{repository}/pulls/{pr_number}",
        token=token,
    )
    task = normalise_task_payload(
        {
            "task": trim_text(payload.get("title"), default=f"Review PR #{pr_number}"),
            "context": trim_text(payload.get("body"), default=""),
            "constraints": [
                "Review only. Do not merge, push, or rewrite repository history.",
            ],
        }
    )
    return {
        "kind": "pr",
        "number": pr_number,
        "title": trim_text(payload.get("title")),
        "url": payload.get("html_url"),
        "task": task,
    }


def post_issue_comment(repository: str, number: int, token: str, comment: str) -> dict[str, Any]:
    return github_api_request(
        repository,
        f"/repos/{repository}/issues/{number}/comments",
        token=token,
        method="POST",
        payload={"body": comment},
    )


def extract_openai_text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    for item in payload.get("output", []):
        if not isinstance(item, dict):
            continue
        for part in item.get("content", []):
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                text = part["text"].strip()
                if text:
                    return text
    raise BridgeError("OpenAI response did not include text output.")


def extract_anthropic_text(payload: dict[str, Any]) -> str:
    blocks = payload.get("content", [])
    parts: list[str] = []
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "text":
            text = trim_text(block.get("text"), default="", limit=12000)
            if text:
                parts.append(text)
    if not parts:
        raise BridgeError("Anthropic response did not include text output.")
    return "\n".join(parts).strip()


def call_openai(prompt: str, model: str, api_key: str) -> dict[str, Any]:
    payload = request_json(
        OPENAI_API,
        method="POST",
        payload={
            "model": model,
            "input": prompt,
            "reasoning": {"effort": "minimal"},
            "text": {"verbosity": "low"},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    text = extract_openai_text(payload)
    return load_json_text(text)


def call_anthropic(prompt: str, model: str, api_key: str) -> dict[str, Any]:
    payload = request_json(
        ANTHROPIC_API,
        method="POST",
        payload={
            "model": model,
            "max_tokens": 1600,
            "temperature": 0.2,
            "messages": [{"role": "user", "content": prompt}],
        },
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    text = extract_anthropic_text(payload)
    return load_json_text(text)


def normalise_recommendations(value: Any) -> list[dict[str, str]]:
    recommendations: list[dict[str, str]] = []
    if not isinstance(value, list):
        return recommendations
    for item in value[:MAX_LIST_ITEMS]:
        if not isinstance(item, dict):
            continue
        title = trim_text(item.get("title"))
        action = trim_text(item.get("action") or item.get("recommendation"))
        if not title or not action:
            continue
        recommendations.append(
            {
                "title": title,
                "action": action,
                "why": trim_text(item.get("why") or item.get("rationale")),
                "freshness_guard": trim_text(
                    item.get("freshness_guard"),
                    default="Keep the 14-hour newest-story requirement unchanged.",
                ),
                "evidence_to_watch": trim_text(
                    item.get("evidence_to_watch") or item.get("measurement")
                ),
                "effort": trim_text(item.get("effort"), default="medium"),
            }
        )
    return recommendations


def normalise_proposal(payload: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    proposal = {
        "summary": trim_text(payload.get("summary")),
        "recommendations": normalise_recommendations(payload.get("recommendations")),
        "risks": normalise_string_list(payload.get("risks")),
        "keep": normalise_string_list(payload.get("keep")) or task["constraints"],
        "questions": normalise_string_list(payload.get("questions")),
    }
    if not proposal["summary"]:
        raise BridgeError("Proposal did not include a summary.")
    if not proposal["recommendations"]:
        raise BridgeError("Proposal did not include any structured recommendations.")
    return proposal


def normalise_critique(payload: dict[str, Any]) -> dict[str, Any]:
    critique = {
        "summary": trim_text(payload.get("summary")),
        "strengths": normalise_string_list(payload.get("strengths")),
        "concerns": normalise_string_list(payload.get("concerns")),
        "missing_guards": normalise_string_list(payload.get("missing_guards")),
        "revision_requests": normalise_string_list(payload.get("revision_requests")),
        "consensus_points": normalise_string_list(payload.get("consensus_points")),
        "accept": bool(payload.get("accept")),
    }
    if not critique["summary"]:
        raise BridgeError("Critique did not include a summary.")
    if not critique["accept"] and not (
        critique["concerns"] or critique["missing_guards"] or critique["revision_requests"]
    ):
        critique["accept"] = True
    return critique


def proposal_prompt(task: dict[str, Any], revision_notes: list[str]) -> str:
    notes = "\n".join(f"- {item}" for item in revision_notes) or "- No prior critique."
    constraints = "\n".join(f"- {item}" for item in task["constraints"]) or "- None supplied."
    acceptance = (
        "\n".join(f"- {item}" for item in task["acceptance_criteria"]) or "- None supplied."
    )
    context = task["context"] or "No extra context supplied."
    return textwrap.dedent(
        f"""
        You are the proposing model in a two-model editorial systems review.
        Return JSON only, with no markdown or prose outside JSON.

        Required JSON shape:
        {{
          "summary": "string",
          "recommendations": [
            {{
              "title": "string",
              "action": "string",
              "why": "string",
              "freshness_guard": "string",
              "evidence_to_watch": "string",
              "effort": "low|medium|high"
            }}
          ],
          "risks": ["string"],
          "keep": ["string"],
          "questions": ["string"]
        }}

        Task:
        {task["task"]}

        Context:
        {context}

        Constraints:
        {constraints}

        Acceptance criteria:
        {acceptance}

        Prior critique to address:
        {notes}

        Focus on increasing fresh-story supply without lowering freshness standards.
        Do not propose autonomous merging, pushing, or publishing.
        """
    ).strip()


def critique_prompt(task: dict[str, Any], proposal: dict[str, Any]) -> str:
    constraints = "\n".join(f"- {item}" for item in task["constraints"]) or "- None supplied."
    acceptance = (
        "\n".join(f"- {item}" for item in task["acceptance_criteria"]) or "- None supplied."
    )
    proposal_json = json.dumps(proposal, ensure_ascii=False, indent=2)
    return textwrap.dedent(
        f"""
        You are the reviewing model in a two-model editorial systems review.
        Critique the proposal below. Return JSON only.

        Required JSON shape:
        {{
          "summary": "string",
          "strengths": ["string"],
          "concerns": ["string"],
          "missing_guards": ["string"],
          "revision_requests": ["string"],
          "consensus_points": ["string"],
          "accept": true
        }}

        Original task:
        {task["task"]}

        Constraints:
        {constraints}

        Acceptance criteria:
        {acceptance}

        Proposal JSON:
        {proposal_json}

        Mark "accept" false only when a material revision is needed.
        Keep the 14-hour newest-story rule intact.
        """
    ).strip()


def synthesise_consensus(
    task: dict[str, Any],
    rounds: list[dict[str, Any]],
    terminated_reason: str,
) -> dict[str, Any]:
    last_round = rounds[-1]
    proposal = last_round["proposal"]
    critique = last_round["critique"]
    guardrails = normalise_string_list(task["constraints"] + proposal["keep"] + critique["consensus_points"])
    consensus_summary = critique["summary"] if critique["accept"] else (
        f"{proposal['summary']} Reviewer accepted the direction only with the listed cautions."
    )
    return {
        "status": "accepted" if critique["accept"] else "accepted-with-cautions",
        "summary": trim_text(consensus_summary),
        "recommendations": proposal["recommendations"],
        "reviewer_concerns": normalise_string_list(
            critique["concerns"] + critique["missing_guards"] + critique["revision_requests"]
        ),
        "guardrails": guardrails,
        "terminated_reason": terminated_reason,
    }


def run_exchange(
    task: dict[str, Any],
    proposer: Callable[[str], dict[str, Any]],
    reviewer: Callable[[str], dict[str, Any]],
    *,
    max_rounds: int,
) -> dict[str, Any]:
    if max_rounds < 1 or max_rounds > MAX_ROUNDS:
        raise BridgeError(f"max_rounds must be between 1 and {MAX_ROUNDS}.")

    rounds: list[dict[str, Any]] = []
    revision_notes: list[str] = []
    terminated_reason = "max_rounds_reached"

    for round_number in range(1, max_rounds + 1):
        proposal = normalise_proposal(proposer(proposal_prompt(task, revision_notes)), task)
        critique = normalise_critique(reviewer(critique_prompt(task, proposal)))
        rounds.append(
            {
                "round": round_number,
                "proposal": proposal,
                "critique": critique,
            }
        )
        if critique["accept"]:
            terminated_reason = "reviewer_accepted"
            break
        revision_notes = normalise_string_list(
            critique["revision_requests"] + critique["missing_guards"] + critique["concerns"]
        )

    return {
        "task": task,
        "rounds": rounds,
        "terminated_reason": terminated_reason,
        "final": synthesise_consensus(task, rounds, terminated_reason),
    }


def build_comment_markdown(report: dict[str, Any], run_url: str, artifact_name: str) -> str:
    final = report["final"]
    recommendations = "\n".join(
        (
            f"- **{item['title']}**: {item['action']} "
            f"(freshness guard: {item['freshness_guard']}; measure: {item['evidence_to_watch'] or 'define a simple success metric'})"
        )
        for item in final["recommendations"]
    )
    concerns = "\n".join(f"- {item}" for item in final["reviewer_concerns"]) or "- None."
    guardrails = "\n".join(f"- {item}" for item in final["guardrails"]) or "- None supplied."
    return textwrap.dedent(
        f"""
        <!-- dual-agent-bridge-result -->
        ## Dual-agent bridge review

        - Run: {run_url}
        - Outcome: `{final['status']}`
        - Loop termination: `{report['terminated_reason']}` after {len(report['rounds'])} round(s)
        - Artifact: `{artifact_name}` on the linked Actions run

        ### Task
        {report['task']['task']}

        ### Consensus summary
        {final['summary']}

        ### Recommended actions
        {recommendations}

        ### Reviewer concerns
        {concerns}

        ### Guardrails kept
        {guardrails}
        """
    ).strip()


def write_outputs(report: dict[str, Any], comment: str, out_json: Path, out_md: Path) -> None:
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out_md.write_text(comment + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=os.getenv("GITHUB_REPOSITORY", ""))
    parser.add_argument("--issue-number", default="")
    parser.add_argument("--pr-number", default="")
    parser.add_argument("--task-json", default="")
    parser.add_argument("--openai-model", default=os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL))
    parser.add_argument(
        "--anthropic-model",
        default=os.getenv("ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL),
    )
    parser.add_argument("--max-rounds", type=int, default=1)
    parser.add_argument(
        "--out-json",
        default=str(REPORTS_DIR / "dual_agent_bridge_report.json"),
    )
    parser.add_argument(
        "--out-markdown",
        default=str(REPORTS_DIR / "dual_agent_bridge_comment.md"),
    )
    parser.add_argument(
        "--artifact-name",
        default=os.getenv("BRIDGE_ARTIFACT_NAME", "dual-agent-bridge-report"),
    )
    return parser.parse_args()


def load_source(args: argparse.Namespace, github_token: str) -> dict[str, Any]:
    if not args.repository:
        raise BridgeError("GITHUB_REPOSITORY or --repository is required.")
    issue_number = parse_optional_int(args.issue_number)
    pr_number = parse_optional_int(args.pr_number)
    if issue_number:
        return fetch_issue_source(args.repository, issue_number, github_token)
    if pr_number:
        return fetch_pr_source(args.repository, pr_number, github_token)
    if args.task_json.strip():
        return {
            "kind": "task_json",
            "number": None,
            "title": "workflow_dispatch task",
            "url": "",
            "task": normalise_task_payload(load_json_text(args.task_json)),
        }
    return {
        "kind": "default",
        "number": None,
        "title": "default bridge task",
        "url": "",
        "task": normalise_task_payload(DEFAULT_TASK),
    }


def run_url(repository: str) -> str:
    server_url = os.getenv("GITHUB_SERVER_URL", "https://github.com")
    run_id = os.getenv("GITHUB_RUN_ID", "")
    return f"{server_url}/{repository}/actions/runs/{run_id}" if run_id else server_url


def failure_comment(message: str, run_link: str) -> str:
    return textwrap.dedent(
        f"""
        <!-- dual-agent-bridge-result -->
        ## Dual-agent bridge failed

        - Run: {run_link}
        - Failure: {message}
        """
    ).strip()


def main() -> int:
    args = parse_args()
    secrets = [
        os.getenv("OPENAI_API_KEY", ""),
        os.getenv("ANTHROPIC_API_KEY", ""),
        os.getenv("GITHUB_TOKEN", ""),
    ]
    github_token = os.getenv("GITHUB_TOKEN", "")
    openai_key = os.getenv("OPENAI_API_KEY", "")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    output_json = Path(args.out_json)
    output_md = Path(args.out_markdown)
    run_link = run_url(args.repository)

    try:
        if not github_token:
            raise BridgeError("GITHUB_TOKEN is required.")
        if not openai_key:
            raise BridgeError("OPENAI_API_KEY is required.")
        if not anthropic_key:
            raise BridgeError("ANTHROPIC_API_KEY is required.")

        source = load_source(args, github_token)
        report = run_exchange(
            source["task"],
            lambda prompt: call_openai(prompt, args.openai_model, openai_key),
            lambda prompt: call_anthropic(prompt, args.anthropic_model, anthropic_key),
            max_rounds=args.max_rounds,
        )
        report["source"] = {
            "kind": source["kind"],
            "number": source["number"],
            "title": source["title"],
            "url": source["url"],
        }
        report["models"] = {
            "proposer": {"provider": "openai", "model": args.openai_model},
            "reviewer": {"provider": "anthropic", "model": args.anthropic_model},
        }
        report["run_url"] = run_link
        comment = build_comment_markdown(report, run_link, args.artifact_name)
        safe_report = redact_value(report, secrets)
        safe_comment = redact_text(comment, secrets)
        write_outputs(safe_report, safe_comment, output_json, output_md)
        if source["number"]:
            posted = post_issue_comment(args.repository, int(source["number"]), github_token, safe_comment)
            safe_report["comment_url"] = posted.get("html_url")
            write_outputs(safe_report, safe_comment, output_json, output_md)
        print("Dual-agent bridge review completed.")
        return 0
    except Exception as error:  # noqa: BLE001 - report failures back into GitHub Actions
        safe_message = redact_text(str(error), secrets)
        comment = failure_comment(safe_message, run_link)
        failure_report = {
            "status": "failed",
            "error": safe_message,
            "run_url": run_link,
        }
        write_outputs(failure_report, comment, output_json, output_md)
        issue_number = parse_optional_int(args.issue_number)
        pr_number = parse_optional_int(args.pr_number)
        comment_target = issue_number or pr_number
        if github_token and args.repository and comment_target:
            try:
                post_issue_comment(args.repository, int(comment_target), github_token, comment)
            except Exception:
                pass
        print(safe_message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())