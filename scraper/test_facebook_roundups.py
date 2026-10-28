"""Regression checks for Facebook photo posts with the link in the first comment."""

from __future__ import annotations

import json
import os
from datetime import datetime as RealDatetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import post_facebook_article as fb

UTC = timezone.utc


def story(key: str, published: str, category: str = "community", **extra) -> dict:
    record = {
        "id": key,
        "slug": key,
        "title": f"Rochdale news item {key}",
        "excerpt": "A verified local update. It has a second sentence. And a third.",
        "published_at": published,
        "first_published_at": published,
        "status": "published",
        "category": category,
        "image_url": f"assets/img/cards/{key}.jpg",
        "image_status": "editorial-photo",
    }
    record.update(extra)
    return record


class FixedDateTime(RealDatetime):
    current = RealDatetime(2026, 10, 14, 11, 27, tzinfo=UTC)

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return cls.current.replace(tzinfo=None)
        return cls.current.astimezone(tz)


def run() -> None:
    # Grouped history still counts as one Page post.
    posts = {
        "a": {"facebook_post_id": "page_100", "posted_at": "2026-10-14T08:10:00Z"},
        "b": {"facebook_post_id": "page_100", "posted_at": "2026-10-14T08:10:00Z"},
    }
    assert len(fb.recent_post_times(posts)) == 1

    now = RealDatetime(2026, 10, 14, 11, 27, tzinfo=UTC)
    assert not fb.roundup_eligible(story("old", "2026-10-11T08:00:00Z"), 36, now)
    assert not fb.roundup_eligible(story("s", "2026-10-14T08:00:00Z", sponsored=True), 36, now)
    assert not fb.roundup_eligible(story("b", "2026-10-14T08:00:00Z", briefing_slot="morning"), 36, now)
    assert not fb.roundup_eligible(story("f", "2026-10-14T08:00:00Z", is_evergreen=True), 36, now)
    assert not fb.roundup_eligible(story("n", "2026-10-14T08:00:00Z", image_url="", img=""), 36, now)

    # The canonical link is the clean address, never the .html redirect.
    assert fb.canonical_url(story("x", "2026-10-14T08:00:00Z")) == "https://rochdaledaily.co.uk/articles/x"
    assert fb.image_url(story("x", "2026-10-14T08:00:00Z")) == "https://rochdaledaily.co.uk/assets/img/cards/x.jpg"

    # Caption: social headline first, two sentences of facts, no URL in the body.
    social = story("q", "2026-10-14T08:00:00Z",
                   social_headline="Heywood lollipop man forced to jump clear as two drivers ignore him")
    caption = fb.compose_caption(social)
    assert caption.startswith("Heywood lollipop man forced to jump clear"), caption
    assert "And a third." not in caption and "http" not in caption
    assert "Tell us what you think" in caption
    crime = story("c", "2026-10-14T08:00:00Z", category="crime")
    assert "Tell us what you think" not in fb.compose_caption(crime)
    # A social headline that breaks the rules falls back to the verified headline.
    shouty = story("z", "2026-10-14T08:00:00Z", social_headline="YOU WON'T BELIEVE WHAT HAPPENED IN ROCHDALE TODAY")
    assert fb.compose_caption(shouty).startswith("Rochdale news item z")

    # Ranking: a crime story outranks an older roadworks note; age halves pull every 12h.
    road = story("r", "2026-10-14T10:00:00Z", category="traffic")
    fresh_crime = story("k", "2026-10-14T09:00:00Z", category="crime")
    assert fb.score(fresh_crime, now) > fb.score(road, now)

    with TemporaryDirectory() as temp:
        base = Path(temp)
        article_file = base / "articles.json"
        state_file = base / "facebook_state.json"
        result_file = base / "facebook_result.json"
        article_file.write_text(json.dumps([
            story("a", "2026-10-14T08:00:00Z", category="traffic"),
            story("b", "2026-10-14T09:15:00Z", category="crime"),
        ]), encoding="utf-8")
        config = {
            "FACEBOOK_PAGE_ACCESS_TOKEN": "mock-token",
            "FACEBOOK_STATE_PATH": str(state_file),
            "FACEBOOK_RESULT_PATH": str(result_file),
            "FACEBOOK_MIN_POST_INTERVAL_MINUTES": "60",
            "FACEBOOK_SLOT_HOURS": "7,12,17,20",
            "FACEBOOK_MAX_POSTS_PER_DAY": "5",
        }
        with patch.dict(os.environ, config), \
             patch.object(fb, "ARTICLES_PATH", article_file), \
             patch.object(fb, "datetime", FixedDateTime), \
             patch.object(fb, "resolve_page_id", return_value="1234"), \
             patch.object(fb, "graph_photo_post", return_value="1234_999") as photo, \
             patch.object(fb, "graph_comment", return_value="999_1") as comment, \
             patch.object(fb, "graph_edit_caption") as edit:
            # 12:27 BST is the noon slot: the crime story wins it.
            FixedDateTime.current = RealDatetime(2026, 10, 14, 11, 27, tzinfo=UTC)
            assert fb.main() == 0
            result = json.loads(result_file.read_text(encoding="utf-8"))
            assert result["status"] == "posted" and result["article_keys"] == ["b"], result
            assert photo.call_args.args[2] == "https://rochdaledaily.co.uk/assets/img/cards/b.jpg"
            assert comment.call_args.args[0] == "1234_999"
            assert comment.call_args.args[2] == "Read the full story: https://rochdaledaily.co.uk/articles/b"
            assert result["link_route"] == "first-comment"
            assert edit.call_count == 0

            # Same slot again: no second post.
            FixedDateTime.current = RealDatetime(2026, 10, 14, 11, 59, tzinfo=UTC)
            assert fb.main() == 0
            assert photo.call_count == 1
            assert "cooldown" in json.loads(result_file.read_text())["reason"]

            # 14:27 BST is between slots: nothing posts.
            FixedDateTime.current = RealDatetime(2026, 10, 14, 13, 27, tzinfo=UTC)
            assert fb.main() == 0
            assert photo.call_count == 1
            assert "Outside the Facebook posting slots" in json.loads(result_file.read_text())["reason"]

            # 17:27 BST slot posts the remaining story.
            FixedDateTime.current = RealDatetime(2026, 10, 14, 16, 27, tzinfo=UTC)
            photo.return_value = "1234_1000"
            assert fb.main() == 0
            assert photo.call_count == 2
            state = json.loads(state_file.read_text(encoding="utf-8"))
            assert set(state["posted"]) == {"a", "b"}
            assert len(state["slots"]) == 2

            # Breaking news may go between slots in the day, never overnight.
            article_file.write_text(json.dumps([
                story("u", "2026-10-14T18:00:00Z", category="crime", breaking_news=True),
            ]))
            FixedDateTime.current = RealDatetime(2026, 10, 14, 18, 27, tzinfo=UTC)   # 19:27 BST
            photo.return_value = "1234_1001"
            assert fb.main() == 0
            assert photo.call_count == 3

            article_file.write_text(json.dumps([
                story("v", "2026-10-15T01:00:00Z", category="crime", breaking_news=True),
            ]))
            FixedDateTime.current = RealDatetime(2026, 10, 15, 1, 27, tzinfo=UTC)    # 02:27 BST
            assert fb.main() == 0
            assert photo.call_count == 3

            # A missing comment permission: link goes in the caption, state saved,
            # result tells the workflow to fail the run afterwards.
            FixedDateTime.current = RealDatetime(2026, 10, 15, 6, 27, tzinfo=UTC)    # 07:27 BST
            comment.side_effect = RuntimeError("no pages_manage_engagement")
            photo.return_value = "1234_1002"
            assert fb.main() == 0
            result = json.loads(result_file.read_text())
            assert result["link_route"] == "caption-after-comment-failed"
            assert "Read the full story: https://rochdaledaily.co.uk/articles/v" in edit.call_args.args[2]
            assert "v" in json.loads(state_file.read_text())["posted"]

    print("Facebook photo-post and link-comment tests passed.")


if __name__ == "__main__":
    run()
