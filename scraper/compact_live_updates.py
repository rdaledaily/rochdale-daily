#!/usr/bin/env python3
"""Compact repetitive LIVE timelines without hiding genuine developments.

Automated source rewrites can describe the same development with slightly
changed wording on successive passes. Exact-string dedupe is not enough for a
reader-facing live timeline, but aggressive semantic dedupe risks hiding a real
new fact. This module therefore removes only strongly overlapping updates when
the older item contributes no new material fact or named entity.

The newest wording wins. Canonical publication/update timestamps are otherwise
left untouched; this is a presentation-quality normalisation, not a freshness
renewal mechanism.
"""
from __future__ import annotations

import argparse
from difflib import SequenceMatcher
import json
import re
from pathlib import Path
from typing import Any

_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’-]{2,}")
_NUMBER_RE = re.compile(r"\b\d+(?::\d+)?\b")
_ENTITY_RE = re.compile(r"\b(?:[A-Z][a-z]+(?:[-’'][A-Z]?[a-z]+)?)(?:\s+[A-Z][a-z]+(?:[-’'][A-Z]?[a-z]+)?)*\b")
_MATERIAL_RE = re.compile(
    r"\b(?:named|identified|victim|tribute|arrested|charged|bailed|released|"
    r"remanded|custody|found|located|reopened|closed|closure|cancelled|"
    r"canceled|delayed|suspended|resumed|restored|repaired|evacuated|"
    r"warning|alert|collision|crash|fire|flood|diversion|replacement|"
    r"service|works|sentenced|convicted|appeal|missing)\b",
    re.I,
)
_STATE_RE = re.compile(
    r"\b(?:no\s+trams?|out\s+of\s+service|until\s+further\s+notice|"
    r"road\s+closed|road\s+reopened|services?\s+resumed|services?\s+suspended)\b",
    re.I,
)
_STOPWORDS = {
    "about", "after", "again", "also", "been", "being", "before", "between",
    "could", "during", "from", "have", "into", "more", "most", "over",
    "rochdale", "said", "should", "some", "such", "than", "that", "their",
    "there", "these", "they", "this", "through", "under", "until", "with",
    "would", "your", "will", "were", "was", "are", "the", "and", "for",
    "but", "not", "our", "its", "you", "via", "now",
}
_ENTITY_STOPWORDS = {
    "A", "An", "The", "Police", "Council", "Passengers", "Customers", "Track",
    "Tram", "Trams", "Planned", "Further", "During", "Additionally", "Essential",
}


def _normalise(text: Any) -> str:
    return re.sub(r"\W+", " ", str(text or "").casefold()).strip()


def _stem_token(token: str) -> str:
    """Very light inflection normalisation for paraphrase comparison only."""
    if len(token) > 5 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith("s") and not token.endswith(("ss", "us")):
        return token[:-1]
    return token


def _words(text: Any) -> set[str]:
    return {
        _stem_token(match.group(0).casefold())
        for match in _WORD_RE.finditer(str(text or ""))
        if match.group(0).casefold() not in _STOPWORDS
    }


def _facts(text: Any) -> set[str]:
    value = str(text or "")
    facts = {match.group(0).casefold() for match in _MATERIAL_RE.finditer(value)}
    facts.update(match.group(0).casefold() for match in _STATE_RE.finditer(value))
    facts.update(_NUMBER_RE.findall(value))
    return facts


def _entities(text: Any) -> set[str]:
    entities: set[str] = set()
    for match in _ENTITY_RE.finditer(str(text or "")):
        raw = match.group(0).strip()
        if raw in _ENTITY_STOPWORDS:
            continue
        entities.add(raw.casefold())
    return entities


def _overlap(older_text: str, newer_text: str) -> tuple[float, float, float]:
    older_words = _words(older_text)
    newer_words = _words(newer_text)
    if not older_words or not newer_words:
        return 0.0, 0.0, 0.0
    intersection = len(older_words & newer_words)
    coverage = intersection / len(older_words)
    union = len(older_words | newer_words)
    jaccard = intersection / union if union else 0.0
    sequence = SequenceMatcher(None, _normalise(older_text), _normalise(newer_text)).ratio()
    return coverage, jaccard, sequence


