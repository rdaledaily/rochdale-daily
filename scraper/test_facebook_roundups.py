"""Regression checks for restrained, grouped Facebook Page updates."""

from __future__ import annotations

import json
import os
from datetime import datetime as RealDatetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import post_facebook_article as fb


def story(key: str, published: str) -> dict:
    return {
        "id": key,
        "slug": key,
        "title": f"Rochdale news item {key}",
        "excerpt": "A verified local update.",
        "published_at": published,
        "first_published_at": published,
        "status": "published",
        "category": "community",
    }


class FixedDateTime(RealDatetime):
    current = RealDatetime(2026, 10, 14, 9, 0, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return cls.current.replace(tzinfo=None)
        return cls.current.astimezone(tz)


def run() -> None:
    utc = timezone.utc
    assert fb.roundup_slot(RealDatetime(2026, 7, 14, 7, 30, tzinfo=utc))[0].endswith(":morning")
    assert fb.roundup_slot(RealDatetime(2026, 1, 14, 7, 30, tzinfo=utc)) is None
    assert fb.roundup_slot(RealDatetime(2026, 1, 14, 12, 30, tzinfo=utc))[0].endswith(":lunchtime")
    assert fb.roundup_slot(RealDatetime(2026, 10, 14, 22, 30, tzinfo=utc))[0].endswith(":evening")
    assert fb.roundup_slot(RealDatetime(2026, 10, 14, 23, 30, tzinfo=utc)) is None

    posts = {
        "a": {"facebook_post_id": "page_100", "posted_at": "2026-10-14T08:10:00Z"},
        "b": {"facebook_post_id": "page_100", "posted_at": "2026-10-14T08:10:00Z"},
        "c": {"facebook_post_id": "page_101", "posted_at": "2026-10-14T09:20:00Z"},
    }
    assert fb.roundup_posts_today(posts, RealDatetime(2026, 10, 14, 9, 30, tzinfo=utc)) == 2
    assert len(fb.recent_post_times(posts)) == 2

    caption = fb.format_roundup(
        [story("alpha", "2026-10-14T08:00:00Z"),
         story("beta", "2026-10-14T08:00:00Z")],
        "Morning news from Rochdale Daily",
    )
    assert caption.count("• ") == 2, caption
    assert caption.count("rochdaledaily.co.uk") == 1, caption
    assert "Morning news" in caption

    older = story("old", "2026-10-11T08:00:00Z")
    assert not fb.roundup_eligible(older, 48)
    sponsored = story("sponsor", "2026-10-14T08:00:00Z")
    sponsored["sponsored"] = True
    assert not fb.roundup_eligible(sponsored, 48)
    briefing = story("briefing", "2026-10-14T08:00:00Z")
    briefing["briefing_slot"] = "morning"
    assert not fb.roundup_eligible(briefing, 48)

    with TemporaryDirectory() as temp:
        base = Path(temp)
        article_file = base / "articles.json"
        state_file = base / "facebook_state.json"
        result_file = base / "facebook_result.json"
        article_file.write_text(
            json.dumps([story("a", "2026-10-14T08:00:00Z"),
                        story("b", "2026-10-14T08:15:00Z")]),
            encoding="utf-8",
        )
        config = {
            "FACEBOOK_PAGE_ACCESS_TOKEN": "mock-token",
            "FACEBOOK_STATE_PATH": str(state_file),
            "FACEBOOK_RESULT_PATH": str(result_file),
            "FACEBOOK_MIN_POST_INTERVAL_MINUTES": "0",
            "FACEBOOK_MAX_POSTS_24H": "0",
            "FACEBOOK_MIN_ARTICLES_PER_ROUNDUP": "2",
            "FACEBOOK_MAX_ARTICLES_PER_ROUNDUP": "5",
        }
        with patch.dict(os.environ, config), \
             patch.object(fb, "ARTICLES_PATH", article_file), \
             patch.object(fb, "datetime", FixedDateTime), \
             patch.object(fb, "resolve_page_id", return_value="1234"), \
             patch.object(fb, "graph_post", return_value="1234_999") as publish:
            FixedDateTime.current = RealDatetime(2026, 10, 14, 9, 0, tzinfo=utc)
            assert fb.main() == 0
            result = json.loads(result_file.read_text(encoding="utf-8"))
            assert result["status"] == "posted" and result["article_count"] == 2, result
            published_state = json.loads(state_file.read_text(encoding="utf-8"))
            assert len(published_state["roundups"]) == 1
            assert len(published_state["posted"]) == 2
            assert set(v["facebook_post_id"] for v in published_state["posted"].values()) == {"1234_999"}
            assert publish.call_count == 1
            assert publish.call_args.args[3] == "https://rochdaledaily.co.uk/"

            assert fb.main() == 0
            assert json.loads(result_file.read_text(encoding="utf-8"))["status"] == "idle"
            assert publish.call_count == 1

            # Existing post history is preserved; two new stories are bundled.
            remaining = [story("c", "2026-10-14T11:00:00Z"),
                         story("d", "2026-10-14T11:20:00Z")]
            article_file.write_text(json.dumps(remaining + [
                story("a", "2026-10-14T08:00:00Z"), story("b", "2026-10-14T08:15:00Z")
            ]), encoding="utf-8")
            FixedDateTime.current = RealDatetime(2026, 10, 14, 12, 20, tzinfo=utc)
            assert fb.main() == 0
            state = json.loads(state_file.read_text(encoding="utf-8"))
            assert len(state["roundups"]) == 2
            assert len(state["posted"]) == 4
            assert publish.call_count == 2

    print("Facebook grouped roundup tests passed.")


if __name__ == "__main__":
    run()
