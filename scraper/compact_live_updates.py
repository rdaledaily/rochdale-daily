#!/usr/bin/env python3
"""Compact repetitive LIVE timelines without hiding genuine developments.

Automated source rewrites can describe the same development with slightly
changed wording on successive passes.  Exact-string dedupe is not enough for a
reader-facing live timeline, but aggressive semantic dedupe risks hiding a real
new fact.  This module therefore removes only strongly overlapping updates when
the older item contributes no new material keyword or number.

The newest wording wins.  Canonical publication/update timestamps are otherwise
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
_MATERIAL_RE = re.compile(
    r"\b(?:named|identified|victim|tribute|arrested|charged|bailed|released|"
    r"remanded|custody|found|located|reopened|closed|closure|cancelled|"
    r"canceled|delayed|suspended|resumed|restored|repaired|evacuated|"
    r"warning|alert|collision|crash|fire|flood|diversion|replacement|"
    r"service|works|sentenced|convicted|appeal|missing)\b",
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


def _normalise(text: Any) -> str:
    return re.sub(r"\W+", " ", str(text or "").casefold()).strip()


def _words(text: Any) -> set[str]:
    return {
        match.group(0).casefold()
        for match in _WORD_RE.finditer(str(text or ""))
        if match.group(0).casefold() not in _STOPWORDS
    }


def _facts(text: Any) -> set[str]:
    value = str(text or "")
    facts = {match.group(0).casefold() for match in _MATERIAL_RE.finditer(value)}
    facts.update(_NUMBER_RE.findall(value))
    return facts


def redundant_update(older_text: str, newer_text: str) -> bool:
    """Return True only when the older wording adds no material information."""
    older = _normalise(older_text)
    newer = _normalise(newer_text)
    if not older or not newer:
        return False
    if older == newer:
        return True

    # Never remove an older timeline item if it carries a material keyword or
    # number that the newer wording no longer contains.  That protects genuine
    # developments such as a newly named person, changed time, route or count.
    if _facts(older_text) - _facts(newer_text):
        return False

    older_words = _words(older_text)
    newer_words = _words(newer_text)
    if not older_words or not newer_words:
        return False

    coverage = len(older_words & newer_words) / len(older_words)
    sequence = SequenceMatcher(None, older, newer).ratio()
    return bool(
        sequence >= 0.80
        or coverage >= 0.82
        or (sequence >= 0.68 and coverage >= 0.70)
    )


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
