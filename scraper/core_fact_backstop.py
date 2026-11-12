"""Core-fact backstop: no automated story stays published on facts its sources do not give.

Written 12 Nov 2026. Rewrites may change wording; they may not change the core
facts -- who, what legal status, which offence or harm, when, where, how many,
and what anyone said. The rewrite gate (source_fidelity via quality_issues)
enforces that on the text the writer was given. This backstop covers the two
ways a wrong story still reached readers:

  1. Stories published before the gate existed.
  2. Sources that change after publication. On 11 Nov Roch Valley Radio
     corrected an arrested man's age from "in his 50s" to 39; Rochdale Daily
     kept the old age.

Each run (from article_gate.main, which every publishing lane already calls):

  capture()  fetches every source of each automated story that has not been
             checked yet, and re-fetches sources of stories under 72 hours old
             so a corrected source is noticed. Bounded per run.
  check()    compares the story with the union of its captured sources and
             records the verdict on the record as core_fact_check.

A story whose verdict is "failed" is dropped by article_gate and its page is
deleted (see article_gate.main). A story is only failed when EVERY source was
captured and the capture is the story itself; anything less is recorded as
"unchecked" with the reason, and reported, never guessed at.
"""
from __future__ import annotations

import hashlib
import ipaddress
import os
import re
import socket
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

from source_fidelity import fidelity_issues

RECHECK_HOURS = 72
RECAPTURE_MINUTES = 30
MAX_BYTES = 1_500_000
UNFETCHABLE_HOSTS = {"news.google.com"}  # wrappers: resolved to the publisher before fetching
# Deterministic records are rendered from a published data record, not
# rewritten, and are guarded where they are generated (food_hygiene.py).
SKIP_SOURCE_KINDS = {"food_hygiene_roundup"}
SKIP_ROUTES = {"daily-briefing", "editorial", "deterministic"}

_STOP = {
    "with", "from", "that", "this", "have", "been", "after", "over", "into",
    "rochdale", "their", "about", "will", "were", "they", "what", "when",
    "where", "which", "while", "says", "said", "news", "daily",
}


