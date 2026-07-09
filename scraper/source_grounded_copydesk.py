from __future__ import annotations

import html
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from openai import OpenAI

from house_style import (
    HOUSE_STYLE_SYSTEM,
    STYLE_VERSION,
    first_reference_issues,
    style_issues,
)

ROOT = Path(__file__).resolve().parents[1]
ARTICLES_PATH = ROOT / "articles.json"
MODEL = os.getenv("OPENAI_STYLE_MODEL") or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
WORKERS = max(1, int(os.getenv("SOURCE_COPYDESK_WORKERS", "4")))
LIMIT = max(1, int(os.getenv("SOURCE_COPYDESK_LIMIT", "180")))
TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("source-copydesk")

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (compatible; RochdaleDailyEditorial/1.0; "
        "+https://rochdaledaily.co.uk/)"
    )
})

SCHEMA = {
    "name": "source_grounded_precision_article",
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
                "maxItems": 9,
            },
        },
        "required": ["publishable", "title", "excerpt", "paragraphs"],
    },
}

HIGH_RISK_RE = re.compile(
    r"\b(?:murder|manslaughter|death|died|dead|fatal|fire|rape|sexual|grooming|"
    r"arrest|charged|court|police|stabbing|shooting|assault|burglary|fraud)\b",
    re.I,
)

REACTION_CLAIM_RE = re.compile(
    r"\b(?:residents|community|neighbours|locals).{0,80}"
    r"(?:expressed|shared|posted|condolences|shock|sorrow|rallied|coming together)\b",
    re.I,
)
REACTION_EVIDENCE_RE = re.compile(
    r"\b(?:resident|neighbour|community member|social media|facebook|condolence|tribute|"
    r"said|told|wrote|posted)\b",
    re.I,
)
PREDICTION_RE = re.compile(
    r"\b(?:council|authority|authorities|officials).{0,100}"
    r"(?:is expected to|are expected to|will convene|will implement|will introduce|"
    r"will announce|will review|will enhance)\b",
    re.I,
)
APPEAL_CLAIM_RE = re.compile(
    r"\bpolice (?:are|were|have been) (?:actively )?appealing\b|"
    r"\bappeal(?:ed|ing)? for (?:witnesses|information)\b",
    re.I,
)
APPEAL_EVIDENCE_RE = re.compile(
    r"\b(?:appeal|witness|information|contact police|come forward|dashcam|CCTV)\b",
    re.I,
)
SUSPECT_RE = re.compile(r"\bsuspect\b", re.I)
MOTHER_RE = re.compile(r"\bmother\b|\bmum\b", re.I)
FARM_RE = re.compile(r"\bfarm\b", re.I)
MILNROW_RE = re.compile(r"\bMilnrow\b", re.I)

LEXICAL_REPLACEMENTS = {
    r"\bsummoned to\b": "called to",
    r"\bat the location\b": "at the scene",
    r"\bworking diligently to piece together\b": "investigating",
    r"\bthe arrested individual\b": "the arrested person",
    r"\ban arrested individual\b": "a person who was arrested",
    r"\bthe blaze\b": "the fire",
}


def plain_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def body_word_count(paragraphs: list[str]) -> int:
    return len(re.findall(r"\b[\w’'-]+\b", " ".join(paragraphs)))


def numbers(value: str) -> set[str]:
    return set(re.findall(r"\b\d+(?:[.,]\d+)?%?\b", value))


