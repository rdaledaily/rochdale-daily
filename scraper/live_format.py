"""The live page: one URL per incident, timestamped updates newest first.

MEN's core format for crashes, fires, police cordons, court days and
matches. A reader returns to the same page, which keeps search and Facebook
sending people to one address instead of five near-identical stories.

Updates come from two places and are merged by id/timestamp:
  * the story record's own ``live_updates`` (pipeline or editor JSON), and
  * the live desk (/live-desk.html -> functions/api/live-updates.js, KV).

Rules
  * LIVE is shown only while the newest update is under six hours old, and
    only for a story an editor started from the desk or one with at least two
    real updates. A single machine-seeded line is not live coverage (on
    28 Oct 2026 a crime story showed BREAKING NEWS - LIVE with one update
    from the previous evening).
  * After that the page keeps its timeline under "As it happened".
  * LiveBlogPosting structured data carries every update, so Google can
    show the page as live coverage.

Everything rendered here is escaped; nothing from an update is trusted HTML.
"""
from __future__ import annotations

import html
import json
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

LIVE_WINDOW = timedelta(hours=6)
LONDON = ZoneInfo("Europe/London")
SITE = "https://rochdaledaily.co.uk"
TIMELINE_RE = re.compile(r'<section class="live-update-timeline".*?</section>', re.S)


def _dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _clean(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(value or ""))).strip()[:limit]


def _safe_url(value: Any) -> str:
    raw = str(value or "").strip()
    if raw.startswith("/assets/") or raw.startswith("https://"):
        return raw
    return ""


def uk_time(dt: datetime, with_date: bool = False) -> str:
    local = dt.astimezone(LONDON)
    zone = "BST" if local.utcoffset() == timedelta(hours=1) else "GMT"
    clock = local.strftime("%H:%M") + " " + zone
    return f"{clock}, {local.day} {local.strftime('%B %Y')}" if with_date else clock


