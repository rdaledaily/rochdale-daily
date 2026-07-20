"""Resolve Google News wrapper links to the publisher's real article URL.

Google News RSS gives a headline and a `news.google.com/rss/articles/CBMi...`
link. That link carries no article text, and plain HTTP requests to it get a
403 or a consent wall, so the pipeline was left with a headline and nothing to
write from — which is why most candidates were correctly discarded by the
editorial gate.

A real browser CAN follow that link through to the publisher. Playwright is
already a dependency (and its Chromium is already installed and cached by the
workflow), so this reuses what is there rather than adding anything new.

Design notes:
* ONE browser is launched per run and reused for every URL — launching per URL
  would dominate the cost.
* Results are cached on disk between runs, so a wrapper is only ever resolved
  once. Steady state is therefore nearly free; only genuinely new stories cost
  a navigation.
* Failures are cached too (with a shorter TTL) so a permanently unresolvable
  link is not retried every 15 minutes.
* Everything is capped and fails soft: any error returns the wrapper unchanged
  and the pipeline behaves exactly as it does today.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

CACHE_PATH = Path(os.getenv("GOOGLE_NEWS_CACHE", "google_news_resolutions.json"))
MAX_NEW_PER_RUN = int(os.getenv("GOOGLE_NEWS_RESOLVE_MAX", "60"))
NAV_TIMEOUT_MS = int(os.getenv("GOOGLE_NEWS_RESOLVE_TIMEOUT_MS", "20000"))
SETTLE_MS = int(os.getenv("GOOGLE_NEWS_RESOLVE_SETTLE_MS", "2500"))
SUCCESS_TTL_DAYS = int(os.getenv("GOOGLE_NEWS_CACHE_TTL_DAYS", "45"))
FAILURE_TTL_HOURS = int(os.getenv("GOOGLE_NEWS_FAILURE_TTL_HOURS", "12"))
ENABLED = os.getenv("GOOGLE_NEWS_BROWSER_RESOLUTION", "true").lower() not in {
    "0", "false", "no", "off",
}

_GOOGLE_HOSTS = ("google.com", "google.co.uk", "gstatic.com", "googleusercontent.com")
_CONSENT_LABELS = (
    "Reject all", "Alle ablehnen", "Decline all", "Accept all",
    "I agree", "Alles accepteren", "Nur essenzielle",
)


def is_google_wrapper(url: str) -> bool:
    host = (urlparse(str(url or "")).hostname or "").lower()
    return host.endswith("news.google.com")


def _is_google_host(url: str) -> bool:
    host = (urlparse(str(url or "")).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in _GOOGLE_HOSTS)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _cache_key(url: str) -> str:
    """Key on the wrapper's token, ignoring query noise like ?oc=5."""
    path = urlparse(str(url or "")).path
    match = re.search(r"/articles/([A-Za-z0-9_\-]+)", path)
    return match.group(1)[:120] if match else str(url or "")[:200]


def load_cache(path: Path = CACHE_PATH) -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def save_cache(cache: dict[str, dict[str, Any]], path: Path = CACHE_PATH) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)
    except OSError:
        pass


def _cached_result(entry: Any, now: datetime) -> str | None:
    """Return cached URL, '' for a still-valid failure, or None if expired."""
    if not isinstance(entry, dict):
        return None
    stamp = _parse(entry.get("at"))
    if stamp is None:
        return None
    url = str(entry.get("url") or "")
    if url:
        return url if now - stamp < timedelta(days=SUCCESS_TTL_DAYS) else None
    return "" if now - stamp < timedelta(hours=FAILURE_TTL_HOURS) else None


def _dismiss_consent(page) -> None:
    for label in _CONSENT_LABELS:
        try:
            button = page.get_by_role("button", name=re.compile(label, re.I))
            if button.count():
                button.first.click(timeout=1200)
                page.wait_for_timeout(600)
                return
        except Exception:
            continue


def _resolve_one(page, url: str) -> str:
    """Navigate the wrapper and return the publisher URL, or '' on failure."""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
    except Exception:
        return ""
    if _is_google_host(page.url):
        _dismiss_consent(page)
    # The wrapper bounces via JS; give it a moment to leave the Google host.
    deadline = SETTLE_MS
    while deadline > 0 and _is_google_host(page.url):
        try:
            page.wait_for_timeout(500)
        except Exception:
            break
        deadline -= 500
    final = str(page.url or "")
    if not final or _is_google_host(final):
        # Last resort: some wrappers expose the target in a canonical/meta tag.
        for selector, attribute in (
            ("link[rel='canonical']", "href"),
            ("meta[property='og:url']", "content"),
        ):
            try:
                node = page.query_selector(selector)
                if node:
                    candidate = str(node.get_attribute(attribute) or "")
                    if candidate and not _is_google_host(candidate):
                        return candidate
            except Exception:
                continue
        return ""
    return final


def resolve_wrappers(
    urls: Iterable[str],
    logger=None,
    cache_path: Path = CACHE_PATH,
    max_new: int | None = None,
    browser_factory=None,
) -> dict[str, str]:
    """Map wrapper URL -> publisher URL for as many as possible.

    Cached entries are free. At most `max_new` fresh navigations happen per run.
    Never raises: on any failure the mapping simply omits that URL.
    """
    wrappers = [u for u in dict.fromkeys(str(x) for x in urls) if is_google_wrapper(u)]
    if not wrappers:
        return {}

    now = _now()
    cache = load_cache(cache_path)
    resolved: dict[str, str] = {}
    pending: list[str] = []

    for url in wrappers:
        cached = _cached_result(cache.get(_cache_key(url)), now)
        if cached:
            resolved[url] = cached
        elif cached == "":
            continue  # known-bad, still within failure TTL
        else:
            pending.append(url)

    limit = MAX_NEW_PER_RUN if max_new is None else max_new
    pending = pending[: max(0, limit)]
    if not pending or not ENABLED:
        if logger and pending:
            logger.info("Google News browser resolution disabled; %d link(s) left unresolved.", len(pending))
        return resolved

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - dependency guard
        if logger:
            logger.warning("Playwright unavailable; Google News links left unresolved: %s", exc)
        return resolved

    succeeded = 0
    try:
        factory = browser_factory or sync_playwright
        with factory() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=["--disable-dev-shm-usage", "--no-sandbox",
                      "--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(
                locale="en-GB",
                timezone_id="Europe/London",
                viewport={"width": 1280, "height": 900},
            )
            page = context.new_page()
            page.set_default_timeout(NAV_TIMEOUT_MS)
            for url in pending:
                final = ""
                try:
                    final = _resolve_one(page, url)
                except Exception:
                    final = ""
                cache[_cache_key(url)] = {"url": final, "at": _iso(_now())}
                if final:
                    resolved[url] = final
                    succeeded += 1
            context.close()
            browser.close()
    except Exception as exc:
        if logger:
            logger.warning("Google News browser resolution stopped early: %s", exc)

    save_cache(cache, cache_path)
    if logger:
        logger.info(
            "Google News resolution: %d/%d newly resolved (%d served from cache).",
            succeeded, len(pending), len(resolved) - succeeded,
        )
    return resolved
