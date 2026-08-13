"""Fail closed when third-party news publisher names leak into article copy.

Rochdale Daily may retain publishers in source_name/source_names/source_url/source_urls,
but scraped article headlines, standfirsts and bodies must read as original Rochdale
Daily copy. A story that still says e.g. "Yahoo News UK", "Manchester Evening News"
or "According to BBC News" has not completed the rewrite cleanly and is removed from
the publishable feed rather than being allowed onto the site.

Editor-written/manual records are exempt because they are editorially locked and may
legitimately discuss a media organisation as the subject of a story.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ARTICLES = Path("articles.json")

NEWS_PUBLISHERS = (
    "Yahoo News UK",
    "Yahoo News",
    "Manchester Evening News",
    "MEN",
    "BBC News",
    "BBC Manchester",
    "The Independent",
    "Roch Valley Radio",
    "About Manchester",
    "Rochdale Online",
    "Rochdale Times",
    "Rochdale Observer",
)

# MEN is too short to test as an unrestricted substring; require word boundaries.
PATTERN = re.compile(
    r"\b(?:"
    + "|".join(sorted((re.escape(name) for name in NEWS_PUBLISHERS), key=len, reverse=True))
    + r")\b",
    re.IGNORECASE,
)


def public_copy(article: dict[str, Any]) -> str:
    return "\n".join(
        str(article.get(field) or "")
        for field in ("title", "excerpt", "summary", "content_html")
    )


def is_editorial(article: dict[str, Any]) -> bool:
    return bool(article.get("editorial_lock") or article.get("manual_article")) or str(
        article.get("publication_route") or ""
    ).lower() == "editorial"


def main() -> int:
    try:
        payload = json.loads(ARTICLES.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"publisher_leak_gate: cannot read articles.json: {exc}")

    if not isinstance(payload, list):
        raise SystemExit("publisher_leak_gate: articles.json is not a list")

    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    for article in payload:
        if not isinstance(article, dict):
            continue
        if is_editorial(article):
            kept.append(article)
            continue
        match = PATTERN.search(public_copy(article))
        if match:
            rejected.append({
                "slug": str(article.get("slug") or ""),
                "title": str(article.get("title") or ""),
                "publisher": match.group(0),
            })
            continue
        kept.append(article)

    if rejected:
        ARTICLES.write_text(
            json.dumps(kept, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        for item in rejected:
            print(
                "publisher_leak_gate: rejected "
                f"{item['slug']} ({item['publisher']}) — rewrite required"
            )

    print(
        f"publisher_leak_gate: {len(kept)} kept, {len(rejected)} rejected; "
        "publisher names remain permitted in source metadata only"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
