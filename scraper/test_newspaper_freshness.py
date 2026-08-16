"""Regression checks for the newsroom front-page freshness policy."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import generate_newspaper_pages as newsroom


def article(*, category: str, words: int, age_hours: int) -> dict:
    now = datetime.now(timezone.utc)
    published = now - timedelta(hours=age_hours)
    body = " ".join(["local"] * words)
    return {
        "title": "Rochdale local update",
        "excerpt": "Local verified update",
        "content_html": f"<p>{body}</p>",
        "category": category,
        "types": [category],
        "status": "published",
        "published_at": published.isoformat().replace("+00:00", "Z"),
        "first_published_at": published.isoformat().replace("+00:00", "Z"),
        "last_updated_at": published.isoformat().replace("+00:00", "Z"),
        "source_count": 1,
    }


def main() -> None:
    transport_brief = article(category="transport", words=65, age_hours=1)
    business_fragment = article(category="business", words=65, age_hours=1)
    older_long_transport = article(category="transport", words=240, age_hours=30)

    transport_brief["rewrite_quality_checked"] = True
    business_fragment["rewrite_quality_checked"] = True
    assert newsroom._newsroom_eligible(transport_brief)
    assert newsroom._newsroom_eligible(business_fragment)

    now = datetime.now(timezone.utc)
    assert newsroom._newsroom_rank(transport_brief, now) > newsroom._newsroom_rank(older_long_transport, now)

    # The page generator rewrites frontpage.json, so time-sensitive rules must
    # be owned here as a final invariant rather than only by an earlier guard.
    local = ZoneInfo("Europe/London")
    after_deadline = datetime(2026, 8, 15, 19, 5, tzinfo=local).astimezone(timezone.utc)
    cutoff = after_deadline - timedelta(hours=14)
    hornets_offer = article(category="sport", words=100, age_hours=2)
    hornets_offer.update({
        "title": "Early Bird Tickets Available for Rochdale Hornets Matches Until 6pm Today",
        "excerpt": "Supporters have until 6pm today to buy discounted tickets.",
        "source_kind": "article",
        "first_published_at": (after_deadline - timedelta(hours=2)).isoformat(),
        "published_at": (after_deadline - timedelta(hours=2)).isoformat(),
    })
    assert not newsroom._keep_on_live_homepage(hornets_offer, after_deadline, cutoff)

    stale_preview = article(category="sport", words=100, age_hours=9)
    stale_preview.update({
        "title": "Rochdale AFC faces Newport County today",
        "excerpt": "Supporters are advised to arrive early for kick-off.",
        "source_kind": "article",
        "first_published_at": (after_deadline - timedelta(hours=9)).isoformat(),
        "published_at": (after_deadline - timedelta(hours=9)).isoformat(),
    })
    assert not newsroom._keep_on_live_homepage(stale_preview, after_deadline, cutoff)

    editorial_deadline = dict(hornets_offer)
    editorial_deadline.update({"manual_article": True, "source_kind": "editorial"})
    assert newsroom._keep_on_live_homepage(editorial_deadline, after_deadline, cutoff)

    # Machine scraping may touch last_updated_at without adding a new verified
    # timeline entry. That must not make an old BREAKING/LIVE article current.
    stale_original = after_deadline - timedelta(days=2)
    old_machine_live = article(category="crime", words=120, age_hours=48)
    old_machine_live.update({
        "title": "Old automated breaking story",
        "source_kind": "aggregator_discovered_article",
        "live_story": True,
        "breaking_news": True,
        "is_ongoing": True,
        "first_published_at": stale_original.isoformat(),
        "published_at": stale_original.isoformat(),
        "last_updated_at": (after_deadline - timedelta(minutes=5)).isoformat(),
        "scraped_at": (after_deadline - timedelta(minutes=2)).isoformat(),
        "live_updates": [{"timestamp": stale_original.isoformat(), "text": "Original fact only."}],
    })
    assert not newsroom._keep_on_live_homepage(old_machine_live, after_deadline, cutoff)

    verified_live = dict(old_machine_live)
    verified_live["live_updates"] = [
        {"timestamp": stale_original.isoformat(), "text": "Original fact."},
        {"timestamp": (after_deadline - timedelta(minutes=15)).isoformat(), "text": "New verified development."},
    ]
    assert newsroom._keep_on_live_homepage(verified_live, after_deadline, cutoff)

    print("Newspaper freshness policy checks passed.")


if __name__ == "__main__":
    main()