def normalise_updates(rows: Iterable[Any]) -> list[dict[str, Any]]:
    """Clean, de-duplicated, newest first."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        when = _dt(row.get("timestamp"))
        text = _clean(row.get("text"), 1500)
        if not when or len(text) < 5:
            continue
        key = str(row.get("id") or "") or f"{when.isoformat()}|{text[:60]}"
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "id": str(row.get("id") or "") or "u" + when.strftime("%Y%m%d%H%M%S"),
            "timestamp": when.isoformat().replace("+00:00", "Z"),
            "when": when,
            "text": text,
            "title": _clean(row.get("title"), 140),
            "image_url": _safe_url(row.get("image_url")),
            "image_credit": _clean(row.get("image_credit"), 120),
            "source_url": _safe_url(row.get("source_url")),
        })
    out.sort(key=lambda row: row["when"], reverse=True)
    return out


def live_state(article: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    updates = normalise_updates(article.get("live_updates") or [])
    desk = bool(article.get("live_desk"))
    real = desk or len(updates) >= 2
    newest = updates[0]["when"] if updates else None
    ended = _dt(article.get("live_ended_at"))
    is_live = bool(real and newest and now - newest < LIVE_WINDOW and not ended)
    return {
        "updates": updates,
        "is_live": is_live,
        "has_timeline": bool(real and updates),
        "label": "LIVE" if is_live else ("As it happened" if real and updates else ""),
        "last_update": newest,
        "key_points": [_clean(p, 220) for p in (article.get("key_points") or []) if _clean(p, 220)][:6],
    }


def strip_baked_timeline(content_html: str) -> str:
    """Older pipeline runs baked a timeline into content_html; the page now
    renders one timeline itself."""
    return TIMELINE_RE.sub("", str(content_html or "")).strip()


def render_block(article: dict[str, Any], now: datetime | None = None) -> str:
    state = live_state(article, now)
    if not state["has_timeline"]:
        return ""
    e = html.escape
    newest = state["last_update"]
    pill = (
        '<span class="live-pill" aria-label="Live coverage">LIVE</span>'
        if state["is_live"] else '<span class="live-pill live-pill--ended">As it happened</span>'
    )
    head = (
        '<div class="live-head">' + pill +
        f'<span class="live-updated">Last updated <time datetime="{e(state["updates"][0]["timestamp"])}">'
        f'{e(uk_time(newest, with_date=True))}</time></span>'
        f'<span class="live-count">{len(state["updates"])} updates</span></div>'
    )
    points = ""
    if state["key_points"]:
        points = (
            '<div class="live-points"><h2>What we know so far</h2><ul>'
            + "".join(f"<li>{e(p)}</li>" for p in state["key_points"])
            + "</ul></div>"
        )
    rows = []
    for row in state["updates"]:
        image = ""
        if row["image_url"]:
            credit = f'<figcaption>Image: {e(row["image_credit"])}</figcaption>' if row["image_credit"] else ""
            image = (f'<figure class="live-figure"><img src="{e(row["image_url"])}" alt="" loading="lazy" '
                     f'decoding="async" referrerpolicy="no-referrer">{credit}</figure>')
        source = (f' <a class="live-source" href="{e(row["source_url"])}" target="_blank" rel="noopener">Source</a>'
                  if row["source_url"] else "")
        title = f'<h3>{e(row["title"])}</h3>' if row["title"] else ""
        rows.append(
            f'<article class="live-entry" id="update-{e(row["id"])}" data-id="{e(row["id"])}">'
            f'<a class="live-time" href="#update-{e(row["id"])}"><time datetime="{e(row["timestamp"])}">'
            f'{e(uk_time(row["when"]))}</time></a>'
            f'<div class="live-body">{title}<p>{e(row["text"])}{source}</p>{image}</div></article>'
        )
    return (
        f'<section class="live-blog" id="live" aria-label="Live updates" data-live="{"1" if state["is_live"] else "0"}">'
        + head + points
        + '<div class="live-new" hidden><button type="button">New updates</button></div>'
        + '<div class="live-timeline">' + "".join(rows) + "</div></section>"
    )


def json_ld(article: dict[str, Any], canonical_url: str, publisher: dict[str, Any], now: datetime | None = None) -> dict[str, Any] | None:
    state = live_state(article, now)
    if not state["has_timeline"]:
        return None
    updates = state["updates"]
    oldest = updates[-1]
    data: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "LiveBlogPosting",
        "@id": canonical_url + "#live",
        "headline": str(article.get("title") or "")[:110],
        "url": canonical_url,
        "coverageStartTime": oldest["timestamp"],
        "publisher": publisher,
        "liveBlogUpdate": [
            {
                "@type": "BlogPosting",
                "headline": (row["title"] or row["text"])[:110],
                "articleBody": row["text"],
                "datePublished": row["timestamp"],
                "url": f"{canonical_url}#update-{row['id']}",
            }
            for row in updates[:50]
        ],
    }
    if not state["is_live"]:
        data["coverageEndTime"] = updates[0]["timestamp"]
    return data


def fetch_desk_updates(base: str = SITE, timeout: float = 6.0) -> dict[str, dict[str, Any]]:
    """Read the live desk (KV) so the static page carries its updates too.

    Network trouble returns {} and the run carries on: the reader's page
    loads desk updates itself, so a missed fold only delays the static copy."""
    try:
        with urllib.request.urlopen(f"{base}/api/live-updates?index=1", timeout=timeout) as response:
            index = json.loads(response.read().decode("utf-8")).get("live") or []
    except Exception:
        return {}
    records: dict[str, dict[str, Any]] = {}
    for entry in index[:20]:
        slug = str(entry.get("slug") or "")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{3,180}", slug):
            continue
        try:
            with urllib.request.urlopen(f"{base}/api/live-updates?slug={slug}", timeout=timeout) as response:
                records[slug] = json.loads(response.read().decode("utf-8"))
        except Exception:
            continue
    return records


def fold_desk(article: dict[str, Any], desk: dict[str, Any] | None) -> dict[str, Any]:
    """A copy of the article with the desk's updates and key points merged in."""
    if not desk:
        return article
    merged = dict(article)
    merged["live_updates"] = list(article.get("live_updates") or []) + list(desk.get("updates") or [])
    if desk.get("key_points"):
        merged["key_points"] = desk["key_points"]
    merged["live_desk"] = True
    if desk.get("ended_at"):
        merged["live_ended_at"] = desk["ended_at"]
    return merged
