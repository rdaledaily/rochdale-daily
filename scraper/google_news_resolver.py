"""Resolve Google News wrapper links to original publisher URLs.

Fast newsroom runs first attempt a tightly bounded HTTP/query/metadata recovery.
The browser-enabled deep run remains the fallback for wrappers that genuinely
need JavaScript/consent handling. Successful and failed browser resolutions are
cached across runs; lightweight failures are not cached, so the deep resolver
still gets a chance.
"""
from __future__ import annotations

import html
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urljoin, urlparse
from urllib.request import Request, build_opener

CACHE_PATH = Path(os.getenv("GOOGLE_NEWS_CACHE", "google_news_resolutions.json"))
MAX_NEW_PER_RUN = int(os.getenv("GOOGLE_NEWS_RESOLVE_MAX", "60"))
NAV_TIMEOUT_MS = int(os.getenv("GOOGLE_NEWS_RESOLVE_TIMEOUT_MS", "20000"))
SETTLE_MS = int(os.getenv("GOOGLE_NEWS_RESOLVE_SETTLE_MS", "2500"))
SUCCESS_TTL_DAYS = int(os.getenv("GOOGLE_NEWS_CACHE_TTL_DAYS", "45"))
FAILURE_TTL_HOURS = int(os.getenv("GOOGLE_NEWS_FAILURE_TTL_HOURS", "12"))
LIGHTWEIGHT_MAX = int(os.getenv("GOOGLE_NEWS_LIGHTWEIGHT_MAX", "10"))
LIGHTWEIGHT_TIMEOUT = float(os.getenv("GOOGLE_NEWS_LIGHTWEIGHT_TIMEOUT", "2.0"))
ENABLED = os.getenv("GOOGLE_NEWS_BROWSER_RESOLUTION", "true").lower() not in {
    "0", "false", "no", "off",
}

_GOOGLE_HOSTS = ("google.com", "google.co.uk", "gstatic.com", "googleusercontent.com")
_CONSENT_LABELS = (
    "Reject all", "Alle ablehnen", "Decline all", "Accept all",
    "I agree", "Alles accepteren", "Nur essenzielle",
)
_USER_AGENT = "Mozilla/5.0 (compatible; RochdaleDaily/2.0; +https://rochdaledaily.co.uk/)"


def is_google_wrapper(url: str) -> bool:
    host = (urlparse(str(url or "")).hostname or "").lower()
    return host.endswith("news.google.com")


def _is_google_host(url: str) -> bool:
    host = (urlparse(str(url or "")).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in _GOOGLE_HOSTS)


def _is_publisher_url(url: str) -> bool:
    value = str(url or "").strip()
    if not value.startswith(("https://", "http://")) or _is_google_host(value):
        return False
    parsed = urlparse(value)
    if not parsed.netloc:
        return False
    return not parsed.path.lower().endswith(
        (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".css", ".js", ".xml", ".json")
    )


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
    if not isinstance(entry, dict):
        return None
    stamp = _parse(entry.get("at"))
    if stamp is None:
        return None
    url = str(entry.get("url") or "")
    if url:
        return url if now - stamp < timedelta(days=SUCCESS_TTL_DAYS) else None
    return "" if now - stamp < timedelta(hours=FAILURE_TTL_HOURS) else None


def _query_candidates(url: str) -> list[str]:
    parsed = urlparse(str(url or ""))
    query = parse_qs(parsed.query)
    result: list[str] = []
    for key in ("url", "u", "q", "target", "dest", "destination"):
        for value in query.get(key, []):
            candidate = unquote(html.unescape(str(value)))
            if _is_publisher_url(candidate) and candidate not in result:
                result.append(candidate)
    return result


def _metadata_candidates(raw: str, page_url: str) -> list[str]:
    patterns = (
        r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)',
        r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']canonical["\']',
        r'<meta[^>]+property=["\']og:url["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:url["\']',
        r'<meta[^>]+name=["\']twitter:url["\'][^>]+content=["\']([^"\']+)',
    )
    result: list[str] = []
    for pattern in patterns:
        for match in re.findall(pattern, raw, flags=re.I):
            candidate = urljoin(page_url, html.unescape(match))
            if _is_publisher_url(candidate) and candidate not in result:
                result.append(candidate)
    refresh = re.search(r'<meta[^>]+http-equiv=["\']refresh["\'][^>]+content=["\'][^"\']*url\s*=\s*([^"\'>]+)', raw, flags=re.I)
    if refresh:
        candidate = urljoin(page_url, html.unescape(refresh.group(1).strip()))
        if _is_publisher_url(candidate) and candidate not in result:
            result.insert(0, candidate)
    return result


