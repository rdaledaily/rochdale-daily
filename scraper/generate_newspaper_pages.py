"""Generate Rochdale Daily pages with newsroom-style front-page selection.

The underlying archive remains untouched. This runtime patch changes only the
front-page editorial behaviour before delegating to generate_pages.py:

* fresh verified briefs are allowed on the homepage without a 200-word rule;
* manual/editorial stories have no word-count gate once they contain story text;
* minimum useful length varies by story type instead of one blanket threshold;
* source-led fallbacks are judged on their actual text, not rejected by route;
* the configured live-news freshness window is enforced in the generator itself;
* older material remains in archive/category/area pages, not the live homepage;
* explicitly time-limited editor pins and genuinely updated live coverage survive;
* automated same-day deadline notices and stale sports previews cannot reappear;
* freshness bands outrank category prestige and stale featured flags;
* related stories favour the same locality and subject, not category alone.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import os
import re

import enforce_frontpage_freshness as freshness_guard
import frontpage_pipeline as fp
import generate_pages


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
FRONTPAGE_FRESH_HOURS = int(os.getenv("FRONTPAGE_FRESH_HOURS", "14"))

RELATED_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "after", "before", "by", "for",
    "from", "has", "have", "in", "into", "is", "it", "its", "new", "of",
    "on", "over", "rochdale", "says", "the", "to", "under", "with",
}


def _newsroom_low_quality(article):
    return bool(fp.LOW_QUALITY_ARTICLE_RE.search(fp.article_text(article)))


def _minimum_words(article) -> int:
    return CATEGORY_MIN_WORDS.get(fp.article_category(article), DEFAULT_MIN_WORDS)


def _newsroom_eligible(article) -> bool:
    if fp.is_event(article):
        return False
    if article.get("manual_article") or article.get("editorial_lock"):
        return bool(fp.article_text(article).strip())
    return fp.editorial_word_count(article) >= _minimum_words(article)


def _newsroom_rank(article, now: datetime):
    first = fp._frontpage_first_published(article) or datetime.min.replace(tzinfo=timezone.utc)
    latest = freshness_guard.latest_verified_update(article)
    if latest == datetime.min.replace(tzinfo=timezone.utc):
        latest = first
    age_hours = max(0.0, (now - first).total_seconds() / 3600)

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

    importance += min(6, int(article.get("source_count") or 1))

    update_age_hours = max(0.0, (now - latest).total_seconds() / 3600)
    if article.get("is_ongoing") and update_age_hours <= 6:
        importance += 4

    pinned = article.get("featured") is True
    return (freshness, pinned, importance, first, latest)


def _keep_on_live_homepage(article, reference: datetime, cutoff: datetime) -> bool:
    """Own the final live-homepage invariant inside page generation.

    A standalone freshness pass runs earlier in several workflows, but page
    generation rewrites frontpage.json. Time-sensitive expiry rules therefore
    have to be enforced here as well or an expired ticket offer/match preview can
    be reintroduced into the final published snapshot.
    """
    if freshness_guard.is_expired_today_deadline(article, reference):
        return False
    if freshness_guard.is_expired_time_sensitive_preview(article, reference):
        return False

    first = fp._frontpage_first_published(article)
    if first is not None and first >= cutoff:
        return True

    until = fp.parse_datetime(article.get("frontpage_until"))
    if article.get("featured") is True and until is not None and until >= reference:
        return True

    active_live = bool(
        article.get("live_story") is True
        or article.get("breaking_news") is True
        or article.get("is_ongoing") is True
    )
    if not active_live:
        return False

    latest = freshness_guard.latest_verified_update(article)
    return latest >= cutoff


def _normalised_area(article) -> str:
    return str(article.get("area") or "").strip().lower().replace("_", " ")


def _headline_terms(article) -> set[str]:
    text = " ".join(
        str(article.get(field) or "")
        for field in ("title", "excerpt", "searched_location_name")
    ).lower()
    return {
        token for token in re.findall(r"[a-z0-9][a-z0-9'-]{2,}", text)
        if token not in RELATED_STOPWORDS
    }


def _article_types(article) -> set[str]:
    raw = article.get("types") or []
    if isinstance(raw, str):
        raw = [raw]
    return {str(value).strip().lower() for value in raw if str(value).strip()}


def _related_score(current, candidate):
    score = 0
    current_area = _normalised_area(current)
    candidate_area = _normalised_area(candidate)
    if current_area and candidate_area and current_area == candidate_area:
        score += 8

    current_ward = str(fp.ward_for_item(current) or "").strip().lower()
    candidate_ward = str(fp.ward_for_item(candidate) or "").strip().lower()
    if current_ward and candidate_ward and current_ward == candidate_ward:
        score += 10

    if fp.article_category(current) == fp.article_category(candidate):
        score += 5

    shared_types = _article_types(current) & _article_types(candidate)
    score += min(3, len(shared_types) * 2)

    shared_terms = _headline_terms(current) & _headline_terms(candidate)
    score += min(8, len(shared_terms) * 2)

    if candidate.get("manual_article") or candidate.get("editorial_lock"):
        score += 1

    published = generate_pages.parse_iso(generate_pages.first_published_at(candidate))
    return (score, published)


def _newsroom_related_stories_markup(article, all_articles):
    slug = article.get("slug")
    related = [
        candidate for candidate in all_articles
        if candidate.get("slug") != slug
        and str(candidate.get("status") or "published") == "published"
        and not candidate.get("requires_approval")
        and not fp.is_event(candidate)
    ]
    related.sort(key=lambda candidate: _related_score(article, candidate), reverse=True)
    related = related[:4]
    if not related:
        return ""

    items = []
    for item in related:
        title = generate_pages.esc(item.get("title") or "Local news update")
        item_slug = generate_pages.esc(item.get("slug") or item.get("id") or "")
        image = generate_pages.esc(generate_pages.absolute_url(item.get("image_url") or ""))
        image_markup = (
            f'<img src="{image}" alt="" loading="lazy" decoding="async">'
            if image else ""
        )
        items.append(
            f'<a class="related-story" href="{item_slug}.html">'
            f'{image_markup}<span class="related-title">{title}</span></a>'
        )
    return '<div class="sidebar-box"><h3>Related local stories</h3>' + "".join(items) + "</div>"


def _newsroom_select_frontpage(articles, now=None):
    reference = now or fp.utc_now()
    base = [
        article for article in articles
        if str(article.get("status") or "published") == "published"
        and not fp.is_job_or_career_post(article)
        and _newsroom_eligible(article)
    ]

    primary_cutoff = reference - timedelta(days=fp.PRIMARY_DAYS)
    fallback_cutoff = reference - timedelta(days=fp.FALLBACK_DAYS)
    primary = [article for article in base if fp._age_eligible(article, primary_cutoff)]
    fallback = [article for article in base if fp._age_eligible(article, fallback_cutoff)]

    primary = sorted(primary, key=lambda item: _newsroom_rank(item, reference), reverse=True)
    fallback = sorted(fallback, key=lambda item: _newsroom_rank(item, reference), reverse=True)

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

    homepage_cutoff = reference - timedelta(hours=FRONTPAGE_FRESH_HOURS)
    arranged = [
        item for item in arranged
        if _keep_on_live_homepage(item, reference, homepage_cutoff)
    ]

    fresh_24h_cutoff = reference - timedelta(hours=24)
    diagnostics = dict(diagnostics)
    diagnostics.update({
        "pool_size": len(pool),
        "primary_pool_size": len(primary),
        "fallback_stories_used": max(0, len(pool) - len(primary)),
        "selection_window_days": fp.PRIMARY_DAYS if len(pool) == len(primary) else fp.FALLBACK_DAYS,
        "frontpage_count": len(arranged),
        "homepage_freshness_hours": FRONTPAGE_FRESH_HOURS,
        "fresh_under_24h": sum(
            1 for item in arranged
            if (fp._frontpage_first_published(item) or datetime.min.replace(tzinfo=timezone.utc)) >= fresh_24h_cutoff
        ),
        "fresh_under_homepage_window": sum(
            1 for item in arranged
            if (fp._frontpage_first_published(item) or datetime.min.replace(tzinfo=timezone.utc)) >= homepage_cutoff
        ),
        "short_briefs_selected": sum(
            1 for item in arranged if fp.editorial_word_count(item) < 200
        ),
        "selected_by_category": dict(Counter(fp.category_key(item) for item in arranged)),
        "selected_by_ward": dict(Counter(fp.ward_for_item(item) or "borough-wide" for item in arranged)),
        "selected_by_source": dict(Counter(fp.source_key(item) for item in arranged)),
    })
    return arranged, diagnostics


def main() -> None:
    fp.is_low_quality_article = _newsroom_low_quality
    fp._article_rank = _newsroom_rank
    fp.select_frontpage = _newsroom_select_frontpage
    generate_pages.related_stories_markup = _newsroom_related_stories_markup
    generate_pages.main()


if __name__ == "__main__":
    main()
