"""Fail closed when generated articles are not clean Rochdale Daily copy.

Publisher names belong in source metadata, not reader-facing copy. Retired
source-led fallback routes are also rejected outright: they existed before
OpenAI rewriting became mandatory and may reproduce source wording too closely.
When a record is rejected, its stale generated HTML page is deleted as well so
old copied pages cannot remain live outside articles.json.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ARTICLES = Path("articles.json")
ARTICLE_PAGES = Path("articles")

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

RETIRED_ROUTES = {
    "source-led-fallback",
    "source-led-emergency-fallback",
    "automatic-attributed-crime-fallback",
    "direct-crime-autopublish",
}

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


def retired_route(article: dict[str, Any]) -> str:
    route = str(article.get("publication_route") or "").lower()
    style = str(article.get("style_rewrite_status") or "").lower()
    if route in RETIRED_ROUTES:
        return route
    if style in RETIRED_ROUTES:
        return style
    return ""


def remove_stale_page(slug: str) -> bool:
    if not slug:
        return False
    page = ARTICLE_PAGES / f"{slug}.html"
    if not page.exists():
        return False
    page.unlink()
    return True


def main() -> int:
    try:
        payload = json.loads(ARTICLES.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"publisher_leak_gate: cannot read articles.json: {exc}")

    if not isinstance(payload, list):
        raise SystemExit("publisher_leak_gate: articles.json is not a list")

    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    deleted_pages = 0

    for article in payload:
        if not isinstance(article, dict):
            continue
        if is_editorial(article):
            kept.append(article)
            continue

        route = retired_route(article)
        match = PATTERN.search(public_copy(article))
        if route or match:
            slug = str(article.get("slug") or "")
            reason = f"retired route: {route}" if route else f"publisher leak: {match.group(0)}"
            rejected.append({
                "slug": slug,
                "title": str(article.get("title") or ""),
                "reason": reason,
            })
            if remove_stale_page(slug):
                deleted_pages += 1
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
                f"{item['slug']} ({item['reason']}) — clean rewrite required"
            )

    print(
        f"publisher_leak_gate: {len(kept)} kept, {len(rejected)} rejected, "
        f"{deleted_pages} stale pages deleted; source metadata remains intact on kept stories"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
