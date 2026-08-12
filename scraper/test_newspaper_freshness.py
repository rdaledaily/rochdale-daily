"""Regression checks for the newsroom front-page freshness policy."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

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

    assert newsroom._minimum_words(transport_brief) == 60
    assert newsroom._minimum_words(business_fragment) == 75
    assert newsroom._newsroom_eligible(transport_brief)
    assert not newsroom._newsroom_eligible(business_fragment)

    now = datetime.now(timezone.utc)
    assert newsroom._newsroom_rank(transport_brief, now) > newsroom._newsroom_rank(older_long_transport, now)

    print("Newspaper freshness policy checks passed.")


if __name__ == "__main__":
    main()
