"""Operational health checks for the autonomous Rochdale Daily newsroom.

A green GitHub Actions run is not proof that the newsroom worked. This module
measures the reader-facing outcome: did the run discover and publish fresh,
local journalism, and where did candidates disappear when it did not?
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def newest_article_age_hours(articles: list[dict[str, Any]], now: datetime) -> float | None:
    dates = []
    for article in articles:
        if str(article.get("status") or "published").lower() != "published":
            continue
        value = parse_datetime(
            article.get("first_published_at")
            or article.get("published_at")
            or article.get("scraped_at")
        )
        if value is not None:
            dates.append(value)
    if not dates:
        return None
    return max(0.0, (now - max(dates)).total_seconds() / 3600.0)


def build_health_report(
    *,
    now: datetime,
    published: list[dict[str, Any]],
    raw_candidates: int,
    candidate_clusters: int,
    eligible_candidates: int,
    selected_candidates: int,
    new_articles: int,
    rejection_reasons: dict[str, int],
    collector_counts: dict[str, int],
    collector_errors: dict[str, str],
    google_resolution: dict[str, Any],
) -> dict[str, Any]:
    newest_age = newest_article_age_hours(published, now)
    conversion = (new_articles / selected_candidates) if selected_candidates else 1.0
    warnings: list[str] = []

    if raw_candidates == 0:
        warnings.append("No raw news candidates were discovered.")
    if candidate_clusters and eligible_candidates == 0:
        warnings.append("Candidates were discovered but none reached rewrite eligibility.")
    if selected_candidates >= 5 and conversion < 0.50:
        warnings.append(
            f"Rewrite-to-publication conversion is only {conversion:.0%}; inspect rejection_reasons."
        )
    if newest_age is None:
        warnings.append("No dated published articles are available.")
    elif newest_age > 12:
        warnings.append(
            f"Newest published article is {newest_age:.1f} hours old; the newsroom is stale."
        )
    wrappers = int(google_resolution.get("wrappers") or 0)
    resolved = int(google_resolution.get("resolved") or 0)
    if wrappers >= 5 and resolved == 0:
        warnings.append(
            f"Google News supplied {wrappers} wrapper leads but none resolved to publisher pages."
        )
    if collector_errors:
        warnings.append(f"{len(collector_errors)} collector(s) reported errors.")

    return {
        "healthy": not warnings,
        "newest_article_age_hours": round(newest_age, 2) if newest_age is not None else None,
        "rewrite_to_publication_conversion": round(conversion, 4),
        "funnel": {
            "raw_candidates": raw_candidates,
            "candidate_clusters": candidate_clusters,
            "eligible_candidates": eligible_candidates,
            "selected_candidates": selected_candidates,
            "new_articles": new_articles,
        },
        "rejection_reasons": dict(sorted(rejection_reasons.items())),
        "collector_counts": collector_counts,
        "collector_errors": collector_errors,
        "google_news_resolution": google_resolution,
        "warnings": warnings,
    }
