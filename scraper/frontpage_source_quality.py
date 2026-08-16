#!/usr/bin/env python3
"""Keep weak machine-generated source material off Rochdale Daily's live front page.

This is intentionally conservative. It does not delete archive articles or override
manual/editorial judgement. It only marks specific automated records as unsuitable
for homepage prominence when the source shape is too weak to support a time-sensitive
news claim.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ARTICLES = Path("articles.json")
FRONTPAGE = Path("articles/frontpage.json")

RESULT_CLAIM_RE = re.compile(
    r"\b(?:defeats?|defeated|beats?|beat|wins?|won|loses?|lost|victory|result)\b",
    re.I,
)
EVERGREEN_TITLE_RE = re.compile(
    r"\b(?:offers?|provides?|available|guidance|support|information|advice)\b",
    re.I,
)
CURRENT_CHANGE_RE = re.compile(
    r"\b(?:today|tonight|this (?:morning|afternoon|evening|week)|closed|closure|"
    r"reopens?|reopened|disruption|cancelled|canceled|delay|outage|incident|warning|"
    r"alert|launched|announced|changed|changes|updated|starts?|ends?|until|from \d)\b",
    re.I,
)
SOCIAL_HOSTS = {
    "facebook.com", "www.facebook.com", "instagram.com", "www.instagram.com",
    "x.com", "www.x.com", "twitter.com", "www.twitter.com", "tiktok.com", "www.tiktok.com",
}


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _editorial(article: dict[str, Any]) -> bool:
    return bool(
        article.get("manual_article") is True
        or article.get("editorial_lock") is True
        or str(article.get("source_kind") or "").lower() == "editorial"
    )


def _urls(article: dict[str, Any]) -> list[str]:
    values = [article.get("source_url")]
    raw = article.get("source_urls")
    if isinstance(raw, list):
        values.extend(raw)
    return [str(value).strip() for value in values if str(value or "").strip()]


def _hosts(article: dict[str, Any]) -> set[str]:
    hosts: set[str] = set()
    for url in _urls(article):
        try:
            hosts.add(urlparse(url).netloc.lower())
        except ValueError:
            pass
    name = str(article.get("source_name") or "").strip().lower()
    if "." in name and " " not in name:
        hosts.add(name)
    return hosts


def weak_single_source_sports_result(article: dict[str, Any]) -> bool:
    """Require stronger grounding for automated match-result claims.

    Social snippets and unresolved Google News wrappers are useful discovery leads,
    but one such source should not be enough for the live homepage to declare a result.
    """
    if _editorial(article):
        return False
    if str(article.get("category") or "").lower() not in {"sport", "sports"}:
        return False
    text = " ".join(str(article.get(key) or "") for key in ("title", "excerpt", "summary"))
    if not RESULT_CLAIM_RE.search(text):
        return False
    if int(article.get("source_count") or 1) >= 2:
        return False
    hosts = _hosts(article)
    has_social = bool(hosts & SOCIAL_HOSTS)
    has_google_wrapper = any("news.google.com" in host for host in hosts)
    source_name = str(article.get("source_name") or "").lower()
    named_social = any(token in source_name for token in ("instagram", "facebook", "twitter", "tiktok", "x.com"))
    return has_social or has_google_wrapper or named_social


def evergreen_live_refresh(article: dict[str, Any]) -> bool:
    """Keep static service/reference pages from masquerading as newly published news."""
    if _editorial(article):
        return False
    if str(article.get("source_kind") or "").lower() != "live_refresh":
        return False
    urls = _urls(article)
    if not urls:
        return False
    council_reference = False
    for url in urls:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        path = parsed.path.lower()
        if host.endswith("rochdale.gov.uk") and "/news/" not in path and "/events/" not in path:
            council_reference = True
            break
    if not council_reference:
        return False
    text = " ".join(str(article.get(key) or "") for key in ("title", "excerpt", "summary"))
    return bool(EVERGREEN_TITLE_RE.search(text) and not CURRENT_CHANGE_RE.search(text))


def exclusion_reason(article: dict[str, Any]) -> str:
    if weak_single_source_sports_result(article):
        return "single-source social/aggregator sports-result claim requires stronger verification"
    if evergreen_live_refresh(article):
        return "evergreen council service/reference page is not a current-news development"
    return ""


def _identity(article: dict[str, Any]) -> str:
    return str(article.get("id") or article.get("slug") or article.get("story_key") or "")


def apply(articles: list[Any], frontpage: dict[str, Any]) -> tuple[int, int]:
    excluded_ids: set[str] = set()
    marked = 0
    for raw in articles:
        if not isinstance(raw, dict):
            continue
        reason = exclusion_reason(raw)
        if not reason:
            continue
        raw["exclude_from_frontpage"] = True
        raw["frontpage_source_quality_reason"] = reason
        ident = _identity(raw)
        if ident:
            excluded_ids.add(ident)
        marked += 1

    current = frontpage.get("articles") if isinstance(frontpage, dict) else None
    removed = 0
    if isinstance(current, list):
        kept = []
        for raw in current:
            if isinstance(raw, dict) and (exclusion_reason(raw) or _identity(raw) in excluded_ids):
                removed += 1
                continue
            kept.append(raw)
        frontpage["articles"] = kept
        frontpage["count"] = len(kept)
        for index, raw in enumerate(kept):
            if isinstance(raw, dict):
                raw["frontpage_rank"] = index
                raw["frontpage_priority"] = max(1, 1000 - index)
                raw["slot"] = "lead" if index == 0 else "secondary-1" if index == 1 else "secondary-2" if index == 2 else ""
        quality = frontpage.setdefault("source_quality_guard", {})
        if isinstance(quality, dict):
            quality["marked_archive_records"] = marked
            quality["removed_frontpage_records"] = removed
    return marked, removed


def main() -> None:
    articles = _read(ARTICLES, [])
    frontpage = _read(FRONTPAGE, {})
    if not isinstance(articles, list):
        raise SystemExit("articles.json must contain a JSON array")
    if not isinstance(frontpage, dict):
        raise SystemExit("articles/frontpage.json must contain a JSON object")
    marked, removed = apply(articles, frontpage)
    _write(ARTICLES, articles)
    _write(FRONTPAGE, frontpage)
    print(f"Frontpage source-quality guard: marked {marked} archive record(s); removed {removed} frontpage record(s).")


if __name__ == "__main__":
    main()
