# Dual-agent collaboration bridge

The repository now includes a comment-only bridge that lets OpenAI and
Anthropic review the same GitHub task with GitHub remaining the source of
truth.

## What it does

- Accepts a GitHub issue, a GitHub pull request, or a structured task payload.
- Asks one model to lead with a proposal or review.
- Asks the other model to critique that response.
- Repeats the exchange only up to the configured round limit.
- Produces a structured consensus artifact and uploads it to the workflow run.
- Posts the consensus back to the issue or pull request as a top-level comment
  when the target is an issue or pull request.

## Guardrails

- The workflow is manual only through `workflow_dispatch`.
- Workflow permissions are restricted to:
  - `contents: read`
  - `issues: write`
  - `pull-requests: read`
- `actions/checkout` runs with `persist-credentials: false`.
- The bridge never writes repository contents, never opens a merge path, and
  never calls any destructive GitHub endpoint.
- The model prompt explicitly says the run is comment only. If destructive or
  privileged work is suggested, the model must mark it for human review.
- The consensus artifact always records:
  - `merge_allowed: false`
  - `push_allowed: false`
  - `human_review_required: true`

## Required secrets

Add these repository-level GitHub Actions secrets before the workflow can call
the model APIs:

- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`

`GITHUB_TOKEN` is supplied automatically by GitHub Actions.

## Manual setup

1. Open the repository on GitHub.
2. Go to `Settings -> Secrets and variables -> Actions`.
3. Add `OPENAI_API_KEY`.
4. Add `ANTHROPIC_API_KEY`.

The current GitHub connector available in this task can create repo code and
workflows, but it cannot populate Actions secrets, so the two API keys still
need manual entry.

## How to run it

1. Open `Actions`.
2. Select `Dual-agent collaboration bridge`.
3. Choose the inputs:
   - `target_type`: `issue`, `pull_request`, or `task`
   - `target_number`: the issue or PR number when applicable
   - `task_json`: a structured task payload when `target_type=task`
   - `lead_provider`: `openai` or `anthropic`
   - `max_rounds`: `1` to `3`
   - `openai_model`: defaults to `gpt-5`
   - `anthropic_model`: defaults to `claude-sonnet-4-20250514`
4. Run the workflow.

## Example task payload

```json
{
  "title": "Review the SEO metadata refactor",
  "objective": "Compare two model assessments before a human decides whether to proceed.",
  "acceptance_criteria": [
    "Return a structured consensus artifact",
    "Do not merge automatically"
  ],
  "constraints": [
    "Comment only",
    "Use GitHub Actions secrets"
  ],
  "changed_files": [
    "scraper/editorial_upgrade.py",
    "README.md"
  ]
}
```

## Output

- For issue and pull request targets, the workflow posts a top-level GitHub
  comment with a human-readable summary and an embedded JSON artifact.
- For every run, the workflow uploads:
  - `dual-agent-bridge-artifact.json`
  - `dual-agent-bridge-comment.md`
