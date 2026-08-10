from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pipeline_health import build_health_report


def test_stale_low_conversion_run_is_unhealthy() -> None:
    now = datetime(2026, 8, 8, 18, tzinfo=timezone.utc)
    published = [{
        "status": "published",
        "published_at": (now - timedelta(days=3)).isoformat(),
    }]
    report = build_health_report(
        now=now,
        published=published,
        raw_candidates=57,
        candidate_clusters=43,
        eligible_candidates=33,
        selected_candidates=33,
        new_articles=5,
        rejection_reasons={"rewrite_failed": 28},
        collector_counts={"rss": 25},
        collector_errors={},
        google_resolution={"wrappers": 22, "resolved": 0},
    )
    assert not report["healthy"]
    assert report["rewrite_to_publication_conversion"] < 0.2
    assert report["newest_article_age_hours"] == 72.0
    assert len(report["warnings"]) >= 3


def test_fresh_productive_run_is_healthy() -> None:
    now = datetime(2026, 8, 8, 18, tzinfo=timezone.utc)
    published = [{
        "status": "published",
        "published_at": (now - timedelta(hours=1)).isoformat(),
    }]
    report = build_health_report(
        now=now,
        published=published,
        raw_candidates=60,
        candidate_clusters=45,
        eligible_candidates=30,
        selected_candidates=20,
        new_articles=16,
        rejection_reasons={"non_news": 4},
        collector_counts={"rss": 30, "direct": 30},
        collector_errors={},
        google_resolution={"wrappers": 8, "resolved": 6},
    )
    assert report["healthy"]
    assert report["rewrite_to_publication_conversion"] == 0.8


if __name__ == "__main__":
    test_stale_low_conversion_run_is_unhealthy()
    test_fresh_productive_run_is_healthy()
    print("Pipeline health tests passed.")
