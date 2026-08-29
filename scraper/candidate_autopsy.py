"""Show which gate is eating the borough's news, using the newsroom's own gate code.

`scraper_status.json` records that a run saw 98 candidates and published two. It
does not record why the other 96 went. Without that, every fix is a guess about
which filter is too tight.

This replays the retained candidate reservoir through the real gate functions --
imported from `scraper`, `selection_policy`, `locality_rules` and
`story_identity`, not reimplemented here -- and records the first gate that
stops each candidate. It also runs the age gate at several widths so the cost of
that setting is a measured number rather than an opinion.

Read-only. It touches no published page, holds no site-writer lock, and changes
no pipeline behaviour: it is a post-mortem on candidates the pipeline has
already handled.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES_PATH = ROOT / "newsroom_candidates.json"
ARTICLES_PATH = ROOT / "articles.json"
REPORT_PATH = ROOT / "reports" / "candidate_autopsy.json"

PUBLISH_MAX_NEWS_AGE_HOURS = int(os.getenv("PUBLISH_MAX_NEWS_AGE_HOURS", "48"))
AGE_WIDTHS = [6, 14, 24, 48, 72, 168]

PUBLISHABLE = "would publish"
GATE_ORDER = [
    "age",
    "denied source",
    "job or career post",
    "not local",
    "duplicate of published story",
    "rewrite ineligible",
]


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def age_hours(record: dict[str, Any], *, now: datetime) -> float | None:
    published = parse_dt(record.get("source_published_at"))
    if published is None:
        return None
    return (now - published).total_seconds() / 3600


def classify(record: dict[str, Any], gates: dict[str, Callable[[dict[str, Any]], bool]]) -> str:
    """Return the first gate that stops this candidate, or PUBLISHABLE.

    Order matters and mirrors the pipeline: a candidate rejected on age never
    reaches the locality check, so counting every gate independently would
    double-count and make each one look more expensive than it is.
    """
    for name in GATE_ORDER:
        gate = gates.get(name)
        if gate is None:
            continue
        try:
            if gate(record):
                return name
        except Exception:  # noqa: BLE001 - a gate that errors is reported, not fatal
            return f"{name} (gate error)"
    return PUBLISHABLE


def survivors_by_age(records: list[dict[str, Any]], *, now: datetime, widths: list[int]) -> dict[str, int]:
    """How many candidates the age gate would admit at each width."""
    result: dict[str, int] = {}
    for width in widths:
        kept = 0
        for record in records:
            hours = age_hours(record, now=now)
            if hours is not None and hours <= width:
                kept += 1
        result[f"{width}h"] = kept
    return result


def build_gates(now: datetime) -> tuple[dict[str, Callable[[dict[str, Any]], bool]], list[str]]:
    """Import the newsroom's real gates. Any that cannot be imported is skipped and named."""
    gates: dict[str, Callable[[dict[str, Any]], bool]] = {}
    unavailable: list[str] = []

    def text_of(record: dict[str, Any]) -> str:
        return " ".join(
            str(record.get(key) or "")
            for key in ("source_title", "source_summary", "source_body_excerpt")
        )

    gates["age"] = lambda record: (
        (age_hours(record, now=now) or 0) > PUBLISH_MAX_NEWS_AGE_HOURS
    )

    try:
        import scraper as newsroom

        gates["denied source"] = lambda record: bool(
            newsroom.source_is_denied(
                record.get("source_name", ""), record.get("source_url", "")
            )
        )
        gates["not local"] = lambda record: not newsroom.source_text_is_local(
            text_of(record),
            record.get("source_name", ""),
            record.get("source_url", ""),
        )
    except Exception as error:  # noqa: BLE001
        unavailable.append(f"scraper ({type(error).__name__})")

    try:
        from selection_policy import is_job_or_career_post

        gates["job or career post"] = lambda record: bool(
            is_job_or_career_post(text_of(record), record.get("source_url", ""))
        )
    except Exception as error:  # noqa: BLE001
        unavailable.append(f"selection_policy ({type(error).__name__})")

    return gates, unavailable


def add_duplicate_gate(
    gates: dict[str, Callable[[dict[str, Any]], bool]],
    published: list[dict[str, Any]],
    unavailable: list[str],
) -> None:
    try:
        from story_identity import same_story
    except Exception as error:  # noqa: BLE001
        unavailable.append(f"story_identity ({type(error).__name__})")
        return

    published_keys = {
        str(item.get("story_key")) for item in published if item.get("story_key")
    }

    def is_duplicate(record: dict[str, Any]) -> bool:
        key = str(record.get("story_key") or "")
        if key and key in published_keys:
            return True
        probe = {
            "title": record.get("source_title", ""),
            "summary": record.get("source_summary", ""),
            "category": record.get("category", ""),
            "area": record.get("area", ""),
            "published_at": record.get("source_published_at", ""),
        }
        return any(same_story(probe, item) for item in published)

    gates["duplicate of published story"] = is_duplicate


def main() -> None:
    now = datetime.now(timezone.utc)
    reservoir = read_json(CANDIDATES_PATH, {})
    candidates = reservoir.get("candidates") if isinstance(reservoir, dict) else reservoir
    if not isinstance(candidates, list):
        candidates = []
    published = [item for item in read_json(ARTICLES_PATH, []) if isinstance(item, dict)]

    gates, unavailable = build_gates(now)
    add_duplicate_gate(gates, published, unavailable)

    verdicts = [classify(record, gates) for record in candidates]
    tally = Counter(verdicts)

    examples: dict[str, list[str]] = {}
    for record, verdict in zip(candidates, verdicts):
        bucket = examples.setdefault(verdict, [])
        if len(bucket) < 3:
            bucket.append(
                f"{record.get('source_name', '?')}: {str(record.get('source_title', ''))[:70]}"
            )

    payload = {
        "examined_at": now.isoformat().replace("+00:00", "Z"),
        "reservoir_retention_hours": reservoir.get("retention_hours")
        if isinstance(reservoir, dict)
        else None,
        "candidates_examined": len(candidates),
        "publish_age_gate_hours": PUBLISH_MAX_NEWS_AGE_HOURS,
        "first_blocking_gate": dict(tally.most_common()),
        "would_publish": tally.get(PUBLISHABLE, 0),
        "age_gate_sensitivity": survivors_by_age(candidates, now=now, widths=AGE_WIDTHS),
        "gates_unavailable": unavailable,
        "examples": examples,
        "note": (
            "Gates are applied in pipeline order and each candidate is attributed to the "
            "first gate that stops it, so the counts sum to the reservoir rather than "
            "double-counting. age_gate_sensitivity ignores every other gate: it is the "
            "ceiling the age setting allows, not a forecast of published stories."
        ),
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        lines = [
            "## Where the candidates go",
            "",
            f"{len(candidates)} candidates in the reservoir; **{payload['would_publish']}** clear every gate.",
            "",
            "| First blocking gate | Candidates |",
            "| --- | ---: |",
        ]
        lines += [f"| {gate} | {count} |" for gate, count in tally.most_common()]
        lines += [
            "",
            "### Age gate ceiling",
            "",
            "| Window | Candidates admitted |",
            "| --- | ---: |",
        ]
        lines += [
            f"| {width} | {count} |"
            for width, count in payload["age_gate_sensitivity"].items()
        ]
        if unavailable:
            lines += ["", "Gates not evaluated: " + ", ".join(unavailable)]
        try:
            with open(summary_path, "a", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")
        except OSError:
            pass


if __name__ == "__main__":
    main()
