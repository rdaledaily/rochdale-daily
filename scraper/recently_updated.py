"""Homepage "Recently updated" links: send crawlers to stories that really changed.

Editor's instruction (12 Nov 2026): when an old article is updated, link to it
from a high-traffic page so Googlebot finds the new version quickly. The
homepage is the most-crawled page on the site, so corrected and genuinely
updated stories are listed there for 14 days.

"Updated" means generate_pages.last_modified_at: a correction, a newsdesk edit,
a timestamped live update, or a real change to the text. A routine re-scrape
never puts a story here (that rule, and why, is documented on last_modified_at).

Called from update_homepage_weekly_news.main(), which every publishing lane
already runs, so no workflow needs to change.
"""
from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

START = "<!-- RECENTLY_UPDATED_START -->"
END = "<!-- RECENTLY_UPDATED_END -->"
WINDOW_DAYS = 14
MIN_GAP = timedelta(hours=1)  # an edit minutes after publishing is not an update
MAX_LINKS = 8
INSERT_AFTER = "<!-- WEEKLY_LOCAL_NEWS_END -->"
INSERT_BEFORE = '      <template id="ward-options">'


def _parse(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _page_exists(root: Path, slug: str) -> bool:
    return (root / "articles" / f"{slug}.html").is_file() or (root / "articles" / slug / "index.html").is_file()


def choose(rows: list[Any], now: datetime, root: Path = Path(".")) -> list[dict[str, Any]]:
    from generate_pages import first_published_at, last_modified_at

    chosen: list[tuple[datetime, dict[str, Any]]] = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("slug") or not row.get("title"):
            continue
        if str(row.get("status") or "published").lower() != "published" or row.get("requires_approval") is True:
            continue
        if row.get("briefing_slot") or str(row.get("id") or "").startswith("briefing-"):
            continue
        published = _parse(first_published_at(row))
        modified = _parse(last_modified_at(row))
        if not published or not modified:
            continue
        if modified - published < MIN_GAP or modified > now or now - modified > timedelta(days=WINDOW_DAYS):
            continue
        if not _page_exists(root, str(row["slug"])):
            continue
        chosen.append((modified, row))
    chosen.sort(key=lambda pair: pair[0], reverse=True)
    return [row for _, row in chosen[:MAX_LINKS]]


def _label(row: dict[str, Any]) -> str:
    from generate_pages import article_corrections, last_modified_at

    modified = str(last_modified_at(row))[:10]
    corrected = any(str(item.get("date") or "")[:10] == modified for item in article_corrections(row))
    return "Corrected" if corrected else "Updated"


def markup(rows: list[dict[str, Any]]) -> str:
    from generate_pages import last_modified_at

    items = []
    for row in rows:
        modified = _parse(last_modified_at(row))
        stamp = f"{modified.day} {modified.strftime('%b %Y')}" if modified else ""
        items.append(
            f'            <li><a href="/articles/{html.escape(str(row["slug"]), quote=True)}">{html.escape(str(row["title"]))}</a>'
            f' <span class="story-meta">{_label(row)} <time datetime="{html.escape(str(last_modified_at(row)), quote=True)}">{stamp}</time></span></li>'
        )
    return (
        f"{START}\n"
        '      <section class="section" id="recently-updated" aria-labelledby="recently-updated-title">\n'
        '        <div class="wrap">\n'
        '          <div class="section-head">\n'
        '            <h2 class="section-title" id="recently-updated-title">Recently updated</h2>\n'
        '            <a class="section-link" href="/corrections-log.html">Corrections log</a>\n'
        '          </div>\n'
        '          <ul class="recently-updated-list">\n'
        + "\n".join(items) + "\n"
        '          </ul>\n'
        '        </div>\n'
        '      </section>\n'
        f"{END}"
    )


def update_html(text: str, rows: list[dict[str, Any]]) -> tuple[str, bool]:
    if START in text and END in text:
        before, rest = text.split(START, 1)
        _, after = rest.split(END, 1)
        if not rows:
            updated = before.rstrip() + "\n\n" + after.lstrip("\n")
        else:
            updated = before + markup(rows) + after
        return updated, updated != text
    if not rows:
        return text, False
    block = markup(rows)
    if text.count(INSERT_AFTER) == 1:
        return text.replace(INSERT_AFTER, INSERT_AFTER + "\n\n" + block, 1), True
    if text.count(INSERT_BEFORE) == 1:
        return text.replace(INSERT_BEFORE, block + "\n\n" + INSERT_BEFORE, 1), True
    raise SystemExit("Homepage recently-updated anchor missing or ambiguous; refusing broad HTML rewrite")


def refresh(index: Path, rows: list[Any], now: datetime | None = None, root: Path = Path(".")) -> int:
    now = now or datetime.now(timezone.utc)
    chosen = choose(rows, now, root)
    text = index.read_text(encoding="utf-8")
    updated, changed = update_html(text, chosen)
    if changed:
        index.write_text(updated, encoding="utf-8")
    print(f"Recently updated: {len(chosen)} stories linked from the homepage.")
    return len(chosen)
