"""Regression checks for individual hourly Facebook Page updates."""

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
    # Legacy grouped history still counts as a single successful Page post.
    posts = {
        "a": {"facebook_post_id": "page_100", "posted_at": "2026-10-14T08:10:00Z"},
        "b": {"facebook_post_id": "page_100", "posted_at": "2026-10-14T08:10:00Z"},
    }
    assert len(fb.recent_post_times(posts)) == 1

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
            "FACEBOOK_MIN_POST_INTERVAL_MINUTES": "60",
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
            assert result["status"] == "posted" and result["article_count"] == 1, result
            published_state = json.loads(state_file.read_text(encoding="utf-8"))
            assert len(published_state["roundups"]) == 1
            assert len(published_state["posted"]) == 1
            assert set(v["facebook_post_id"] for v in published_state["posted"].values()) == {"1234_999"}
            assert publish.call_count == 1
            assert publish.call_args.args[3] == "https://rochdaledaily.co.uk/articles/b.html"
            assert "Rochdale news item b" in publish.call_args.args[2]
            assert "Rochdale news item a" not in publish.call_args.args[2]

            assert fb.main() == 0
            assert json.loads(result_file.read_text(encoding="utf-8"))["status"] == "idle"
            assert publish.call_count == 1

            # A new run before the hour cannot post the next story.
            FixedDateTime.current = RealDatetime(2026, 10, 14, 9, 59, tzinfo=utc)
            assert fb.main() == 0
            assert publish.call_count == 1
            # At one hour, the remaining story can publish on its own.
            FixedDateTime.current = RealDatetime(2026, 10, 14, 10, 0, tzinfo=utc)
            publish.return_value = "1234_1000"
            assert fb.main() == 0
            assert publish.call_count == 2
            assert publish.call_args.args[3].endswith("/a.html")
            state = json.loads(state_file.read_text(encoding="utf-8"))
            assert set(state["posted"]) == {"a", "b"}
            # Overnight posting is allowed, but an empty queue is never recycled.
            FixedDateTime.current = RealDatetime(2026, 10, 14, 23, 0, tzinfo=utc)
            assert fb.main() == 0
            assert publish.call_count == 2
            assert json.loads(result_file.read_text())["status"] == "idle"
            article_file.write_text(json.dumps([story("c", "2026-10-14T22:00:00Z")]))
            publish.return_value = "1234_1001"
            assert fb.main() == 0
            assert publish.call_count == 3
            assert publish.call_args.args[3].endswith("/c.html")

    print("Facebook individual hourly posting tests passed.")


if __name__ == "__main__":
    run()
