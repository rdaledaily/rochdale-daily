"""Regression checks for the newsroom front-page freshness policy."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import copy
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
from zoneinfo import ZoneInfo

import generate_newspaper_pages as newsroom
import enforce_frontpage_freshness as freshness
import enforce_live_homepage_window as window
import ensure_manual_frontpage as manual
from manual_articles import _absorb_scraped_match, _normalise, load_manual_article_records
import manual_articles as manual_source
from story_identity import merge_article_records


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
    # Even an edited live article retains its original age. An editor can
    # explicitly pin it for a bounded period if it warrants renewed coverage.
    assert not newsroom._keep_on_live_homepage(verified_live, after_deadline, cutoff)
    pinned = {**verified_live, "featured": True, "frontpage_until": (after_deadline + timedelta(hours=1)).isoformat()}
    assert newsroom._keep_on_live_homepage(pinned, after_deadline, cutoff)
    assert window.keep(pinned, after_deadline, cutoff)
    pinned["frontpage_until"] = (after_deadline - timedelta(seconds=1)).isoformat()
    assert not newsroom._keep_on_live_homepage(pinned, after_deadline, cutoff)
    assert not window.keep(pinned, after_deadline, cutoff)

    # Publishing unrelated stories must not reorder a still-fresh story just
    # because its edit, scrape or automatic LIVE fields change.
    stable = article(category="community", words=150, age_hours=8)
    stable_rank = newsroom._newsroom_rank(stable, now)
    pipeline_rank = newsroom.fp._article_rank(stable, now)
    touched = {**stable, "last_updated_at": now.isoformat(), "scraped_at": now.isoformat(), "is_ongoing": True}
    assert newsroom._newsroom_rank(touched, now) == stable_rank
    assert newsroom.fp._article_rank(touched, now) == pipeline_rank
    assert manual.latest_update(touched) == manual.first_published(stable)

    # Exercise the actual final guards repeatedly against archive records with
    # newly touched timestamps, including an automatically merged live story.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        feed, archive = root / "frontpage.json", root / "articles.json"
        fresh = article(category="community", words=150, age_hours=1)
        fresh.update(id="new", slug="new", title="New local community story")
        old = article(category="community", words=150, age_hours=72)
        old.update(id="old", slug="old", title="Older local community story", is_ongoing=True, live_story=True)
        rows = [fresh, old]
        archive.write_text(json.dumps(rows))
        for _ in range(3):
            edited = copy.deepcopy(old)
            edited.update(last_updated_at=now.isoformat(), scraped_at=now.isoformat(),
                          live_updates=[{"timestamp": now.isoformat(), "text": "Rewritten summary"}])
            feed.write_text(json.dumps({"articles": [edited, fresh]}))
            with patch.multiple(freshness, FRONTPAGE=feed, ARTICLES=archive, FRESH_HOURS=14), \
                 patch.multiple(window, FRONTPAGE=feed, FRESH_HOURS=14):
                freshness.main()
                window.main()
            assert [row["id"] for row in json.loads(feed.read_text())["articles"]] == ["new"]
        assert json.loads(archive.read_text()) == rows

    # Ingestion time is not a modification date, including for manual stories
    # that absorb attribution from an existing scrape.
    original = stable["published_at"]
    without_update = {k: v for k, v in stable.items() if k != "last_updated_at"}
    merged = merge_article_records(without_update, {**without_update, "scraped_at": now.isoformat()})
    assert freshness.parse_dt(merged["last_updated_at"]) == freshness.parse_dt(original)
    manual_record = {**stable, "id": "manual", "slug": "manual", "source_url": "https://example.test/a"}
    absorbed = _absorb_scraped_match(manual_record, {**without_update, "id": "scraped", "scraped_at": now.isoformat()})
    assert freshness.parse_dt(absorbed["last_updated_at"]) == freshness.parse_dt(original).replace(microsecond=0)

    # Reproduce the production bug: legacy manual source files without dates
    # used to receive now on every unrelated publish, overriding archive age.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source, archive = root / "manual.json", root / "articles.json"
        undated = {"id": "legacy", "slug": "legacy", "title": "Legacy editorial story", "body": "Original reporting."}
        original = "2026-10-12T20:28:42Z"
        source.write_text(json.dumps([undated]))
        archive.write_text(json.dumps([{**undated, "manual_article": True, "published_at": original}]))
        with patch.multiple(manual_source, MANUAL_ARTICLES_PATH=source, MANUAL_ARTICLES_DIR=root / "absent", ARTICLES_FEED_PATH=archive):
            for offset in (0, 1, 3):
                rows = load_manual_article_records(now + timedelta(days=offset))
                assert len(rows) == 1
                assert rows[0]["published_at"] == rows[0]["first_published_at"] == original
            archive.write_text("[]")
            assert load_manual_article_records(now) == []
        assert _normalise(undated, now) is None

    print("Newspaper freshness policy checks passed.")


if __name__ == "__main__":
    main()