def _lightweight_resolve(url: str) -> str:
    """Recover easy wrappers without Chromium; never raises and stays bounded."""
    for candidate in _query_candidates(url):
        return candidate
    try:
        request = Request(
            url,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.2",
                "Accept-Language": "en-GB,en;q=0.9",
            },
        )
        with build_opener().open(request, timeout=LIGHTWEIGHT_TIMEOUT) as response:
            final = str(response.geturl() or "")
            if _is_publisher_url(final):
                return final
            raw = response.read(512 * 1024).decode("utf-8", errors="ignore")
    except (HTTPError, URLError, TimeoutError, ValueError, OSError):
        return ""
    candidates = _metadata_candidates(raw, final or url)
    return candidates[0] if candidates else ""


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
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
    except Exception:
        return ""
    if _is_google_host(page.url):
        _dismiss_consent(page)
    deadline = SETTLE_MS
    while deadline > 0 and _is_google_host(page.url):
        try:
            page.wait_for_timeout(500)
        except Exception:
            break
        deadline -= 500
    final = str(page.url or "")
    if not final or _is_google_host(final):
        for selector, attribute in (
            ("link[rel='canonical']", "href"),
            ("meta[property='og:url']", "content"),
        ):
            try:
                node = page.query_selector(selector)
                if node:
                    candidate = str(node.get_attribute(attribute) or "")
                    if _is_publisher_url(candidate):
                        return candidate
            except Exception:
                continue
        return ""
    return final if _is_publisher_url(final) else ""


def resolve_wrappers(
    urls: Iterable[str],
    logger=None,
    cache_path: Path = CACHE_PATH,
    max_new: int | None = None,
    browser_factory=None,
) -> dict[str, str]:
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
            continue
        else:
            pending.append(url)

    # Frequent runs get a small cheap recovery pass even when browser resolution
    # is disabled. Do not cache failures: the deep browser must still get a try.
    lightweight_resolved = 0
    still_pending: list[str] = []
    for index, url in enumerate(pending):
        if index >= max(0, LIGHTWEIGHT_MAX):
            still_pending.extend(pending[index:])
            break
        final = _lightweight_resolve(url)
        if final:
            resolved[url] = final
            cache[_cache_key(url)] = {"url": final, "at": _iso(_now())}
            lightweight_resolved += 1
        else:
            still_pending.append(url)
    pending = still_pending
    if lightweight_resolved:
        save_cache(cache, cache_path)
        if logger:
            logger.info("Google News lightweight resolution recovered %d wrapper(s).", lightweight_resolved)

    limit = MAX_NEW_PER_RUN if max_new is None else max_new
    pending = pending[: max(0, limit)]
    if not pending or not ENABLED:
        if logger and pending:
            logger.info(
                "Google News browser resolution disabled; %d link(s) remain for the deep resolver.",
                len(pending),
            )
        return resolved

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover
        if logger:
            logger.warning("Playwright unavailable; Google News links left unresolved: %s", exc)
        return resolved

    succeeded = 0
    budget_seconds = float(os.getenv("GOOGLE_NEWS_RESOLVE_BUDGET_SECONDS", "480"))
    deadline = (time.monotonic() + budget_seconds) if budget_seconds > 0 else None
    stopped_early = False
    try:
        factory = browser_factory or sync_playwright
        with factory() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=["--disable-dev-shm-usage", "--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(
                locale="en-GB",
                timezone_id="Europe/London",
                viewport={"width": 1280, "height": 900},
            )
            page = context.new_page()
            page.set_default_timeout(NAV_TIMEOUT_MS)
            for url in pending:
                if deadline is not None and time.monotonic() >= deadline:
                    stopped_early = True
                    break
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
        if stopped_early and logger:
            logger.info(
                "Google News resolution hit its %.0fs budget after %d browser success(es); remaining wrappers will retry later.",
                budget_seconds,
                succeeded,
            )
    except Exception as exc:
        if logger:
            logger.warning("Google News browser resolution stopped early: %s", exc)

    save_cache(cache, cache_path)
    if logger:
        logger.info(
            "Google News resolution: lightweight=%d browser=%d remaining_attempted=%d cached_total=%d.",
            lightweight_resolved,
            succeeded,
            len(pending),
            len(resolved),
        )
    return resolved
