from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

# Keep tests pinned to the production defaults even if a developer shell has overrides.
os.environ.pop("EVERGREEN_THIN_THRESHOLD", None)
os.environ.pop("EVERGREEN_LOOKBACK_HOURS", None)
os.environ.pop("EVERGREEN_COOLDOWN_HOURS", None)
os.environ.pop("EVERGREEN_START_HOUR", None)
os.environ.pop("EVERGREEN_END_HOUR", None)

import evergreen_fallback as evergreen


def article(
    when: datetime,
    *,
    area: str = "rochdale",
    category: str = "news",
    source_kind: str = "news",
    route: str = "scraper",
    evergreen_id: str = "",
    last_updated: datetime | None = None,
) -> dict:
    stamp = when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    row = {
        "title": "Test story",
        "status": "published",
        "area": area,
        "category": category,
        "source_kind": source_kind,
        "publication_route": route,
        "first_published_at": stamp,
        "published_at": stamp,
        "last_updated_at": (last_updated or when).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if evergreen_id:
        row["evergreen_id"] = evergreen_id
        row["is_evergreen"] = True
    return row


def main() -> int:
    # 12:00 UTC is 13:00 BST on 30 August 2026: inside the 09:00-20:00 UK window.
    now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)

    five = [article(now - timedelta(hours=i + 1)) for i in range(5)]
    decision = evergreen.evaluate_trigger(five, now)
    assert decision.should_publish is True
    assert decision.reason == "thin_news_supply"
    assert decision.qualifying_count == 5
    assert decision.threshold == 6

    six = [article(now - timedelta(hours=i + 1)) for i in range(6)]
    decision = evergreen.evaluate_trigger(six, now)
    assert decision.should_publish is False
    assert decision.reason == "normal_supply"
    assert decision.qualifying_count == 6

    # Events, weather and prior evergreen features do not pad the real-news count.
    mixed = five + [
        article(now - timedelta(hours=1), category="events", source_kind="event"),
        article(now - timedelta(hours=1), source_kind="weather", route="weather"),
        article(now - timedelta(hours=1), source_kind="evergreen", route="evergreen_fallback", evergreen_id="fairies"),
    ]
    assert evergreen.qualifying_story_count(mixed, now) == 5

    # Updating an old story today must not turn it into a new story for this metric.
    old_with_new_update = article(
        now - timedelta(days=3),
        last_updated=now - timedelta(minutes=10),
    )
    assert evergreen.is_qualifying_new_local_story(old_with_new_update, now) is False

    # A story outside Rochdale Daily's local area set is not counted.
    non_local = article(now - timedelta(hours=1), area="manchester")
    assert evergreen.is_qualifying_new_local_story(non_local, now) is False

    # Thin supply outside the publishing window does not trigger filler overnight.
    overnight = datetime(2026, 8, 30, 3, 0, tzinfo=timezone.utc)  # 04:00 BST
    decision = evergreen.evaluate_trigger([], overnight)
    assert decision.should_publish is False
    assert decision.reason == "outside_publishing_window"

    # A fallback inside the previous 24 hours blocks another one even when supply is thin.
    recent_evergreen = article(
        now - timedelta(hours=23),
        source_kind="evergreen",
        route="evergreen_fallback",
        evergreen_id="used-topic",
    )
    decision = evergreen.evaluate_trigger([recent_evergreen], now)
    assert decision.should_publish is False
    assert decision.reason == "evergreen_cooldown"

    # Exactly 24 hours old is outside the cooldown and permits a new fallback.
    old_evergreen = article(
        now - timedelta(hours=24),
        source_kind="evergreen",
        route="evergreen_fallback",
        evergreen_id="used-topic",
    )
    decision = evergreen.evaluate_trigger([old_evergreen], now)
    assert decision.should_publish is True

    topics = [{"id": "one"}, {"id": "two"}]
    chosen = evergreen.choose_topic(topics, [
        article(now - timedelta(days=2), source_kind="evergreen", route="evergreen_fallback", evergreen_id="one")
    ])
    assert chosen == {"id": "two"}
    assert evergreen.choose_topic(topics, [
        article(now - timedelta(days=2), source_kind="evergreen", route="evergreen_fallback", evergreen_id="one"),
        article(now - timedelta(days=1), source_kind="evergreen", route="evergreen_fallback", evergreen_id="two"),
    ]) is None

    print("Evergreen fallback trigger tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