def _parse(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def is_automated(row: dict[str, Any]) -> bool:
    if not isinstance(row, dict):
        return False
    if row.get("manual_article") or row.get("sponsored") or row.get("editorial_lock"):
        return False
    if str(row.get("source_kind") or "") in SKIP_SOURCE_KINDS:
        return False
    if str(row.get("publication_route") or "") in SKIP_ROUTES:
        return False
    return True


def source_urls(row: dict[str, Any]) -> list[str]:
    urls = [u for u in (row.get("source_urls") or []) if isinstance(u, str) and u]
    if not urls and row.get("source_url"):
        urls = [str(row["source_url"])]
    seen: list[str] = []
    for url in urls:
        if url not in seen:
            seen.append(url)
    return seen


def _public_https(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("not a plain public https URL")
    host = parsed.hostname or ""
    if host in UNFETCHABLE_HOSTS:
        raise ValueError("aggregator link, not an article")
    for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise ValueError("non-public address")


def fetch_text(url: str) -> str:
    """Fetch a source page as plain text. Raises on anything unexpected."""
    import requests
    from bs4 import BeautifulSoup

    current = url
    if (urlparse(url).hostname or "") in UNFETCHABLE_HOSTS:
        # The pipeline's own resolver turns a Google News wrapper into the
        # publisher's URL; without it 80 live stories could not be checked.
        from resolve_google_news_sources import resolve_google_news_url
        resolved = resolve_google_news_url(url, timeout=10)
        if not resolved:
            raise ValueError("Google News link did not resolve to a publisher page")
        current = resolved
    for _ in range(4):
        _public_https(current)
        response = requests.get(
            current, timeout=(5, 10), allow_redirects=False,
            headers={"User-Agent": "RochdaleDailyFactCheck/1.0 (+https://rochdaledaily.co.uk/editorial-standards.html)",
                     "Accept": "text/html"},
        )
        if 300 <= response.status_code < 400 and response.headers.get("Location"):
            current = urljoin(current, response.headers["Location"])
            continue
        response.raise_for_status()
        if "html" not in response.headers.get("Content-Type", "").lower():
            raise ValueError("not an HTML page")
        if len(response.content) > MAX_BYTES:
            raise ValueError("page too large")
        soup = BeautifulSoup(response.content, "html.parser")
        for node in soup(["script", "style", "noscript", "svg"]):
            node.decompose()
        return " ".join(soup.stripped_strings)[:40000]
    raise ValueError("too many redirects")


def _known_text(row: dict[str, Any]) -> dict[str, str]:
    """Source text already captured on the record by earlier evidence runs."""
    known: dict[str, str] = {}
    for item in row.get("evidence_sources") or []:
        if isinstance(item, dict) and item.get("url") and item.get("captured_text"):
            known[str(item["url"])] = str(item["captured_text"])
    return known


def needs_capture(row: dict[str, Any], now: datetime) -> bool:
    verdict = row.get("core_fact_check") or {}
    first = _parse(row.get("first_published_at") or row.get("published_at"))
    young = first is not None and now - first < timedelta(hours=RECHECK_HOURS)
    if not verdict:
        return True
    # A capture that failed for a passing reason (timeout, rate limit) is
    # retried on later runs; aggregator links never become fetchable.
    if (
        verdict.get("status") == "unchecked"
        and int(verdict.get("attempts") or 1) < 3
        and "capture failed" in str(verdict.get("reason") or "")
    ):
        return True
    if young:
        last = _parse(verdict.get("checked_at"))
        return last is None or now - last >= timedelta(minutes=RECAPTURE_MINUTES)
    return False


def _relevant(text: str, title: str) -> bool:
    """True when the capture is the story, not a cookie wall or an index page."""
    words = {w for w in re.findall(r"[a-z0-9]+", title.lower()) if len(w) >= 4 and w not in _STOP}
    if not words:
        return True
    lowered = text.lower()
    return sum(1 for w in words if w in lowered) / len(words) >= 0.4


def draft_text(row: dict[str, Any]) -> str:
    # Joined as separate sentences, so the standfirst's first word is not
    # read as a capitalised name in the middle of the headline.
    parts = [str(row.get(k) or "").strip() for k in ("title", "excerpt")]
    return ". ".join(p.rstrip(".") for p in parts if p) + ". " + str(row.get("content_html") or "")


def check(row: dict[str, Any], texts: dict[str, str], errors: dict[str, str]) -> dict[str, Any]:
    urls = source_urls(row)
    title = str(row.get("title") or "")
    missing = [u for u in urls if not texts.get(u)]
    off_topic = [u for u in urls if texts.get(u) and not _relevant(texts[u], title)]
    combined = " ".join(texts[u] for u in urls if texts.get(u) and u not in off_topic)
    published = _parse(row.get("first_published_at") or row.get("published_at"))
    published_on: date | None = published.date() if published else None
    issues = fidelity_issues(draft_text(row), combined, published_on) if combined else []

    if not urls:
        status, reason = "unchecked", "story records no source URL"
    elif missing or off_topic:
        # Partial evidence can neither convict nor clear a story.
        status = "unchecked"
        reasons = [f"{u}: {errors.get(u, 'not captured')}" for u in missing]
        reasons += [f"{u}: capture is not the story" for u in off_topic]
        reason = "; ".join(reasons)[:600]
    elif issues:
        status, reason = "failed", ""
    else:
        status, reason = "passed", ""
    return {
        "status": status,
        "issues": issues if status == "failed" else [],
        "reason": reason,
        "source_sha": {u: hashlib.sha256(texts[u].encode("utf-8")).hexdigest()[:16] for u in urls if texts.get(u)},
    }


def run(
    rows: list[dict[str, Any]],
    now: datetime | None = None,
    fetcher: Callable[[str], str] = fetch_text,
    limit: int | None = None,
) -> dict[str, int]:
    """Capture and check; writes core_fact_check onto each record in place."""
    now = now or datetime.now(timezone.utc)
    budget = limit if limit is not None else int(os.getenv("RD_CORE_FACT_FETCH_LIMIT", "30"))
    counts = {"checked": 0, "passed": 0, "failed": 0, "unchecked": 0, "fetches": 0, "changed_sources": 0}
    candidates = [r for r in rows if is_automated(r) and needs_capture(r, now)]
    # Crime, police and court stories first (contempt and defamation risk),
    # then newest first: a fresh story is the one most readers see now.
    candidates.sort(key=lambda r: (
        str(r.get("category") or "") == "crime" or bool(r.get("police_matter")),
        _parse(r.get("first_published_at") or r.get("published_at")) or datetime.min.replace(tzinfo=timezone.utc),
    ), reverse=True)
    for row in candidates:
        urls = source_urls(row)
        fetchable = list(urls)
        known = _known_text(row)
        previous = (row.get("core_fact_check") or {}).get("source_sha") or {}
        first = _parse(row.get("first_published_at") or row.get("published_at"))
        young = first is not None and now - first < timedelta(hours=RECHECK_HOURS)
        to_fetch = [u for u in fetchable if young or not known.get(u)]
        if counts["fetches"] + len(to_fetch) > budget and counts["checked"]:
            break
        texts: dict[str, str] = {u: known[u] for u in urls if known.get(u)}
        errors: dict[str, str] = {}
        for url in to_fetch[:12]:
            counts["fetches"] += 1
            try:
                texts[url] = fetcher(url)
            except Exception as exc:  # noqa: BLE001 - every failure is recorded, none is fatal
                if url not in texts:
                    errors[url] = f"capture failed ({type(exc).__name__}: {str(exc)[:80]})"
        verdict = check(row, texts, errors)
        if previous and any(previous.get(u) and previous.get(u) != verdict["source_sha"].get(u) for u in urls):
            counts["changed_sources"] += 1
            verdict["source_changed_at"] = _iso(now)
        verdict["checked_at"] = _iso(now)
        verdict["attempts"] = int((row.get("core_fact_check") or {}).get("attempts") or 0) + 1
        row["core_fact_check"] = verdict
        counts["checked"] += 1
        counts[verdict["status"]] += 1
    return counts


def failed(row: dict[str, Any]) -> bool:
    return is_automated(row) and (row.get("core_fact_check") or {}).get("status") == "failed"
