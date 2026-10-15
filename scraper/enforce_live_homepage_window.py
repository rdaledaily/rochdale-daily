#!/usr/bin/env python3
"""Final artifact-level guard for Rochdale Daily's live homepage.

This runs *after* page generation. It removes ordinary news older than the
configured live-homepage window from articles/frontpage.json and from the
breaking ticker. Archive/category/area/article pages are untouched.

Only an explicit, unexpired editor pin can extend a story's homepage life.
Edits, source merges and LIVE/ONGOING labels never reset its publication age.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

FRONTPAGE = Path(os.getenv("FRONTPAGE_JSON", "articles/frontpage.json"))
FRESH_HOURS = int(os.getenv("FRONTPAGE_FRESH_HOURS", "14"))


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def first_published(article: dict[str, Any]) -> datetime | None:
    return parse_dt(article.get("first_published_at") or article.get("published_at"))


def keep(article: dict[str, Any], now: datetime, cutoff: datetime) -> bool:
    first = first_published(article)
    if first is not None and first >= cutoff:
        return True

    until = parse_dt(article.get("frontpage_until"))
    if article.get("featured") is True and until is not None and until >= now:
        return True

    return False


def main() -> None:
    payload = json.loads(FRONTPAGE.read_text(encoding="utf-8"))
    rows = payload.get("articles")
    if not isinstance(rows, list):
        raise SystemExit("frontpage articles array missing")

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=FRESH_HOURS)
    kept = [row for row in rows if isinstance(row, dict) and keep(row, now, cutoff)]
    removed = [row for row in rows if isinstance(row, dict) and row not in kept]

    for index, article in enumerate(kept):
        article["frontpage_rank"] = index
        article["frontpage_priority"] = max(1, 1000 - index)
        article["slot"] = "lead" if index == 0 else "secondary-1" if index == 1 else "secondary-2" if index == 2 else ""

    breaking_titles = [
        str(article.get("title") or "").strip()
        for article in kept
        if article.get("breaking_news") is True and str(article.get("title") or "").strip()
    ]

    payload["articles"] = kept
    payload["count"] = len(kept)
    payload["breaking"] = "     •     BREAKING     •     ".join(breaking_titles)
    payload["final_live_window_guard"] = {
        "fresh_hours": FRESH_HOURS,
        "kept": len(kept),
        "removed": len(removed),
        "enforced_at": now.isoformat().replace("+00:00", "Z"),
    }
    FRONTPAGE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    removed_titles = [str(row.get("title") or "") for row in removed[:10]]
    print(f"Final live-homepage guard: kept {len(kept)}, removed {len(removed)} stale item(s): {removed_titles}")


if __name__ == "__main__":
    main()
