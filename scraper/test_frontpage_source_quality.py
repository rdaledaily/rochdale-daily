"""Regression checks for conservative front-page source quality rules."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import frontpage_source_quality as guard


def main() -> None:
    weak_result = {
        "id": "sport-1",
        "title": "Newport County Defeats Rochdale in EFL Season Opener",
        "excerpt": "Newport secured a victory against Rochdale.",
        "category": "sport",
        "source_count": 1,
        "source_name": "instagram.com",
        "source_url": "https://news.google.com/rss/articles/example",
        "status": "published",
    }
    assert guard.weak_single_source_sports_result(weak_result)

    # This represents a separately verified record. It deliberately has a
    # different identity: if it reused sport-1, the guard should correctly
    # propagate the exclusion to every copy of that same canonical record.
    verified_result = dict(weak_result)
    verified_result["id"] = "sport-verified"
    verified_result["source_count"] = 2
    assert not guard.weak_single_source_sports_result(verified_result)

    editorial_result = dict(weak_result)
    editorial_result.update({"manual_article": True, "source_kind": "editorial"})
    assert not guard.weak_single_source_sports_result(editorial_result)

    evergreen_support = {
        "id": "council-1",
        "title": "Rochdale Council Offers Support for Domestic Violence Victims",
        "excerpt": "The council provides information and support for residents.",
        "category": "community",
        "source_kind": "live_refresh",
        "source_url": "https://www.rochdale.gov.uk/domestic-violence-abuse",
        "status": "published",
    }
    assert guard.evergreen_live_refresh(evergreen_support)

    actual_change = dict(evergreen_support)
    actual_change["title"] = "Rochdale Council Announces Changes to Domestic Abuse Support This Week"
    assert not guard.evergreen_live_refresh(actual_change)

    council_news = dict(evergreen_support)
    council_news["source_url"] = "https://www.rochdale.gov.uk/news/article/123/example"
    assert not guard.evergreen_live_refresh(council_news)

    frontpage = {"articles": [dict(weak_result), dict(evergreen_support), dict(verified_result)]}
    archive = [dict(weak_result), dict(evergreen_support), dict(verified_result)]
    marked, removed = guard.apply(archive, frontpage)
    assert marked == 2
    assert removed == 2
    assert frontpage["count"] == 1
    assert frontpage["articles"][0]["source_count"] == 2
    assert archive[0]["exclude_from_frontpage"] is True
    assert archive[1]["exclude_from_frontpage"] is True

    # Quality enforcement must not leave a needless hole. If a weak current
    # story is removed and another genuinely fresh eligible article exists in
    # the archive reservoir, the guard should refill the slot immediately.
    now = datetime(2026, 8, 16, 11, 30, tzinfo=timezone.utc)
    weak_current = dict(weak_result)
    weak_current["published_at"] = (now - timedelta(hours=1)).isoformat()
    weak_current["first_published_at"] = weak_current["published_at"]
    fallback = {
        "id": "community-fresh",
        "title": "Volunteer Group Opens New Rochdale Community Session",
        "excerpt": "A new local session has opened for residents this morning.",
        "category": "community",
        "area": "rochdale",
        "source_kind": "article",
        "source_name": "Community organisation",
        "source_url": "https://example.org/rochdale-session",
        "source_count": 1,
        "status": "published",
        "published_at": (now - timedelta(hours=2)).isoformat(),
        "first_published_at": (now - timedelta(hours=2)).isoformat(),
    }
    refill_frontpage = {"articles": [dict(weak_current)]}
    refill_archive = [dict(weak_current), dict(fallback)]
    marked, removed = guard.apply(refill_archive, refill_frontpage, now=now)
    assert marked == 1
    assert removed == 1
    assert refill_frontpage["count"] == 1
    assert refill_frontpage["articles"][0]["id"] == "community-fresh"
    assert refill_frontpage["source_quality_guard"]["refilled_frontpage_records"] == 1

    print("Frontpage source-quality checks passed.")


if __name__ == "__main__":
    main()
