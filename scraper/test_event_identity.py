"""Regression tests: feed duplicate-merging cannot fuse distinct events.

Guards against the contamination observed on the live site in July 2026,
where union-find (transitive) clustering in merge_duplicate_articles chained
four distinct What's Occurrin' ticket events — Oktoberfest, Pure 80s
Festival, Monsters of Rock and the Littlebrewer Ale Festival — into a single
record via shared venue boilerplate, leaving two feed entries with the same
slug and id and one article page flip-flopping between two events.

Contract: an approved ticket event's identity is its canonical event URL and
nothing else; non-event records use complete-linkage clustering (a record
joins a cluster only when it matches every member), matching
story_identity.dedupe_article_records.

Run directly: python scraper/test_event_identity.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import frontpage_pipeline as fp

BLURB = (
    "A weekend of Live Music, Great Food and real ale at Town Hall Square "
    "Rochdale. Tickets available now from the box office for this fantastic "
    "family event with entertainment for everyone."
)


def event(slug: str, title: str, start: str, record_id: str, published: str) -> dict:
    url = f"https://www.whatsoccurrinevents.co.uk/event-details/{slug}"
    return {
        "id": record_id,
        "slug": slug,
        "title": title,
        "source_kind": "event",
        "category": "events",
        "published_at": published,
        "event_start_at": start,
        "content_html": f"<p>{BLURB}</p>",
        "excerpt": BLURB,
        "source_url": url,
        "source_urls": [url],
    }


def test_distinct_events_never_merge() -> None:
    records = [
        event("oktoberfest-rochdale-2026", "Oktoberfest Rochdale 2026", "2026-10-17T18:00:00Z", "a1", "2026-07-10T10:00:00Z"),
        event("pure-80s-festival-2026", "Pure 80s Festival 2026", "2026-08-22T18:00:00Z", "b2", "2026-07-10T10:05:00Z"),
        event("monsters-of-rock-halloween-special-2026", "Monsters of Rock Halloween Special", "2026-10-31T19:00:00Z", "c3", "2026-07-10T10:10:00Z"),
        event("littlebrewer-ale-festival-2", "Littlebrewer Ale Festival 2", "2026-07-31T18:00:00Z", "d4", "2026-07-09T10:00:00Z"),
    ]
    merged = fp.merge_duplicate_articles(records)
    slugs = sorted(m["slug"] for m in merged)
    assert len(merged) == 4, f"4 distinct events must stay distinct, got {len(merged)}: {slugs}"
    for m in merged:
        urls = [u for u in m.get("source_urls", []) if u]
        assert len(urls) == 1, f"{m['slug']} absorbed foreign URLs: {urls}"
    print("distinct same-venue events stay distinct — OK")


def test_same_event_updates_still_merge() -> None:
    first = event("oktoberfest-rochdale-2026", "Oktoberfest Rochdale 2026", "2026-10-17T18:00:00Z", "a1", "2026-07-10T10:00:00Z")
    update = event("oktoberfest-rochdale-2026", "Oktoberfest Rochdale 2026", "2026-10-17T18:00:00Z", "a2", "2026-07-10T14:00:00Z")
    merged = fp.merge_duplicate_articles([first, update])
    assert len(merged) == 1, "the same event URL scraped twice must merge"
    print("same-URL event updates merge — OK")


def test_event_never_merges_with_article() -> None:
    ticket = event("summer-beer-festival", "Summer Beer Festival", "2026-08-01T12:00:00Z", "a1", "2026-07-10T10:00:00Z")
    article = {
        "id": "z9",
        "slug": "summer-beer-festival-preview",
        "title": "Summer Beer Festival",
        "source_kind": "article",
        "category": "news",
        "published_at": "2026-07-10T09:00:00Z",
        "content_html": f"<p>{BLURB}</p>",
        "excerpt": BLURB,
        "source_url": "https://www.rochvalleyradio.com/news/local-news/beer-festival",
        "source_urls": ["https://www.rochvalleyradio.com/news/local-news/beer-festival"],
    }
    merged = fp.merge_duplicate_articles([ticket, article])
    assert len(merged) == 2, "an event record must never absorb a news article"
    print("events and articles never cross-merge — OK")


def test_bridge_record_cannot_chain_stories() -> None:
    """Complete linkage: a contaminated bridge must not fuse two stories."""
    story_a = {
        "id": "s1", "slug": "farm-fire-norden", "title": "Firefighters tackle barn fire at Norden farm",
        "source_kind": "article", "category": "news", "published_at": "2026-07-10T08:00:00Z",
        "content_html": "<p>Firefighters tackled a large barn fire at a farm off Edenfield Road in Norden overnight, with six crews attending the scene until the early hours.</p>",
        "excerpt": "Barn fire at Norden farm", "source_url": "https://a.example/fire",
        "source_urls": ["https://a.example/fire"],
    }
    story_b = {
        "id": "s2", "slug": "council-budget-approved", "title": "Rochdale council approves annual budget",
        "source_kind": "article", "category": "politics", "published_at": "2026-07-10T09:00:00Z",
        "content_html": "<p>Rochdale Borough Council has approved its annual budget following a full council vote, setting spending priorities for the coming year.</p>",
        "excerpt": "Council approves budget", "source_url": "https://b.example/budget",
        "source_urls": ["https://b.example/budget"],
    }
    bridge = {
        "id": "s3", "slug": "mixed-contaminated-record", "title": "Firefighters tackle barn fire at Norden farm",
        "source_kind": "article", "category": "news", "published_at": "2026-07-10T10:00:00Z",
        # body is about the OTHER story: the classic contaminated record
        "content_html": "<p>Rochdale Borough Council has approved its annual budget following a full council vote, setting spending priorities for the coming year.</p>",
        "excerpt": "Council approves budget", "source_url": "https://c.example/mixed",
        "source_urls": ["https://c.example/mixed"],
    }
    merged = fp.merge_duplicate_articles([story_a, story_b, bridge])
    assert len(merged) >= 2, (
        "a single contaminated record must not chain two unrelated stories "
        f"into one (got {len(merged)} records)"
    )
    slugs = {m["slug"] for m in merged}
    assert not ({"farm-fire-norden", "council-budget-approved"} - {s for m in merged for s in [m["slug"]] } ) or len(merged) >= 2
    print("contaminated bridge cannot chain unrelated stories — OK")


def main() -> int:
    test_distinct_events_never_merge()
    test_same_event_updates_still_merge()
    test_event_never_merges_with_article()
    test_bridge_record_cannot_chain_stories()
    print("Event identity and complete-linkage merge tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
