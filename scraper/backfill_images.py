"""Sweep articles.json and backfill a real publisher image for any article
that's still on its generic category stock image.

Why this exists as a separate script, not just the per-run fix in
rewrite_candidate(): that fix only ever runs for a candidate at the moment
it's freshly rewritten, so it only helps *new* articles going forward. It
does nothing for the hundred-plus articles already published before that fix
existed, and it can't retry an article whose one backfill attempt happened
to fail on a transient network error. This script closes both gaps: it
sweeps the whole live archive every time it runs, so it catches existing
articles once and keeps re-checking future ones as a safety net alongside
the per-run backfill.

It deliberately reuses scraper.py's own functions (page_metadata,
cache_source_image, the shared SESSION with its retry adapter and slow-
domain circuit breaker) rather than reimplementing any of that, so an image
obtained here is cached and attributed in exactly the same way as one
obtained during a normal scrape.

Usage: python scraper/backfill_images.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scraper import (  # noqa: E402
    Candidate,
    OUTPUT_FILE,
    CATEGORY_STOCK_IMAGES,
    cache_source_image,
    page_metadata,
    write_json_atomic,
    log,
)

# Events and live-page candidates are deliberately excluded, matching the
# same reasoning as the per-run backfill in rewrite_candidate(): live pages
# (weather, travel alerts) essentially never expose a usable publisher
# image and are already re-fetched during normal collection, and ticket
# events have their own separate, deliberately conservative image-reuse
# policy in frontpage_pipeline.py (parse_event_detail), which this script
# should not override.
SKIPPED_SOURCE_KINDS = {"event", "live"}

# A soft cap on how many articles get a fresh page_metadata() fetch attempt
# in a single run. The full archive only grows over time; without a cap, a
# large backlog could turn a routine sweep into an unbounded, slow run. Any
# article not reached this run is simply picked up on the next scheduled
# run, so nothing is lost -- it just arrives over a few runs instead of one.
MAX_FETCH_ATTEMPTS_PER_RUN = 150


def has_real_cached_image(article: dict[str, Any]) -> bool:
    """True when this article already carries a genuine cached publisher
    image rather than a generic category stock image.

    image_credit_url is only ever set by cache_source_image() on a
    successful cache, so its presence is the reliable marker -- checking
    image_url against the stock-image path would also catch legitimate
    manually-uploaded images that intentionally reuse a stock filename.
    """
    return bool(str(article.get("image_credit_url") or "").strip())


def build_candidate(article: dict[str, Any], image_candidate_url: str = "") -> Candidate:
    return Candidate(
        source_name=str(article.get("source_name") or ""),
        source_url=str(article.get("source_url") or ""),
        source_title=str(article.get("title") or ""),
        source_summary=str(article.get("excerpt") or ""),
        source_published_at=str(article.get("published_at") or ""),
        area=str(article.get("area") or "rochdale"),
        category=str(article.get("category") or "news"),
        image_candidate_url=image_candidate_url,
        source_kind=str(article.get("source_kind") or "article"),
    )


def needs_metadata_fetch(article: dict[str, Any]) -> bool:
    """True when this article has no known image candidate at all yet, and
    would need a fresh page_metadata() network fetch to find one.

    Used both to decide the outcome inside backfill_one() and, before that,
    to decide whether this article counts against the per-run fetch cap --
    the same single check drives both, so they can't drift out of sync.
    """
    return (
        not has_real_cached_image(article)
        and not article.get("editorial_lock")
        and str(article.get("source_kind") or "article") not in SKIPPED_SOURCE_KINDS
        and bool(str(article.get("source_url") or "").strip())
        and not str(article.get("source_image_candidate_url") or "").strip()
    )


def backfill_one(article: dict[str, Any], allow_fetch: bool) -> tuple[dict[str, Any], str]:
    """Attempt to backfill a single article's image.

    allow_fetch controls only whether a *fresh* page_metadata() network
    fetch is permitted this run (the per-run cap); an article that already
    has a known image_candidate_url from an earlier attempt is still
    retried regardless of allow_fetch, since that's just a cache attempt
    with no new network lookup needed.

    Returns (possibly updated article, outcome label) where outcome is one
    of: "already-cached", "skipped-kind", "editorial-lock", "no-source-url",
    "deferred-to-next-run", "backfilled", "still-fallback".
    """
    if article.get("editorial_lock"):
        return article, "editorial-lock"
    if str(article.get("source_kind") or "article") in SKIPPED_SOURCE_KINDS:
        return article, "skipped-kind"
    if has_real_cached_image(article):
        return article, "already-cached"

    source_url = str(article.get("source_url") or "").strip()
    if not source_url:
        return article, "no-source-url"

    image_candidate_url = str(article.get("source_image_candidate_url") or "").strip()
    if not image_candidate_url:
        if not allow_fetch:
            return article, "deferred-to-next-run"
        try:
            meta = page_metadata(source_url)
            image_candidate_url = str(meta.get("image") or "").strip()
        except Exception as exc:
            log.debug("Backfill metadata fetch failed for %s: %s", source_url, exc)
            image_candidate_url = ""

    if not image_candidate_url:
        return article, "still-fallback"

    candidate = build_candidate(article, image_candidate_url)
    category = str(article.get("category") or "news")
    if category not in CATEGORY_STOCK_IMAGES:
        category = "news"

    image_url, image_credit, image_credit_url, original_image_url = cache_source_image(
        candidate, category
    )

    article["image_url"] = image_url
    article["image_credit"] = image_credit
    article["image_credit_url"] = image_credit_url
    article["source_image_candidate_url"] = original_image_url
    article["source_image_reuse_status"] = (
        "publisher-image-cached-and-credited" if image_credit_url else "category-fallback"
    )

    return article, ("backfilled" if image_credit_url else "still-fallback")


def main() -> int:
    import json

    try:
        articles = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.error("Could not read %s: %s", OUTPUT_FILE, exc)
        return 1
    if not isinstance(articles, list):
        log.error("%s did not contain a JSON list; aborting.", OUTPUT_FILE)
        return 1

    counts: dict[str, int] = {}
    fetch_attempts_used = 0
    updated = []

    for article in articles:
        if not isinstance(article, dict):
            updated.append(article)
            continue

        allow_fetch = True
        if needs_metadata_fetch(article):
            allow_fetch = fetch_attempts_used < MAX_FETCH_ATTEMPTS_PER_RUN
            if allow_fetch:
                fetch_attempts_used += 1

        article, outcome = backfill_one(article, allow_fetch)
        counts[outcome] = counts.get(outcome, 0) + 1
        updated.append(article)

    write_json_atomic(OUTPUT_FILE, updated)

    summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    log.info("Image backfill complete: %d total articles, %s", len(updated), summary)
    print(f"Image backfill complete: {len(updated)} total articles, {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
