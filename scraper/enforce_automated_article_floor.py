"""Enforce the newsroom's declared minimum length for automated news.

The core scraper historically logged a 200-word publication floor but its final
list comprehension still accepted ordinary 50-word pieces. This final gate is
run after scraping and before page/archive generation so thin automated copy
cannot become a published article simply because an earlier branch forgot the
quality threshold.

Events are handled by the dedicated event system and remain exempt. An explicit
``allow_short_article`` flag is available for a future verified emergency/live
format; ordinary scraped news does not receive that flag automatically.
"""
from __future__ import annotations

import html
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
ARTICLES_PATH = ROOT / "articles.json"
MIN_WORDS = max(100, int(os.getenv("MIN_AUTOMATED_ARTICLE_WORDS", "200")))
TAG_RE = re.compile(r"<[^>]+>")
WORD_RE = re.compile(r"\b[\w’'-]+\b", re.UNICODE)


def _public_text(article: dict) -> str:
    body = str(article.get("body") or "").strip()
    if not body:
        body = str(article.get("content_html") or "").strip()
    text = TAG_RE.sub(" ", html.unescape(body))
    return re.sub(r"\s+", " ", text).strip()


def _word_count(article: dict) -> int:
    return len(WORD_RE.findall(_public_text(article)))


def _exempt(article: dict) -> bool:
    if article.get("allow_short_article") is True:
        return True
    if str(article.get("source_kind") or "").lower() == "event":
        return True
    if str(article.get("category") or "").lower() == "events":
        return True
    return False


def main() -> int:
    try:
        payload = json.loads(ARTICLES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Could not read {ARTICLES_PATH}: {exc}")

    if not isinstance(payload, list):
        raise SystemExit("articles.json must contain a JSON array")

    kept: list[dict] = []
    removed: list[dict] = []
    for article in payload:
        if not isinstance(article, dict):
            continue
        words = _word_count(article)
        if _exempt(article) or words >= MIN_WORDS:
            kept.append(article)
            continue
        removed.append(
            {
                "title": str(article.get("title") or ""),
                "source_url": str(article.get("source_url") or ""),
                "word_count": words,
            }
        )

    if removed:
        ARTICLES_PATH.write_text(
            json.dumps(kept, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    print(
        f"Automated article floor: kept {len(kept)}, removed {len(removed)} "
        f"below {MIN_WORDS} words"
    )
    for item in removed[:20]:
        print(
            f"  removed {item['word_count']} words: {item['title']} | "
            f"{item['source_url']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
