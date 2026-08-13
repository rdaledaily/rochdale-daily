"""Keep developing crime coverage on one article URL with timestamped updates."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import story_identity

_ORIGINAL = story_identity.merge_article_records
_INSTALLED = False


def _time(item: dict[str, Any]) -> str:
    for key in ("last_updated_at", "scraped_at", "source_published_at", "published_at"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(item: dict[str, Any]) -> str:
    value = str(item.get("excerpt") or item.get("summary") or "")
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()[:900]


def _updates(item: dict[str, Any]) -> list[dict[str, str]]:
    out = []
    existing = item.get("live_updates")
    if isinstance(existing, list):
        for row in existing:
            if isinstance(row, dict) and row.get("timestamp") and row.get("text"):
                out.append({"timestamp": str(row["timestamp"]), "text": str(row["text"])})
    text = _text(item)
    if text:
        out.append({"timestamp": _time(item), "text": text})
    return out


def _merge(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    merged = _ORIGINAL(left, right)
    if str(merged.get("category") or "").lower() != "crime":
        return merged

    seen = set()
    updates = []
    for row in _updates(left) + _updates(right):
        key = re.sub(r"\W+", " ", row["text"].lower()).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        updates.append(row)
    updates.sort(key=lambda row: row["timestamp"], reverse=True)

    merged["live_story"] = True
    merged["live_label"] = "LIVE"
    merged["is_ongoing"] = True
    merged["ongoing_label"] = "LIVE"
    merged["live_updates"] = updates[:30]
    merged["update_count"] = max(int(merged.get("update_count") or 1), len(updates))
    if updates:
        merged["last_updated_at"] = updates[0]["timestamp"]
    return merged


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    story_identity.merge_article_records = _merge

    # The renderer runs after the scraper has written articles.json, so fresh
    # crime reports receive LIVE labels and matched reports get a visible
    # timestamped timeline before page generation starts.
    import scraper as core
    from render_live_updates import main as render_live_updates

    original_main = core.main

    def main_with_live_updates():
        result = original_main()
        if result == 0:
            render_live_updates()
        return result

    core.main = main_with_live_updates
    _INSTALLED = True
