from __future__ import annotations

from datetime import datetime, timedelta, timezone

import check_scraper_health as mod


NOW = datetime(2026, 8, 16, 9, 0, tzinfo=timezone.utc)


def base_article(**updates):
    article = {
        "title": "Fresh Rochdale transport update",
        "slug": "fresh-rochdale-transport-update",
        "status": "published",
        "category": "transport",
        "source_kind": "article",
        "first_published_at": (NOW - timedelta(hours=2)).isoformat(),
    }
    article.update(updates)
    return article


def test_normal_recent_journalism_is_frontpage_eligible() -> None:
    assert mod.is_frontpage_eligible_news_article(base_article(), NOW)


def test_thin_contact_directory_is_not_counted_as_available_news() -> None:
    article = base_article(
        title="Rochdale Borough Council Updates Contact Information for Estates and Asset Management Team",
        slug="rochdale-borough-council-updates-contact-information-for-estates-and-asset-manag",
        category="business",
        source_url="https://www.rochdale.gov.uk/contact-us/estates-asset-management-team-contact-details",
    )
    assert mod.is_eligible_news_article(article)
    assert not mod.is_frontpage_eligible_news_article(article, NOW)


def test_expired_today_deadline_is_not_counted_as_available_news() -> None:
    article = base_article(
        title="Tickets available until 6pm today",
        category="community",
        first_published_at="2026-08-15T12:00:00+00:00",
    )
    assert not mod.is_frontpage_eligible_news_article(article, NOW)


def test_expired_machine_sports_preview_is_not_counted_as_available_news() -> None:
    article = base_article(
        title="Rochdale face visitors today in match preview",
        category="sport",
        first_published_at=(NOW - timedelta(hours=9)).isoformat(),
    )
    assert not mod.is_frontpage_eligible_news_article(article, NOW)


def test_manual_editorial_contact_story_remains_eligible() -> None:
    article = base_article(
        title="Council contact service moves after office closure",
        category="business",
        source_kind="editorial",
        source_url="https://www.rochdale.gov.uk/contact-us/example-contact-details",
    )
    assert mod.is_frontpage_eligible_news_article(article, NOW)


if __name__ == "__main__":
    failures = 0
    for test in (
        test_normal_recent_journalism_is_frontpage_eligible,
        test_thin_contact_directory_is_not_counted_as_available_news,
        test_expired_today_deadline_is_not_counted_as_available_news,
        test_expired_machine_sports_preview_is_not_counted_as_available_news,
        test_manual_editorial_contact_story_remains_eligible,
    ):
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:
            failures += 1
            print(f"FAIL {test.__name__}: {exc}")
    raise SystemExit(1 if failures else 0)
