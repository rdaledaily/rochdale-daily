#!/usr/bin/env python3
"""Add visible, semantic publication timing to generated article pages.

Rochdale Daily already publishes machine-readable article:published_time and
NewsArticle datePublished metadata, but readers should not have to inspect page
source to know whether a story is current. This post-processor inserts a visible
<time> row immediately below the byline on every generated article page.

For automated stories, routine scraper timestamps do not count as editorial
updates. A visible "Updated" time is only shown when a live/breaking/ongoing
story has a newer timestamped live update. Manual/editorial stories may use
last_updated_at because that field is controlled by the newsdesk.

The transformation is idempotent and marker-bounded so it is safe to run at the
final deployment boundary without rewriting article copy or metadata.
"""
from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
ARTICLES_JSON = ROOT / "articles.json"
PAGES_DIR = ROOT / "articles"
LOCAL_TZ = ZoneInfo("Europe/London")
START = "<!-- ARTICLE_TIME_META_START -->"
END = "<!-- ARTICLE_TIME_META_END -->"
BYLINE_RE = re.compile(r'(<div class="article-byline">.*?</div>)', re.S)


def parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def first_published(article: dict[str, Any]) -> datetime | None:
    return parse_dt(article.get("first_published_at") or article.get("published_at"))


def meaningful_update(article: dict[str, Any], published: datetime) -> datetime | None:
    """Return only a reader-meaningful update time, never a polling timestamp."""
    editorial = bool(
        article.get("manual_article") is True
        or article.get("editorial_lock") is True
        or str(article.get("source_kind") or "").lower() == "editorial"
    )
    if editorial:
        updated = parse_dt(article.get("last_updated_at"))
        if updated is not None and updated > published:
            return updated
        return None

    active = bool(
        article.get("live_story") is True
        or article.get("breaking_news") is True
        or article.get("is_ongoing") is True
    )
    if not active:
        return None

    candidates: list[datetime] = []
    raw_updates = article.get("live_updates") or []
    if isinstance(raw_updates, list):
        for item in raw_updates:
            if not isinstance(item, dict):
                continue
            parsed = parse_dt(
                item.get("timestamp")
                or item.get("updated_at")
                or item.get("published_at")
            )
            if parsed is not None and parsed > published:
                candidates.append(parsed)
    return max(candidates) if candidates else None


def format_local(value: datetime) -> str:
    local = value.astimezone(LOCAL_TZ)
    day = local.strftime("%d").lstrip("0")
    return f"{day} {local.strftime('%B %Y at %H:%M')}"


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def metadata_markup(article: dict[str, Any]) -> str:
    published = first_published(article)
    if published is None:
        return ""
    updated = meaningful_update(article, published)
    published_text = html.escape(format_local(published))
    parts = [
        f'<time datetime="{html.escape(iso_utc(published), quote=True)}">Published {published_text}</time>'
    ]
    if updated is not None:
        updated_text = html.escape(format_local(updated))
        parts.append(
            f'<time datetime="{html.escape(iso_utc(updated), quote=True)}">Updated {updated_text}</time>'
        )
    return (
        START
        + '\n<p class="article-published-meta" '
        + 'style="margin:6px 0 14px;color:#5b5b5b;font-size:14px;line-height:1.4">'
        + '<span aria-label="Article timing">'
        + ' <span aria-hidden="true"> · </span>'.join(parts)
        + '</span></p>\n'
        + END
    )


def inject(text: str, article: dict[str, Any]) -> tuple[str, bool]:
    markup = metadata_markup(article)
    if not markup:
        return text, False

    if START in text and END in text:
        updated = re.sub(
            re.escape(START) + r".*?" + re.escape(END),
            markup,
            text,
            count=1,
            flags=re.S,
        )
        return updated, updated != text

    match = BYLINE_RE.search(text)
    if not match:
        return text, False
    updated = text[: match.end()] + "\n          " + markup + text[match.end() :]
    return updated, True


def main() -> int:
    rows = json.loads(ARTICLES_JSON.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise SystemExit("articles.json must contain a JSON array")

    eligible = [
        row for row in rows
        if isinstance(row, dict)
        and str(row.get("status") or "published").lower() == "published"
        and str(row.get("slug") or "").strip()
        and first_published(row) is not None
    ]

    touched = 0
    matched = 0
    missing_pages = 0
    for article in eligible:
        slug = str(article.get("slug") or "").strip().strip("/")
        page = PAGES_DIR / f"{slug}.html"
        if not page.is_file():
            missing_pages += 1
            continue
        matched += 1
        original = page.read_text(encoding="utf-8")
        updated, changed = inject(original, article)
        if changed:
            page.write_text(updated, encoding="utf-8")
            touched += 1

    if eligible and matched == 0:
        raise SystemExit("No generated article pages matched published articles; refusing silent metadata failure")

    print(
        f"Article timing metadata: {matched} page(s) checked, {touched} updated, "
        f"{missing_pages} published record(s) without a generated page."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
