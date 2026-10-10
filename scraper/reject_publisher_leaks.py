"""Keep generated reports safe without rejecting them for source attribution.

The original publisher is credited through discreet clickable links in the
article's Sources section. Publisher names appearing in an independently
rewritten report are not grounds for suppressing the entire article.

Retired copy-through publication routes and emoji/pictographs in automated
copy remain blocked. Only genuinely rejected records have their stale
generated HTML pages removed.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ARTICLES = Path("articles.json")
ARTICLE_PAGES = Path("articles")

RETIRED_ROUTES = {
    "source-led-fallback",
    "source-led-emergency-fallback",
    "automatic-attributed-crime-fallback",
    "direct-crime-autopublish",
}

EMOJI_PATTERN = re.compile(
    "["
    "\U0001F1E6-\U0001F1FF"
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FAFF"
    "\U00002600-\U000026FF"
    "\U00002700-\U000027BF"
    "]",
    re.UNICODE,
)


def public_copy(article: dict[str, Any]) -> str:
    return "\n".join(
        str(article.get(field) or "")
        for field in ("title", "excerpt", "summary", "body", "content_html")
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
        copy = public_copy(article)
        emoji_match = EMOJI_PATTERN.search(copy)
        # A journalist or outlet named in otherwise original reporting does
        # not make the report a source-copy; URL attribution belongs in the
        # existing linked Sources section, not an article rejection gate.
        if route or emoji_match:
            slug = str(article.get("slug") or "")
            if route:
                reason = f"retired route: {route}"
            else:
                reason = "emoji/pictograph in public copy"
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
        f"{deleted_pages} stale pages deleted; linked source metadata retained"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
