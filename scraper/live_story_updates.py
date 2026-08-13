"""Keep developing crime coverage on one article URL with timestamped updates."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import story_identity

_ORIGINAL = story_identity.merge_article_records
_INSTALLED = False
_AUTHORITATIVE_DOMAINS = {
    "gmp.police.uk",
    "rochdale.gov.uk",
    "manchesterfire.gov.uk",
    "greatermanchester-ca.gov.uk",
    "gmca.gov.uk",
    "tfgm.com",
    "news.tfgm.com",
    "nationalhighways.co.uk",
    "northerncarealliance.nhs.uk",
    "penninecare.nhs.uk",
}


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
    merged["breaking_news"] = True
    merged["breaking_label"] = "BREAKING NEWS"
    merged["is_ongoing"] = True
    merged["ongoing_label"] = "LIVE"
    merged["live_updates"] = updates[:30]
    merged["update_count"] = max(int(merged.get("update_count") or 1), len(updates))
    if updates:
        merged["last_updated_at"] = updates[0]["timestamp"]
    return merged


def _authoritative_url(value: str) -> bool:
    host = (urlparse(str(value or "")).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return any(host == domain or host.endswith("." + domain) for domain in _AUTHORITATIVE_DOMAINS)


def _live_source_candidates(core) -> list[Any]:
    """Explicitly re-fetch each active authoritative LIVE source every scraper run."""
    try:
        if not core.OUTPUT_FILE.exists():
            return []
        articles = json.loads(core.OUTPUT_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        core.log.warning("LIVE source refresh could not read articles.json: %s", exc)
        return []

    candidates = []
    seen_urls = set()
    for article in articles:
        if not isinstance(article, dict):
            continue
        if not (article.get("live_story") or article.get("is_ongoing")):
            continue
        source_url = str(article.get("source_url") or "").strip()
        if not source_url or source_url in seen_urls or not _authoritative_url(source_url):
            continue
        seen_urls.add(source_url)

        try:
            meta = core.page_metadata(source_url)
        except Exception as exc:
            core.log.info("LIVE source refresh failed for %s: %s", source_url, exc)
            continue

        title = core.normalise_ws(str(meta.get("title") or article.get("title") or ""))
        description = core.normalise_ws(str(meta.get("description") or ""))
        body_excerpt = core.normalise_ws(str(meta.get("body_excerpt") or ""))
        if not title or len(description + body_excerpt) < 40:
            continue

        candidates.append(
            core.Candidate(
                source_name=str(article.get("source_name") or "Official source"),
                source_url=str(meta.get("url") or source_url),
                source_title=title,
                source_summary=description or body_excerpt[:900],
                source_published_at=core.iso_utc(core.utc_now()),
                area=str(article.get("area") or "rochdale"),
                category=str(article.get("category") or "crime"),
                image_candidate_url=str(meta.get("image") or ""),
                source_body_excerpt=body_excerpt,
                source_kind="live_refresh",
            )
        )
        core.log.info("LIVE source explicitly re-fetched: %s", source_url)
    return candidates


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    story_identity.merge_article_records = _merge

    import scraper as core
    from render_live_updates import main as render_live_updates

    # Discovery indexes do not always surface an edited press release again.
    # Always revisit the source URL already attached to each active LIVE story.
    original_collect_discovery = core.collect_discovery_candidates

    def collect_discovery_with_live_refresh():
        candidates = list(original_collect_discovery())
        existing_urls = {str(getattr(item, "source_url", "") or "") for item in candidates}
        for item in _live_source_candidates(core):
            if str(getattr(item, "source_url", "") or "") not in existing_urls:
                candidates.append(item)
        return candidates

    core.collect_discovery_candidates = collect_discovery_with_live_refresh

    # The renderer runs after the scraper has written articles.json, so fresh
    # crime reports receive LIVE labels and matched reports get a visible
    # timestamped timeline before page generation starts.
    original_main = core.main

    def main_with_live_updates():
        result = original_main()
        if result == 0:
            render_live_updates()
        return result

    core.main = main_with_live_updates
    _INSTALLED = True
