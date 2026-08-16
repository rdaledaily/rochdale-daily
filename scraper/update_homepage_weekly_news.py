#!/usr/bin/env python3
"""Add a secondary, clearly labelled weekly archive discovery section.

The live Latest feed remains strict and is never padded with older material. The
weekly section is deliberately separate so a quiet current-news cycle does not
leave readers or crawlers with an unnecessarily shallow homepage. Older stories
are never represented as current or breaking news.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from enforce_frontpage_freshness import is_recent_live_update
from update_homepage_static_latest import (
    ARTICLES,
    INDEX,
    card,
    clean,
    is_expired_time_sensitive_preview,
    is_expired_today_deadline,
    is_utility_not_news,
    parse_dt,
)

ROOT = Path(__file__).resolve().parents[1]
FRONTPAGE = ROOT / "articles/frontpage.json"
START = "<!-- WEEKLY_LOCAL_NEWS_START -->"
END = "<!-- WEEKLY_LOCAL_NEWS_END -->"
MAX_STORIES = 6
MAX_AGE_DAYS = 7
CURRENT_EDITION_HOURS = 14
MIN_CURRENT_EDITION_FOR_WEEKLY = 6
INSERT_BEFORE = '      <section class="section" id="news-by-ward" aria-labelledby="news-by-ward-title">'


def frontpage_rows(path: Path = FRONTPAGE) -> list[dict]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = payload.get("articles", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def frontpage_slugs(path: Path = FRONTPAGE) -> set[str]:
    return {
        clean(row.get("slug"))
        for row in frontpage_rows(path)
        if clean(row.get("slug"))
    }


def current_edition_story_count(rows: list[dict], now: datetime | None = None) -> int:
    """Count genuinely current rows, not merely whatever happens to be in frontpage.json."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=CURRENT_EDITION_HOURS)
    count = 0
    for row in rows:
        published = parse_dt(row.get("first_published_at") or row.get("published_at"))
        if published >= cutoff:
            count += 1
            continue
        if is_recent_live_update(row, cutoff):
            count += 1
    return count


def current_edition_healthy(rows: list[dict], now: datetime | None = None) -> bool:
    """Retained as a newsroom-health signal; it no longer hides archive discovery."""
    return current_edition_story_count(rows, now) >= MIN_CURRENT_EDITION_FOR_WEEKLY


def weekly_eligible(row: object, now: datetime) -> bool:
    if not isinstance(row, dict):
        return False
    if str(row.get("status") or "published").lower() != "published":
        return False
    if row.get("requires_approval") is True:
        return False
    if not clean(row.get("slug")) or not clean(row.get("title")):
        return False
    if clean(row.get("category")).lower() in {"event", "events", "what's on", "whats-on"}:
        return False
    if is_utility_not_news(row):
        return False
    if is_expired_today_deadline(row, now):
        return False
    if is_expired_time_sensitive_preview(row, now):
        return False
    published = parse_dt(row.get("first_published_at") or row.get("published_at"))
    return published.year > 1970 and published <= now


def choose_weekly(rows: list[object], current_slugs: set[str], now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    floor = now - timedelta(days=MAX_AGE_DAYS)
    candidates: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        if not weekly_eligible(row, now):
            continue
        slug = clean(row.get("slug"))
        if not slug or slug in current_slugs or slug in seen:
            continue
        published = parse_dt(row.get("first_published_at") or row.get("published_at"))
        if published < floor or published > now:
            continue
        seen.add(slug)
        candidates.append(row)

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
        '            <h2 class="section-title" id="more-local-news-title">More local news from the past 7 days</h2>\n'
        '            <a class="section-link" href="/archive.html">Browse the archive</a>\n'
        '          </div>\n'
        '          <p style="margin:0 0 14px;color:var(--muted);font-size:15px">Further local reporting from the past week. Latest news above remains limited to verified current stories from the last 14 hours.</p>\n'
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

    now = datetime.now(timezone.utc)
    current_rows = frontpage_rows()
    current_count = current_edition_story_count(current_rows, now)
    chosen = choose_weekly(payload, {clean(row.get('slug')) for row in current_rows}, now=now)

    if current_count < MIN_CURRENT_EDITION_FOR_WEEKLY:
        print(
            f"Current edition has only {current_count} genuinely current stories; "
            "keeping the clearly labelled weekly archive section visible for honest homepage depth."
        )

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
