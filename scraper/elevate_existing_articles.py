from __future__ import annotations

import html
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from openai import OpenAI

from house_style import HOUSE_STYLE_SYSTEM, STYLE_VERSION, style_issues

ROOT = Path(__file__).resolve().parents[1]
ARTICLES_PATH = ROOT / "articles.json"
MODEL = os.getenv("OPENAI_STYLE_MODEL") or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
WORKERS = max(1, int(os.getenv("STYLE_REWRITE_WORKERS", "4")))
LIMIT = max(1, int(os.getenv("STYLE_REWRITE_LIMIT", "180")))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("style-rewrite")

SCHEMA = {
    "name": "professional_local_article_edit",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "publishable": {"type": "boolean"},
            "title": {"type": "string"},
            "excerpt": {"type": "string"},
            "paragraphs": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 5,
                "maxItems": 10,
            },
        },
        "required": ["publishable", "title", "excerpt", "paragraphs"],
    },
}


def plain_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def body_word_count(paragraphs: list[str]) -> int:
    return len(re.findall(r"\b[\w’'-]+\b", " ".join(paragraphs)))


def numbers(value: str) -> set[str]:
    return set(re.findall(r"\b\d+(?:[.,]\d+)?%?\b", value))


def normalise(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    paragraphs: list[str] = []
    seen: set[str] = set()
    for item in raw.get("paragraphs") or []:
        paragraph = plain_text(item)
        key = paragraph.casefold()
        if not paragraph or key in seen:
            continue
        seen.add(key)
        paragraphs.append(paragraph)
    return {
        "publishable": bool(raw.get("publishable")),
        "title": plain_text(raw.get("title"))[:160],
        "excerpt": plain_text(raw.get("excerpt"))[:360],
        "paragraphs": paragraphs[:10],
    }


def draft_score(draft: dict[str, Any], evidence: str) -> tuple[int, list[str]]:
    feedback: list[str] = []
    count = body_word_count(draft.get("paragraphs") or [])
    if not draft.get("publishable"):
        feedback.append("Revise the article rather than refusing a supported local story.")
    if count < 200:
        feedback.append(f"Expand the body to at least 200 words; it contains {count}.")
    if count > 750:
        feedback.append("Tighten the article to fewer than 750 words.")
    if len(draft.get("title", "").split()) < 4:
        feedback.append("Write a complete, specific headline.")
    feedback.extend(style_issues(draft))

    invented = numbers(
        " ".join([
            draft.get("title", ""),
            draft.get("excerpt", ""),
            *(draft.get("paragraphs") or []),
        ])
    ) - numbers(evidence)
    if invented:
        feedback.append(
            "Remove numerical details absent from the supplied article: "
            + ", ".join(sorted(invented))
        )
    return len(feedback), feedback


def edit_article(article: dict[str, Any]) -> tuple[dict[str, Any], str]:
    original_body = plain_text(article.get("content_html"))
    evidence = " ".join([
        plain_text(article.get("title")),
        plain_text(article.get("excerpt") or article.get("summary")),
        original_body,
    ])
    if len(re.findall(r"\b[\w’'-]+\b", evidence)) < 120:
        return article, "insufficient-existing-evidence"

    prompt = {
        "task": (
            "Line-edit this existing local-news article into polished, authoritative British journalism. "
            "Treat the current article as the complete factual evidence bundle. Retain every useful verified fact, "
            "but rewrite the prose rather than merely polishing individual sentences. "
            "Keep a substantive local-impact paragraph. Explain practical implications for commuters, families, "
            "businesses or services where the facts reasonably support them, using measured conditional language. "
            "Do not delete local context simply because it is explanatory. Do not add any new case-specific fact."
        ),
        "article": {
            "title": article.get("title"),
            "standfirst": article.get("excerpt") or article.get("summary"),
            "body": original_body,
            "category": article.get("category"),
            "area": article.get("area"),
            "is_ongoing": bool(article.get("is_ongoing")),
            "source_names": article.get("source_names") or [article.get("source_name")],
        },
        "requirements": {
            "body_words": "250-600, absolute minimum 200",
            "paragraphs": "5-10",
            "retain_local_impact_context": True,
            "new_facts_forbidden": True,
            "house_style_version": STYLE_VERSION,
        },
    }

    best: dict[str, Any] | None = None
    best_score = 999
    previous = None
    feedback: list[str] = []

    for attempt in range(3):
        current_prompt = dict(prompt)
        if attempt:
            current_prompt["previous_draft"] = previous
            current_prompt["repair_required"] = feedback

        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": HOUSE_STYLE_SYSTEM},
                {"role": "user", "content": json.dumps(current_prompt, ensure_ascii=False)},
            ],
            response_format={"type": "json_schema", "json_schema": SCHEMA},
            temperature=0.16,
            max_tokens=3500,
        )
        draft = normalise(json.loads(response.choices[0].message.content or "{}"))
        score, feedback = draft_score(draft, evidence)

        if score < best_score:
            best = draft
            best_score = score
        if score == 0:
            break
        previous = draft

    if not best or body_word_count(best.get("paragraphs") or []) < 200:
        kept = dict(article)
        kept["style_rewrite_status"] = "kept-original"
        return kept, "kept-original"

    updated = dict(article)
    updated["title"] = best["title"]
    updated["excerpt"] = best["excerpt"]
    updated["summary"] = best["excerpt"]
    body = "".join(f"<p>{html.escape(paragraph)}</p>" for paragraph in best["paragraphs"])
    if article.get("is_ongoing"):
        body = (
            '<p class="ongoing-label"><strong>ONGOING STORY</strong> — '
            'This report brings together confirmed developments from multiple sources.</p>'
            + body
        )
    updated["content_html"] = body
    updated["editorial_style_version"] = STYLE_VERSION
    updated["publication_route"] = "ai-professional-style-edit"
    updated["rewrite_quality_checked"] = True
    updated["style_rewrite_status"] = "passed" if best_score == 0 else "best-safe-draft"
    return updated, updated["style_rewrite_status"]


def main() -> int:
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is missing")

    articles = json.loads(ARTICLES_PATH.read_text(encoding="utf-8"))
    targets = [
        article for article in articles
        if isinstance(article, dict)
        and str(article.get("status") or "published") == "published"
        and str(article.get("source_kind") or "article").lower() != "event"
        and article.get("editorial_style_version") != STYLE_VERSION
    ][:LIMIT]

    results: dict[str, dict[str, Any]] = {}
    stats: dict[str, int] = {}

    def worker(article: dict[str, Any]) -> tuple[str, dict[str, Any], str]:
        updated, status = edit_article(article)
        key = str(article.get("id") or article.get("slug") or article.get("story_key"))
        return key, updated, status

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = [executor.submit(worker, article) for article in targets]
        for future in as_completed(futures):
            key, updated, status = future.result()
            results[key] = updated
            stats[status] = stats.get(status, 0) + 1
            log.info("%s: %s", status, updated.get("title"))

    output: list[dict[str, Any]] = []
    for article in articles:
        key = str(article.get("id") or article.get("slug") or article.get("story_key"))
        output.append(results.get(key, article))

    ARTICLES_PATH.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("Professional style rewrite complete: %s", stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
