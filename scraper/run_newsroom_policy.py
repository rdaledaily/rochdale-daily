#!/usr/bin/env python3
"""Install production-only source policy before running the newsroom.

Local news publishers are valid discovery/corroboration sources. They are not
allowed to leak into Rochdale Daily's reader-facing copy, and their photographs
are not automatically republished. The existing mandatory original rewrite,
source-overlap guard and publisher-leak gate remain the publication controls.
"""
from __future__ import annotations

import json
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

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


def _host(url: str) -> str:
    host = (urlparse(str(url or "")).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


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


def install_runtime_policy() -> None:
    """Make discovery broad while keeping publication/copyright controls strict."""
    if getattr(core, "_RD_RUNTIME_SOURCE_POLICY_INSTALLED", False):
        return

    original_source_is_denied = core.source_is_denied

    def source_is_denied(source_name: str = "", source_url: str = "") -> bool:
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
    core._RD_RUNTIME_SOURCE_POLICY_INSTALLED = True
    core.log.info(
        "Runtime source policy: local publishers enabled for discovery/corroboration; "
        "automatic publisher-image reuse restricted to the explicit allowlist."
    )


def _normalise_runtime_status() -> None:
    """Keep diagnostic status aligned with the policy actually used in production."""
    try:
        status = json.loads(core.STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(status, dict):
        return
    status["prohibited_sources"] = [
        "pressreader.com",
        "autouncle.co.uk",
        "tes.com",
        "tiktok.com",
        "youtube.com",
        "reddit.com",
        "classified/spam denylist",
    ]
    status["local_publishers_discovery_enabled"] = sorted(LOCAL_PUBLISHER_DOMAINS)
    status["local_publisher_public_copy_policy"] = (
        "May be used for discovery/corroboration and source metadata only; publisher names are blocked from reader-facing copy."
    )
    status["publisher_source_image_policy"] = (
        "Automatic source-image reuse is limited to IMAGE_REUSE_SOURCE_DOMAINS; other sources fall back to curated/Commons/generated artwork."
    )
    status["source_led_fallback_enabled"] = False
    status["crime_direct_publish_enabled"] = False
    status["crime_ai_gate_enabled"] = True
    core.write_json_atomic(core.STATUS_FILE, status)


def main() -> int:
    install_runtime_policy()
    result = pipeline.main()
    if result == 0:
        _normalise_runtime_status()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