def _strongly_overlapping(older_text: str, newer_text: str) -> bool:
    coverage, jaccard, sequence = _overlap(older_text, newer_text)
    return bool(
        sequence >= 0.80
        or coverage >= 0.82
        or jaccard >= 0.72
        or (sequence >= 0.68 and coverage >= 0.70)
        or (jaccard >= 0.58 and coverage >= 0.65)
    )


def redundant_update(older_text: str, newer_text: str) -> bool:
    """Return True only when the older wording adds no material information."""
    older = _normalise(older_text)
    newer = _normalise(newer_text)
    if not older or not newer:
        return False
    if older == newer:
        return True

    # Never remove an older timeline item if it carries a material keyword,
    # number, operational-state phrase or named entity that the newer wording
    # no longer contains. This protects real developments such as a newly named
    # person, changed time, route, location or count.
    if _facts(older_text) - _facts(newer_text):
        return False
    if _entities(older_text) - _entities(newer_text):
        return False
    return _strongly_overlapping(older_text, newer_text)


def _redundant_against_retained(older_text: str, newer_rows: list[dict[str, str]]) -> bool:
    """Compare an older update against the retained newer timeline as a whole.

    A fact may be split across two successive paraphrases (for example one
    mentions the date range while another mentions Exchange Square). Pairwise
    comparison alone then keeps every paraphrase forever. We may remove the
    older row only when all of its facts/entities are already represented in
    the newer retained set *and* it strongly overlaps at least one newer row.
    """
    if not newer_rows:
        return False
    newer_facts: set[str] = set()
    newer_entities: set[str] = set()
    for row in newer_rows:
        newer_facts.update(_facts(row["text"]))
        newer_entities.update(_entities(row["text"]))
    if _facts(older_text) - newer_facts:
        return False
    if _entities(older_text) - newer_entities:
        return False
    return any(_strongly_overlapping(older_text, row["text"]) for row in newer_rows)


def compact_updates(rows: Any, limit: int = 30) -> list[dict[str, str]]:
    """Keep the newest useful wording and drop only redundant older updates."""
    cleaned: list[dict[str, str]] = []
    if not isinstance(rows, list):
        return cleaned

    valid: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        timestamp = str(row.get("timestamp") or "").strip()
        text = re.sub(r"\s+", " ", str(row.get("text") or "")).strip()
        if timestamp and text:
            valid.append({"timestamp": timestamp, "text": text})
    valid.sort(key=lambda row: row["timestamp"], reverse=True)

    for row in valid:
        if any(redundant_update(row["text"], newer["text"]) for newer in cleaned):
            continue
        if _redundant_against_retained(row["text"], cleaned):
            continue
        cleaned.append(row)
        if len(cleaned) >= limit:
            break
    return cleaned


def compact_articles(articles: Any) -> tuple[Any, int, int]:
    if not isinstance(articles, list):
        return articles, 0, 0

    changed_articles = 0
    removed_updates = 0
    for article in articles:
        if not isinstance(article, dict) or not isinstance(article.get("live_updates"), list):
            continue
        original = article["live_updates"]
        compacted = compact_updates(original)
        if compacted == original:
            continue
        article["live_updates"] = compacted
        article["update_count"] = len(compacted)
        changed_articles += 1
        removed_updates += max(0, len(original) - len(compacted))
    return articles, changed_articles, removed_updates


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--articles", default="articles.json")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    path = Path(args.articles)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Could not read {path}: {exc}")

    payload, changed_articles, removed_updates = compact_articles(payload)
    if args.check:
        if changed_articles:
            raise SystemExit(
                f"LIVE timeline compaction required: {changed_articles} article(s), "
                f"{removed_updates} redundant update(s)"
            )
        print("LIVE timelines are compact.")
        return 0

    if changed_articles:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"LIVE timeline compaction: {changed_articles} article(s) changed; "
        f"{removed_updates} redundant update(s) removed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
