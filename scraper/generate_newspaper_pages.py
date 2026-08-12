"""Generate Rochdale Daily pages with newsroom-style front-page selection.

The underlying archive remains untouched. This runtime patch changes only the
front-page editorial behaviour before delegating to generate_pages.py:

* fresh verified briefs are allowed on the homepage even when under 200 words;
* source-led fallbacks are judged on their actual text, not rejected by route;
* the last 24 hours is the main news pool;
* older material is used only when needed to reach the minimum front-page size;
* freshness bands outrank category prestige so yesterday's feature cannot beat
  a genuinely new local incident simply because it is longer.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

import frontpage_pipeline as fp
import generate_pages


def _newsroom_low_quality(article):
    """Reject boilerplate, not an otherwise factual article's publication route."""
    return bool(fp.LOW_QUALITY_ARTICLE_RE.search(fp.article_text(article)))


def _newsroom_rank(article, now: datetime):
    first = fp._frontpage_first_published(article) or datetime.min.replace(tzinfo=timezone.utc)
    latest = fp.parse_datetime(
        article.get("last_updated_at")
        or article.get("published_at")
        or article.get("scraped_at")
    ) or first
    age_hours = max(0.0, (now - first).total_seconds() / 3600)

    # Newspaper-style freshness bands. A new verified brief should normally
    # outrank an older feature; importance then decides within each band.
    if age_hours <= 3:
        freshness = 5
    elif age_hours <= 6:
        freshness = 4
    elif age_hours <= 12:
        freshness = 3
    elif age_hours <= 24:
        freshness = 2
    elif age_hours <= 48:
        freshness = 1
    else:
        freshness = 0

    importance = {
        "crime": 100,
        "traffic": 92,
        "transport": 88,
        "health": 84,
        "politics": 80,
        "education": 72,
        "community": 68,
        "news": 66,
        "business": 62,
        "environment": 60,
        "sport": 58,
        "events": 40,
    }.get(fp.article_category(article), 60)

    # Multi-source confirmation is useful, but length itself is not a reason
    # to suppress a short factual local brief.
    importance += min(6, int(article.get("source_count") or 1))
    pinned = article.get("featured") is True
    return (pinned, freshness, importance, first, latest)


def _newsroom_select_frontpage(articles, now=None):
    reference = now or fp.utc_now()
    base = [
        article for article in articles
        if str(article.get("status") or "published") == "published"
        and not fp.is_job_or_career_post(article)
    ]

    primary_cutoff = reference - timedelta(days=fp.PRIMARY_DAYS)
    fallback_cutoff = reference - timedelta(days=fp.FALLBACK_DAYS)
    primary = [article for article in base if fp._age_eligible(article, primary_cutoff)]
    fallback = [article for article in base if fp._age_eligible(article, fallback_cutoff)]

    primary = sorted(primary, key=lambda item: _newsroom_rank(item, reference), reverse=True)
    fallback = sorted(fallback, key=lambda item: _newsroom_rank(item, reference), reverse=True)

    # Do not replace a small fresh front page with an entire older fallback
    # window. Add only enough older stories to reach the minimum.
    pool = list(primary)
    if len(pool) < fp.FRONTPAGE_MIN:
        for item in fallback:
            if item in pool:
                continue
            pool.append(item)
            if len(pool) >= fp.FRONTPAGE_MIN:
                break

    pool = sorted(pool, key=lambda item: _newsroom_rank(item, reference), reverse=True)
    target = min(fp.FRONTPAGE_TARGET, len(pool))
    balanced, diagnostics = fp.balanced_select(
        pool,
        limit=target,
        max_per_source=4,
        max_per_category=6,
    )
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
        "fallback_stories_used": max(0, len(pool) - len(primary)),
        "selection_window_days": fp.PRIMARY_DAYS if len(pool) == len(primary) else fp.FALLBACK_DAYS,
        "frontpage_count": len(arranged),
        "selected_by_category": dict(Counter(fp.category_key(item) for item in arranged)),
        "selected_by_ward": dict(Counter(fp.ward_for_item(item) or "borough-wide" for item in arranged)),
        "selected_by_source": dict(Counter(fp.source_key(item) for item in arranged)),
    })
    return arranged, diagnostics


def main() -> None:
    fp.is_low_quality_article = _newsroom_low_quality
    fp._article_rank = _newsroom_rank
    fp.select_frontpage = _newsroom_select_frontpage
    generate_pages.main()


if __name__ == "__main__":
    main()
