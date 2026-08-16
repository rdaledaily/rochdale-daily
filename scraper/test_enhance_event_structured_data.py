from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import enhance_event_structured_data as events


def sample_event(**overrides):
    row = {
        "title": "Pure 80's Festival 2026",
        "slug": "pure-80-s-festival-2026",
        "category": "events",
        "source_kind": "event",
        "status": "published",
        "event_start_at": "2026-09-12T12:00:00Z",
        "event_end_at": "2026-09-12T20:00:00Z",
        "event_location": "Littleborough Cricket Club, Denhurst Road, Littleborough OL15 9LD, UK",
        "excerpt": "A public 80s music festival in Littleborough.",
        "image_url": "assets/img/cards/pure-80-s-festival-2026-generated-card.jpg",
    }
    row.update(overrides)
    return row


def main() -> int:
    payload = events.event_payload(sample_event())
    assert payload is not None
    assert payload["@type"] == "Event"
    assert payload["name"] == "Pure 80's Festival 2026"
    # 12:00 UTC in September is 13:00 BST; emit the actual local offset.
    assert payload["startDate"] == "2026-09-12T13:00:00+01:00"
    assert payload["endDate"] == "2026-09-12T21:00:00+01:00"
    assert payload["location"]["@type"] == "Place"
    assert payload["location"]["address"]["@type"] == "PostalAddress"
    assert payload["location"]["address"]["addressCountry"] == "GB"
    assert payload["image"] == [
        "https://rochdaledaily.co.uk/assets/img/cards/pure-80-s-festival-2026-generated-card.jpg"
    ]

    # Missing required Google Event fields should be skipped rather than
    # publishing incomplete structured data.
    assert events.event_payload(sample_event(event_start_at="")) is None
    assert events.event_payload(sample_event(event_location="")) is None

    cancelled = events.event_payload(sample_event(event_status="cancelled"))
    assert cancelled is not None
    assert cancelled["eventStatus"] == "https://schema.org/EventCancelled"

    # Date-only events remain date-only; no fake midnight is invented.
    all_day = events.event_payload(sample_event(event_start_at="2026-09-12", event_end_at=""))
    assert all_day is not None
    assert all_day["startDate"] == "2026-09-12"
    assert "endDate" not in all_day

    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        pages = root / "articles"
        pages.mkdir()
        page = pages / "pure-80-s-festival-2026.html"
        page.write_text("<html><head><title>Event</title></head><body></body></html>", encoding="utf-8")
        data = root / "articles.json"
        data.write_text(json.dumps([sample_event()]), encoding="utf-8")

        eligible, changed = events.enhance_events(data, pages)
        assert eligible == 1
        assert changed == 1
        first = page.read_text(encoding="utf-8")
        assert first.count('id="rd-event-jsonld"') == 1
        assert '"@type":"Event"' in first
        assert '"startDate":"2026-09-12T13:00:00+01:00"' in first

        # Idempotence: a second run must not duplicate or alter the block.
        eligible, changed = events.enhance_events(data, pages)
        assert eligible == 1
        assert changed == 0
        assert page.read_text(encoding="utf-8") == first

    print("Event structured-data checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
