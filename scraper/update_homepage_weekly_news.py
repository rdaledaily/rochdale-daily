#!/usr/bin/env python3
"""Add a clearly separated 'More local news from this week' homepage section.

The live Latest feed intentionally remains strict: genuinely current reporting must
not be padded with older stories just to make the homepage look busy. On quieter
news cycles that can leave only a handful of cards, which reduces useful internal
linking and onward reading. This pass keeps the meanings separate by adding a
small secondary section of recent archive journalism that is *not* in the current
frontpage feed.

The section is static/crawlable, capped at six stories, limited to seven days,
and reuses the same utility/deadline/sports-preview exclusions as the crawler-
facing Latest fallback. It therefore adds discovery depth without pretending an
older article is new.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from update_homepage_static_latest import (
    ARTICLES,
    INDEX,
    card,
    clean,
    eligible,
    parse_dt,
)

ROOT = Path(__file__).resolve().parents[1]
FRONTPAGE = ROOT / "articles/frontpage.json"
START = "<!-- WEEKLY_LOCAL_NEWS_START -->"
END = "<!-- WEEKLY_LOCAL_NEWS_END -->"
MAX_STORIES = 6
MAX_AGE_DAYS = 7
INSERT_BEFORE = '      <section class="section" id="news-by-ward" aria-labelledby="news-by-ward-title">'


def frontpage_slugs(path: Path = FRONTPAGE) -> set[str]:
    if not path.is_file():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    rows = payload.get("articles", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return set()
    return {
        clean(row.get("slug"))
        for row in rows
        if isinstance(row, dict) and clean(row.get("slug"))
    }


def choose_weekly(rows: list[object], current_slugs: set[str], now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    floor = now - timedelta(days=MAX_AGE_DAYS)
    candidates: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or not eligible(row):
            continue
        slug = clean(row.get("slug"))
        if not slug or slug in current_slugs or slug in seen:
            continue
        published = parse_dt(row.get("first_published_at") or row.get("published_at"))
        if published < floor or published > now:
            continue
        seen.add(slug)
        candidates.append(row)

    # Editorial/manual journalism wins a close tie, then recency. A light
    # diversity guard stops one busy beat or township monopolising the section.
    candidates.sort(
        key=lambda row: (
            1 if row.get("manual_article") is True or clean(row.get("source_kind")).lower() == "editorial" else 0,
            parse_dt(row.get("first_published_at") or row.get("published_at")),
        ),
        reverse=True,
    )

    chosen: list[dict] = []
    area_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    deferred: list[dict] = []
    for row in candidates:
        area = clean(row.get("area") or "rochdale").lower()
        category = clean(row.get("category") or "news").lower()
        if area_counts.get(area, 0) >= 2 or category_counts.get(category, 0) >= 2:
            deferred.append(row)
            continue
        chosen.append(row)
        area_counts[area] = area_counts.get(area, 0) + 1
        category_counts[category] = category_counts.get(category, 0) + 1
        if len(chosen) >= MAX_STORIES:
            return chosen

    for row in deferred:
        chosen.append(row)
        if len(chosen) >= MAX_STORIES:
            break
    return chosen


def section_markup(rows: list[dict]) -> str:
    cards = "\n".join(card(row).replace("static-latest-card", "weekly-local-card", 1) for row in rows)
    return (
        f"{START}\n"
        '      <section class="section" id="more-local-news" aria-labelledby="more-local-news-title">\n'
        '        <div class="wrap">\n'
        '          <div class="section-head">\n'
        '            <h2 class="section-title" id="more-local-news-title">More local news from this week</h2>\n'
        '            <a class="section-link" href="/archive.html">Browse the archive</a>\n'
        '          </div>\n'
        '          <p style="margin:0 0 14px;color:var(--muted);font-size:15px">Recent Rochdale borough reporting that is still useful to read. The latest breaking and current stories remain in Latest news above.</p>\n'
        '          <div class="news-grid weekly-news-grid">\n'
        f"{cards}\n"
        '          </div>\n'
        '        </div>\n'
        '      </section>\n'
        f"{END}"
    )


def update_html(text: str, rows: list[dict]) -> tuple[str, bool]:
    if not rows:
        if START in text and END in text:
            before, rest = text.split(START, 1)
            _, after = rest.split(END, 1)
            return before.rstrip() + "\n\n" + after.lstrip("\n"), True
        return text, False

    block = section_markup(rows)
    if START in text and END in text:
        before, rest = text.split(START, 1)
        _, after = rest.split(END, 1)
        updated = before + block + after
        return updated, updated != text

    if text.count(INSERT_BEFORE) != 1:
        raise SystemExit("Homepage ward-section anchor missing or ambiguous; refusing broad HTML rewrite")
    updated = text.replace(INSERT_BEFORE, block + "\n\n" + INSERT_BEFORE, 1)
    return updated, True


def main() -> int:
    payload = json.loads(ARTICLES.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SystemExit("articles.json must contain a JSON array")
    chosen = choose_weekly(payload, frontpage_slugs())
    text = INDEX.read_text(encoding="utf-8")
    updated, changed = update_html(text, chosen)
    if changed:
        INDEX.write_text(updated, encoding="utf-8")
        print(f"Updated weekly local-news discovery section with {len(chosen)} stories.")
    else:
        print(f"Weekly local-news discovery section already current ({len(chosen)} stories).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
