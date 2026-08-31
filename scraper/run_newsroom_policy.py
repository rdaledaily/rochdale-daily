#!/usr/bin/env python3
"""Install production-only source and newsroom quality policy.

Local news publishers are valid discovery/corroboration sources. They are not
allowed to leak into Rochdale Daily's reader-facing copy, and their photographs
are not automatically republished. The existing mandatory original rewrite,
source-overlap guard and publisher-leak gate remain the publication controls.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import editorial_upgrade as editorial
import live_story_updates as live_updates
import run_newspaper_pipeline as pipeline

core = pipeline.core

LOCAL_PUBLISHER_DOMAINS = {
    "rochdaletimes.co.uk",
    "rochdaleonline.co.uk",
    "rochdaleobserver.co.uk",
}
LOCAL_PUBLISHER_NAMES = (
    "rochdale times",
    "rochdale online",
    "rochdale observer",
)
CHALLENGE_PATH_MARKERS = (
    "/.well-known/sgcaptcha/",
    "/cdn-cgi/challenge-platform/",
    "/captcha/",
)


def _host(url: str) -> str:
    host = (urlparse(str(url or "")).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _is_challenge_url(source_url: str = "") -> bool:
    """Reject bot/challenge endpoints that can never be useful source articles."""
    try:
        path = (urlparse(str(source_url or "")).path or "").lower()
    except Exception:
        return False
    return any(marker in path for marker in CHALLENGE_PATH_MARKERS)


def _is_local_publisher(source_name: str = "", source_url: str = "") -> bool:
    host = _host(source_url)
    name = str(source_name or "").strip().casefold()
    return (
        host in LOCAL_PUBLISHER_DOMAINS
        or any(name == publisher or name.startswith(publisher + " ") for publisher in LOCAL_PUBLISHER_NAMES)
    )


def _remove_local_publisher_search_exclusions(url: str) -> str:
    """Remove only the legacy exclusions for legitimate local publishers."""
    parsed = urlparse(str(url or ""))
    params = parse_qs(parsed.query, keep_blank_values=True)
    queries = params.get("q") or []
    if not queries:
        return str(url or "")
    query = str(queries[0])
    for domain in ("rochdaletimes.co.uk", "rochdaleonline.co.uk"):
        query = query.replace(f" -site:{domain}", "")
    params["q"] = [query]
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            urlencode(params, doseq=True),
            parsed.fragment,
        )
    )


def _remove_near_target_length_issue(
    issues: list[str],
    draft,
    source_text: str,
    source_kind: str = "",
) -> list[str]:
    """Treat a near-200 rich report as complete instead of forcing padding.

    The 200-word rich-source budget remains the writing target. Its quality gate
    gets a 5% (10-word) tolerance so a grounded 197-word story is not sent
    through four expansion retries merely to manufacture three words. Thin
    sources keep their exact adaptive floors/caps, so this cannot weaken the
    short-brief anti-padding rules.
    """
    floor, _cap = editorial.length_budget(source_text, source_kind)
    if floor < 200:
        return list(issues)
    clean = editorial.normalise_draft(draft)
    words = editorial.draft_word_count(clean) if clean else 0
    tolerance = max(10, int(round(floor * 0.05)))
    if not (floor - tolerance <= words < floor):
        return list(issues)
    prefix = f"Write at least {floor} body words"
    return [issue for issue in issues if not str(issue).startswith(prefix)]


def _should_watch_developing_article(article: dict) -> bool:
    """Watch genuine developing sources, not every legacy row carrying LIVE.

    Historic bad data marked static council service pages such as council-tax,
    bins and generic guidance as `live_story`. They were safely prevented from
    republishing, but repeatedly re-fetching them wastes the frequent-run budget.
    Explicit live/live-refresh records, breaking coverage and rows already
    carrying timestamped live updates remain watched. For legacy Rochdale Council
    rows, an otherwise bare LIVE flag is accepted only on news articles or
    directory records (the latter covers changing roadworks/closure notices).
    """
    if not isinstance(article, dict):
        return False
    kind = str(article.get("source_kind") or "").strip().lower()
    if kind in {"live", "live_refresh"} or article.get("breaking_news") is True:
        return True
    raw_updates = article.get("live_updates") or []
    if isinstance(raw_updates, list) and any(isinstance(row, dict) and row.get("timestamp") for row in raw_updates):
        return True
    if not (article.get("live_story") is True or article.get("is_ongoing") is True):
        return False

    source_url = str(article.get("source_url") or "")
    parsed = urlparse(source_url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = (parsed.path or "/").lower()
    if host == "rochdale.gov.uk" or host.endswith(".rochdale.gov.uk"):
        return path.startswith("/news/article/") or path.startswith("/directory-record/")
    return True


def install_runtime_policy() -> None:
    """Make discovery broad while keeping publication/copyright controls strict."""
    if getattr(core, "_RD_RUNTIME_SOURCE_POLICY_INSTALLED", False):
        return

    original_source_is_denied = core.source_is_denied

    def source_is_denied(source_name: str = "", source_url: str = "") -> bool:
        # Challenge/CAPTCHA endpoints are not articles. Reject them before the
        # local-publisher discovery exemption so they cannot consume fetch or AI
        # budget on the fast lane.
        if _is_challenge_url(source_url):
            return True
        # Local competitors may inform a story. They still have to pass locality,
        # freshness, AI rewrite, copying and public-copy publisher-leak gates.
        if _is_local_publisher(source_name, source_url):
            return False
        return original_source_is_denied(source_name, source_url)

    core.source_is_denied = source_is_denied

    original_google_news_sources = core.google_news_sources

    def google_news_sources():
        sources = original_google_news_sources()
        for source in sources:
            if isinstance(source, dict) and source.get("url"):
                source["url"] = _remove_local_publisher_search_exclusions(str(source["url"]))
        return sources

    core.google_news_sources = google_news_sources

    original_source_image_allowed = core._source_image_allowed

    def source_image_allowed(candidate) -> bool:
        # Discovery permission is not image-reuse permission. Only sources in the
        # explicit reuse allowlist may have their publisher image cached/reused.
        if not original_source_image_allowed(candidate):
            return False
        host = core.domain_of(str(getattr(candidate, "source_url", "") or ""))
        return any(
            host == allowed or host.endswith("." + allowed)
            for allowed in core.IMAGE_REUSE_SOURCE_DOMAINS
        )

    core._source_image_allowed = source_image_allowed

    original_editorial_quality_issues = core.editorial_quality_issues

    def editorial_quality_issues(draft, source_text: str, source_kind: str = ""):
        issues = original_editorial_quality_issues(draft, source_text, source_kind)
        return _remove_near_target_length_issue(
            issues,
            draft,
            source_text,
            source_kind,
        )

    core.editorial_quality_issues = editorial_quality_issues
    live_updates._is_developing = _should_watch_developing_article
    core._RD_RUNTIME_SOURCE_POLICY_INSTALLED = True
    core.log.info(
        "Runtime source policy: local publishers enabled for discovery/corroboration; "
        "challenge/CAPTCHA endpoints rejected before processing; "
        "automatic publisher-image reuse restricted to the explicit allowlist; "
        "rich-source 200-word target uses a 10-word no-padding tolerance; "
        "developing-source watches exclude legacy static council guidance pages."
    )


def _read_status() -> dict:
    try:
        status = json.loads(core.STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return status if isinstance(status, dict) else {}


def _preserved_evergreen_status() -> dict:
    """Keep fallback attempt state even if the core scraper rewrites status.json."""
    return {
        key: value
        for key, value in _read_status().items()
        if str(key).startswith("evergreen_")
    }


def _normalise_runtime_status(preserved_evergreen: dict | None = None) -> None:
    """Keep diagnostic status aligned with the policy actually used in production."""
    status = _read_status()
    if not status:
        return
    if preserved_evergreen:
        status.update(preserved_evergreen)
    status["prohibited_sources"] = [
        "pressreader.com",
        "autouncle.co.uk",
        "tes.com",
        "tiktok.com",
        "youtube.com",
        "reddit.com",
        "classified/spam denylist",
        "captcha/challenge endpoints",
    ]
    status["local_publishers_discovery_enabled"] = sorted(LOCAL_PUBLISHER_DOMAINS)
    status["local_publisher_public_copy_policy"] = (
        "May be used for discovery/corroboration and source metadata only; publisher names are blocked from reader-facing copy."
    )
    status["publisher_source_image_policy"] = (
        "Automatic source-image reuse is limited to IMAGE_REUSE_SOURCE_DOMAINS; other sources fall back to curated/Commons/generated artwork."
    )
    status["rich_source_length_policy"] = (
        "200 words remains the target; grounded drafts within 10 words of it are accepted rather than padded."
    )
    status["developing_story_watch_policy"] = (
        "Only explicit live/breaking/timestamped-update records and plausible changing authoritative pages are rechecked; static legacy council guidance is not."
    )
    status["source_led_fallback_enabled"] = True
    status["evergreen_fallback_policy"] = (
        "After each newsroom run: publish at most one researched evergreen when fewer than 6 qualifying new local stories exist in the trailing 12 hours, only 09:00-20:00 Europe/London, with a 24-hour publication cooldown and a 1-hour failed-attempt backoff."
    )
    status["crime_direct_publish_enabled"] = False
    status["crime_ai_gate_enabled"] = True
    core.write_json_atomic(core.STATUS_FILE, status)


def _maybe_run_evergreen_fallback() -> None:
    """Measure supply after the real-news scrape and invoke one bounded fallback."""
    try:
        import evergreen_fallback as evergreen

        articles = evergreen.read_json(evergreen.ARTICLES_PATH, [])
        if not isinstance(articles, list):
            core.log.warning("Evergreen fallback skipped: articles.json is not a list")
            return

        now = datetime.now(timezone.utc)
        decision = evergreen.evaluate_trigger(articles, now)
        if not decision.should_publish:
            core.log.info(
                "Evergreen fallback skip: %s (%s qualifying stories; threshold %s)",
                decision.reason,
                decision.qualifying_count,
                decision.threshold,
            )
            return

        status = _read_status()
        last_attempt = evergreen.parse_dt(status.get("evergreen_fallback_attempt_at"))
        if last_attempt is not None and now - last_attempt < timedelta(hours=1):
            core.log.info(
                "Evergreen fallback skip: failed-attempt backoff until one hour after %s",
                last_attempt.isoformat(),
            )
            return

        status["evergreen_fallback_attempt_at"] = now.isoformat().replace("+00:00", "Z")
        status["evergreen_fallback_attempt_reason"] = decision.reason
        status["evergreen_fallback_attempt_count"] = decision.qualifying_count
        core.write_json_atomic(core.STATUS_FILE, status)

        evergreen.main()
    except Exception as exc:
        # Fallback content is supplementary. It must never make the real-news
        # pipeline fail or prevent a valid edition from publishing.
        core.log.exception("Evergreen fallback guarded failure: %s", exc)


def main() -> int:
    install_runtime_policy()
    preserved_evergreen = _preserved_evergreen_status()
    result = pipeline.main()
    if result == 0:
        _normalise_runtime_status(preserved_evergreen)
        _maybe_run_evergreen_fallback()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
