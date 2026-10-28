"""The live page format (live_format.py)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import live_format as lf

NOW = datetime(2026, 10, 28, 16, 0, tzinfo=timezone.utc)


def story(**extra) -> dict:
    base = {"slug": "m62-crash", "title": "M62 closed after crash near Milnrow", "excerpt": "Westbound shut."}
    base.update(extra)
    return base


def run() -> None:
    # One seeded line is not live coverage: the 28 Oct 2026 failure.
    single = story(live_updates=[{"timestamp": "2026-10-28T15:00:00Z", "text": "Seventeen arrests were made."}])
    state = lf.live_state(single, NOW)
    assert not state["is_live"] and not state["has_timeline"]
    assert lf.render_block(single, NOW) == ""

    # Two real updates inside six hours: live, newest first, escaped.
    two = story(live_updates=[
        {"timestamp": "2026-10-28T14:00:00Z", "text": "Police closed the westbound <b>carriageway</b>."},
        {"timestamp": "2026-10-28T15:30:00Z", "text": "One lane has reopened.", "title": "Lane reopens",
         "image_url": "javascript:alert(1)", "source_url": "https://www.gmp.police.uk/x"},
    ], key_points=["Westbound closed", "Air ambulance attended"])
    state = lf.live_state(two, NOW)
    assert state["is_live"] and state["label"] == "LIVE"
    html = lf.render_block(two, NOW)
    assert html.index("One lane has reopened") < html.index("Police closed the westbound")
    assert "<b>" not in html and "javascript:" not in html
    assert "What we know so far" in html and "15:30 GMT" in html and 'data-live="1"' in html

    # Older than six hours: kept as "As it happened", schema gets an end time.
    later = datetime(2026, 10, 28, 23, 0, tzinfo=timezone.utc)
    assert lf.live_state(two, later)["label"] == "As it happened"
    ld = lf.json_ld(two, "https://rochdaledaily.co.uk/articles/m62-crash", {"@type": "NewsMediaOrganization"}, later)
    assert ld["@type"] == "LiveBlogPosting" and "coverageEndTime" in ld
    assert ld["liveBlogUpdate"][0]["datePublished"] == "2026-10-28T15:30:00Z"
    json.dumps(ld)
    live_ld = lf.json_ld(two, "https://rochdaledaily.co.uk/articles/m62-crash", {}, NOW)
    assert "coverageEndTime" not in live_ld

    # A story started from the desk is live from its first update.
    desk = lf.fold_desk(story(), {"updates": [{"id": "a1", "timestamp": "2026-10-28T15:55:00Z", "text": "Crews at the scene."}],
                                  "key_points": ["Crews at the scene"], "ended_at": ""})
    assert lf.live_state(desk, NOW)["is_live"]
    ended = lf.fold_desk(story(), {"updates": [{"id": "a1", "timestamp": "2026-10-28T15:55:00Z", "text": "Crews at the scene."}],
                                   "ended_at": "2026-10-28T15:58:00Z"})
    assert not lf.live_state(ended, NOW)["is_live"]

    # A timeline baked into the body by an older run is removed.
    body = '<section class="live-update-timeline"><h2>BREAKING NEWS</h2></section><p>Body.</p>'
    assert lf.strip_baked_timeline(body) == "<p>Body.</p>"

    # Network failure while folding the desk is silent: pages still build.
    assert lf.fetch_desk_updates("http://127.0.0.1:9", timeout=0.5) == {}
    print("Live format tests passed.")


if __name__ == "__main__":
    run()
