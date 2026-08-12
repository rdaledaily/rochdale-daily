"""Freshness-first front-page policy for Rochdale Daily.

The scraper can publish useful local briefs from 50 words, but the legacy
front-page selector still heavily penalised anything below 200 words and could
replace the whole candidate pool with long-form stories only. That made a
healthy scrape look stale on the public site.

This module keeps the existing balancing/capping logic, but:
- uses story-type minimums rather than a blanket 200-word preference;
- makes original publication time the dominant freshness signal;
- prevents old ongoing stories from becoming "new" just because they were
  re-scraped or lightly updated;
- still allows editor-pinned stories to lead;
- keeps jobs/career posts out before homepage selection.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

import frontpage_pipeline as fp


CATEGORY_MIN_WORDS = {
    "crime": 60,
    "traffic": 60,
    "transport": 60,
    "news": 60,
    "community": 75,
    "business": 75,
    "health": 75,
    "education": 75,
    "politics": 75,
    "environment": 75,
    "sport": 75,
}
DEFAULT_MIN_WORDS = 75


def minimum_words(article: dict[str, Any]) -> int:
    """Return a pragmatic minimum for a useful local-news homepage brief."""
    if article.get("manual_article") or article.get("editorial_lock"):
        return 50
    return CATEGORY_MIN_WORDS.get(fp.article_category(article), DEFAULT_MIN_WORDS)


def homepage_eligible(article: dict[str, Any]) -> bool:
    if fp.is_event(article):
        return False
    return fp.editorial_word_count(article) >= minimum_words(article)


def freshness_rank(article: dict[str, Any], now: datetime) -> tuple[Any, ...]:
    """Rank genuinely new stories ahead of old stories receiving small updates."""
    category = fp.article_category(article)
    first_published = (
        fp._frontpage_first_published(article)
        or datetime.min.replace(tzinfo=timezone.utc)
    )
    latest_update = fp.parse_datetime(
        article.get("last_updated_at")
        or article.get("published_at")
        or article.get("scraped_at")
    ) or first_published

    age_hours = max(0.0, (now - first_published).total_seconds() / 3600)
    update_age_hours = max(0.0, (now - latest_update).total_seconds() / 3600)

    importance = {
        "crime": 100,
        "traffic": 82,
        "transport": 78,
        "politics": 74,
        "health": 72,
        "education": 68,
        "community": 64,
        "news": 62,
        "business": 58,
        "environment": 56,
        "sport": 54,
    }.get(category, 50)

    # Freshness is explicit and based on first publication, not scraped_at.
    if age_hours <= 6:
        freshness_bucket = 4
        importance += 30
    elif age_hours <= 24:
        freshness_bucket = 3
        importance += 20
    elif age_hours <= 48:
        freshness_bucket = 2
        importance += 8
    else:
        freshness_bucket = 1

    # A substantive ongoing update can receive a modest boost, but cannot
    # outrank a genuinely new story merely because its timestamp changed.
    if article.get("is_ongoing") and update_age_hours <= 6:
        importance += 4

    importance += min(6, int(article.get("source_count") or 1))
    importance -= min(60, age_hours * 1.5)

    pinned = article.get("featured") is True
    return (pinned, freshness_bucket, importance, first_published, latest_update)


def select_frontpage(
    articles: list[dict[str, Any]],
    now: datetime | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Select a fresh, balanced homepage without a blanket 200-word gate."""
    reference = now or fp.utc_now()
    base = [
        article for article in articles
        if str(article.get("status") or "published") == "published"
        and not fp.is_job_or_career_post(article)
        and homepage_eligible(article)
    ]

    primary_cutoff = reference - timedelta(days=fp.PRIMARY_DAYS)
    fallback_cutoff = reference - timedelta(days=fp.FALLBACK_DAYS)
    primary = [article for article in base if fp._age_eligible(article, primary_cutoff)]
    fallback = [article for article in base if fp._age_eligible(article, fallback_cutoff)]

    # Prefer the primary freshness window. Only widen when there are not enough
    # current stories to fill the requested front-page target.
    pool = primary if len(primary) >= fp.FRONTPAGE_TARGET else fallback
    pool = sorted(pool, key=lambda item: freshness_rank(item, reference), reverse=True)

    balanced, diagnostics = fp.balanced_select(
        pool,
        limit=min(fp.FRONTPAGE_TARGET, len(pool)),
        max_per_source=4,
        max_per_category=6,
    )
    target = min(fp.FRONTPAGE_TARGET, len(pool))
    capped = fp._cap_selected(
        balanced + [item for item in pool if item not in balanced],
        target,
    )
    capped = fp.enforce_category_minimums(
        capped,
        pool,
        target,
        fp.category_key,
        fp.DEFAULT_CATEGORY_MINIMUMS,
    )
    arranged = fp.arrange_frontpage(capped, reference)

    diagnostics = dict(diagnostics)
    diagnostics.update({
        "pool_size": len(pool),
        "primary_pool_size": len(primary),
        "selection_window_days": fp.PRIMARY_DAYS if len(primary) >= fp.FRONTPAGE_TARGET else fp.FALLBACK_DAYS,
        "frontpage_count": len(arranged),
        "fresh_under_24h": sum(
            1 for item in arranged
            if (fp._frontpage_first_published(item) or datetime.min.replace(tzinfo=timezone.utc))
            >= reference - timedelta(hours=24)
        ),
        "short_briefs_selected": sum(
            1 for item in arranged if fp.editorial_word_count(item) < 200
        ),
        "selected_by_category": dict(Counter(fp.category_key(item) for item in arranged)),
        "selected_by_ward": dict(Counter(fp.ward_for_item(item) or "borough-wide" for item in arranged)),
        "selected_by_source": dict(Counter(fp.source_key(item) for item in arranged)),
    })
    return arranged, diagnostics


def install() -> None:
    """Install the policy before generate_pages imports front-page functions."""
    fp._article_rank = freshness_rank
    fp.select_frontpage = select_frontpage