def source_urls(article: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    primary = str(article.get("source_url") or "").strip()
    if primary:
        urls.append(primary)
    for value in article.get("source_urls") or []:
        url = str(value or "").strip()
        if url and url not in urls:
            urls.append(url)
    return urls[:12]


def extract_page(url: str) -> dict[str, str] | None:
    try:
        response = SESSION.get(url, timeout=TIMEOUT, allow_redirects=True)
        response.raise_for_status()
    except Exception as exc:
        log.debug("Source fetch failed for %s: %s", url, exc)
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    for node in soup(["script", "style", "nav", "footer", "form", "aside"]):
        node.decompose()

    title = ""
    for selector, attribute in (
        ('meta[property="og:title"]', "content"),
        ('meta[name="twitter:title"]', "content"),
    ):
        node = soup.select_one(selector)
        if node and node.get(attribute):
            title = plain_text(node.get(attribute))
            break
    if not title and soup.title:
        title = plain_text(soup.title.get_text(" ", strip=True))

    description = ""
    for selector in (
        'meta[property="og:description"]',
        'meta[name="description"]',
    ):
        node = soup.select_one(selector)
        if node and node.get("content"):
            description = plain_text(node.get("content"))
            break

    container = (
        soup.find("article")
        or soup.find("main")
        or soup.find(attrs={"role": "main"})
        or soup.body
    )
    paragraphs: list[str] = []
    if container:
        for node in container.find_all(["p", "h2", "li"]):
            text = plain_text(node.get_text(" ", strip=True))
            if len(text.split()) >= 5 and text not in paragraphs:
                paragraphs.append(text)
            if sum(len(item) for item in paragraphs) >= 9000:
                break

    body = " ".join(paragraphs)
    combined = plain_text(" ".join([title, description, body]))
    if len(combined.split()) < 25:
        return None

    return {
        "url": response.url,
        "domain": (urlparse(response.url).hostname or "").removeprefix("www."),
        "title": title,
        "description": description,
        "body": body[:9000],
    }


def collect_evidence(article: dict[str, Any]) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    seen: set[str] = set()
    for url in source_urls(article):
        record = extract_page(url)
        if not record:
            continue
        key = record["url"]
        if key in seen:
            continue
        seen.add(key)
        records.append(record)
    return records


def normalise(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    paragraphs: list[str] = []
    seen: set[str] = set()
    for item in raw.get("paragraphs") or []:
        paragraph = plain_text(item)
        for pattern, replacement in LEXICAL_REPLACEMENTS.items():
            paragraph = re.sub(pattern, replacement, paragraph, flags=re.I)
        key = paragraph.casefold()
        if not paragraph or key in seen:
            continue
        seen.add(key)
        paragraphs.append(paragraph)

    title = plain_text(raw.get("title"))[:160]
    excerpt = plain_text(raw.get("excerpt"))[:360]
    return {
        "publishable": bool(raw.get("publishable")),
        "title": title,
        "excerpt": excerpt,
        "paragraphs": paragraphs[:9],
    }


def evidence_issues(draft: dict[str, Any], evidence: str) -> list[str]:
    issues = style_issues(draft)
    issues.extend(first_reference_issues(draft))
    combined = plain_text(" ".join([
        draft.get("title", ""),
        draft.get("excerpt", ""),
        *(draft.get("paragraphs") or []),
    ]))

    if not draft.get("publishable"):
        issues.append("Rewrite the supported local report rather than refusing it.")
    count = body_word_count(draft.get("paragraphs") or [])
    if count < 200:
        issues.append(f"Expand the body to at least 200 words; it contains {count}.")
    if count > 650:
        issues.append("Tighten the report to fewer than 650 words.")

    invented_numbers = numbers(combined) - numbers(evidence)
    if invented_numbers:
        issues.append(
            "Remove numerical details absent from the sources: "
            + ", ".join(sorted(invented_numbers))
        )

    if SUSPECT_RE.search(combined) and not SUSPECT_RE.search(evidence):
        issues.append("Use 'person arrested' rather than 'suspect'; the sources do not use suspect.")
    if MOTHER_RE.search(combined) and not MOTHER_RE.search(evidence):
        issues.append("Remove 'mother'; the relationship is not established by the source evidence.")
    if FARM_RE.search(combined) and not FARM_RE.search(evidence):
        issues.append("Remove 'farm'; the source evidence does not establish that location.")
    if MILNROW_RE.search(combined) and not MILNROW_RE.search(evidence):
        issues.append("Remove 'Milnrow'; the source evidence does not establish that place.")
    if REACTION_CLAIM_RE.search(combined) and not REACTION_EVIDENCE_RE.search(evidence):
        issues.append("Remove the invented community or social-media reaction.")
    if PREDICTION_RE.search(combined):
        issues.append("Remove predictions about council meetings, reviews, announcements or measures.")
    if APPEAL_CLAIM_RE.search(combined) and not APPEAL_EVIDENCE_RE.search(evidence):
        issues.append("Do not attribute a witness appeal to police; the source evidence does not record one.")

    return list(dict.fromkeys(issues))


def is_high_risk(article: dict[str, Any]) -> bool:
    text = " ".join([
        str(article.get("category") or ""),
        plain_text(article.get("title")),
        plain_text(article.get("excerpt")),
    ])
    return bool(HIGH_RISK_RE.search(text))


def rewrite_article(article: dict[str, Any]) -> tuple[dict[str, Any], str]:
    records = collect_evidence(article)
    evidence = plain_text(" ".join(
        f"{record['title']} {record['description']} {record['body']}"
        for record in records
    ))

    if len(evidence.split()) < 80:
        kept = dict(article)
        kept.pop("editorial_style_version", None)
        kept["source_grounding_status"] = "insufficient-source-text"
        if is_high_risk(article):
            kept["status"] = "pending_context"
            kept["style_rewrite_status"] = "held-for-source-grounding"
            return kept, "held-for-source-grounding"
        return kept, "insufficient-source-text"

    prompt = {
        "task": (
            "Write a new article from the source records. Do not treat the previous Rochdale Daily article as "
            "evidence. Use exact ordinary nouns, verbs and adjectives. Preserve every supported material fact. "
            "Apply strict first-reference grammar: an unidentified person must first be introduced with the "
            "same noun and an indefinite article. Write 'A woman was pronounced dead at the scene', never "
            "'The woman was pronounced dead' unless 'a woman' has already appeared earlier in the body. "
            "Likewise, introduce 'a man', 'a person', 'a mother' or 'a father' before the corresponding "
            "definite noun. Do not treat a different role noun as the same grammatical introduction. "
            "but exclude every claim not established by the source records. "
            "For a police matter, add the Rochdale Daily reporting-route sentence near the end. "
            "For a death, close with the approved editorial expression of sympathy. "
            "If the story has multiple sources, the visible label will be added separately; do not write it."
        ),
        "working_title_not_evidence": article.get("title"),
        "category": article.get("category"),
        "area": article.get("area"),
        "is_ongoing": bool(article.get("is_ongoing")),
        "source_records": records,
        "requirements": {
            "lexical_precision": "paramount",
            "first_reference_grammar": (
                "Use a woman/man/person/mother/father before the matching definite noun."
            ),
            "body_words": "220-550, absolute minimum 200",
            "paragraphs": "5-9",
            "new_facts_forbidden": True,
            "community_reaction_requires_source": True,
            "future_official_action_requires_source": True,
            "crime_contact_sentence": (
                "Anyone with information can find Greater Manchester Police and "
                "Crimestoppers contact details at the end of this article."
            ),
            "death_closing_sentence": (
                "Our thoughts are with the family and all those affected."
            ),
        },
    }

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    previous = None
    feedback: list[str] = []
    best: dict[str, Any] | None = None

    for attempt in range(5):
        current_prompt = dict(prompt)
        if attempt:
            current_prompt["previous_draft"] = previous
            current_prompt["repair_required"] = feedback
            current_prompt["repair_instruction"] = (
                "Rewrite again. Correct every listed issue. Prefer the most accurate ordinary word to a dramatic "
                "or literary synonym. Correct anonymous-person first references exactly: use 'a woman' before "
                "'the woman', and the same rule for man, person, mother and father. Do not remove verified "
                "facts. Do not add a claim."
            )

        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": HOUSE_STYLE_SYSTEM},
                {"role": "user", "content": json.dumps(current_prompt, ensure_ascii=False)},
            ],
            response_format={"type": "json_schema", "json_schema": SCHEMA},
            temperature=0.08,
            max_tokens=3500,
        )
        draft = normalise(json.loads(response.choices[0].message.content or "{}"))
        feedback = evidence_issues(draft, evidence)
        if not feedback:
            best = draft
            break
        previous = draft
        log.info(
            "Precision repair %d for %s: %s",
            attempt + 1,
            article.get("title"),
            "; ".join(feedback),
        )

    if not best:
        kept = dict(article)
        kept.pop("editorial_style_version", None)
        kept["style_rewrite_status"] = "needs-source-grounded-retry"
        kept["style_rewrite_issues"] = feedback[:10]
        if is_high_risk(article):
            kept["status"] = "pending_context"
            return kept, "held-after-failed-grounding"
        return kept, "needs-source-grounded-retry"

    updated = dict(article)
    updated["title"] = best["title"]
    updated["excerpt"] = best["excerpt"]
    updated["summary"] = best["excerpt"]
    body = "".join(f"<p>{html.escape(paragraph)}</p>" for paragraph in best["paragraphs"])
    if article.get("is_ongoing") or len(source_urls(article)) > 1:
        body = (
            '<p class="ongoing-label"><strong>ONGOING STORY</strong> — '
            'This report brings together developments from multiple sources.</p>'
            + body
        )

    updated["content_html"] = body
    updated["status"] = "published"
    updated["editorial_style_version"] = STYLE_VERSION
    updated["publication_route"] = "ai-source-grounded-precision-edit"
    updated["rewrite_quality_checked"] = True
    updated["source_grounding_status"] = "passed"
    updated["style_rewrite_status"] = "passed"
    updated.pop("style_rewrite_issues", None)
    return updated, "passed"


def main() -> int:
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is missing")

    articles = json.loads(ARTICLES_PATH.read_text(encoding="utf-8"))
    targets = [
        article for article in articles
        if isinstance(article, dict)
        and str(article.get("source_kind") or "article").lower() != "event"
        and (
            str(article.get("status") or "published") == "published"
            or article.get("style_rewrite_status") in {
                "needs-editorial-retry",
                "needs-source-grounded-retry",
                "held-for-source-grounding",
            }
        )
        and article.get("editorial_style_version") != STYLE_VERSION
    ][:LIMIT]

    results: dict[str, dict[str, Any]] = {}
    stats: dict[str, int] = {}

    def worker(article: dict[str, Any]) -> tuple[str, dict[str, Any], str]:
        updated, status = rewrite_article(article)
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
    log.info("Source-grounded precision copydesk complete: %s", stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
