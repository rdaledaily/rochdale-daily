"""Briefings never absorb real stories; distinct events never merge.

16 Nov 2026: the 12 November Morning Briefing absorbed the Springhill Hospice
attacks story through manual_articles' fold-in (which calls same_story), and
the push-race merge (dedupe_article_records) folded two What's On events into
other events at the same venue. Both losses were silent.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from story_identity import dedupe_article_records, same_story  # noqa: E402

BRIEFING = {
    "id": "briefing-morning-briefing-12-november-2026",
    "slug": "morning-briefing-12-november-2026",
    "title": "Morning Briefing: Thursday 12 November 2026",
    "category": "news",
    "manual_article": True,
    "editorial_lock": True,
    "published_at": "2026-11-12T09:29:17Z",
    "content_html": (
        "<p>9 new stories.</p><ul><li>Police investigate attacks on Springhill "
        "Hospice charity shops in Rochdale</li><li>Man dies in flat fire in "
        "Rochdale</li><li>Fire festival returns to Rochdale</li></ul>"
    ),
}

STORY = {
    "id": "hospice01",
    "slug": "police-investigate-attacks-on-springhill-hospice-shops",
    "title": "Police investigate attacks on Springhill Hospice charity shops in Rochdale",
    "category": "crime",
    "published_at": "2026-11-12T10:00:00Z",
    "source_url": "https://www.rochdaletimes.co.uk/police-probe-horrific-spate-of-attacks-against-hospice/",
    "content_html": "<p>Police are investigating attacks on Springhill Hospice charity shops in Rochdale.</p>",
}


def event(slug, title, url):
    return {
        "id": slug, "slug": slug, "title": title, "category": "events",
        "source_kind": "event", "source_url": url,
        "published_at": "2026-11-16T09:00:00Z",
        "content_html": "<p>Live music, great food and drink at the Flying Horse, Rochdale.</p>",
    }


def test_same_story_never_matches_a_briefing_to_a_story():
    assert not same_story(BRIEFING, STORY)
    assert not same_story(STORY, BRIEFING)


def test_a_briefing_is_still_the_same_as_itself():
    assert same_story(BRIEFING, dict(BRIEFING))


def test_dedupe_keeps_story_and_briefing_apart():
    out = dedupe_article_records([BRIEFING, STORY])
    assert {r["slug"] for r in out} == {BRIEFING["slug"], STORY["slug"]}


def test_distinct_events_survive_the_push_race_merge():
    # The four real records merge_feeds lost two of on 16 Nov 2026, with
    # remote and local copies of each as in a push race.
    import json
    real = json.loads((Path(__file__).resolve().parent / "test_event_merge_16nov_fixture.json").read_text(encoding="utf-8"))
    out = dedupe_article_records(real + [dict(r) for r in real])
    assert sorted(r["slug"] for r in out) == sorted(r["slug"] for r in real)


def test_the_same_event_page_still_merges():
    a = event("pure-80-s-festival-2027", "Pure 80s Festival 2027",
              "https://www.whatsoccurrinevents.co.uk/event-details/pure-80s-festival-2027")
    b = dict(a, id="other-id", slug="pure-80s-festival-2027-copy")
    assert len(dedupe_article_records([a, b])) == 1


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok  ", name)
    print("all briefing/event identity tests passed")
