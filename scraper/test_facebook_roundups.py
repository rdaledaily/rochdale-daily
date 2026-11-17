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

    # The second block adds detail or is left out (Sarah, 15 Nov 2026). The
    # e-bike post repeated the headline as its second line; it must now skip
    # the echo and take the facts from the body instead.
    ebike = story(
        "e", "2026-10-14T08:00:00Z", category="news",
        title="Warning issued over e-bikes and e-scooters ahead of Christmas",
        social_headline="Police warn against buying e-bikes and e-scooters this Christmas after tragic death of local teenager.",
        excerpt="Police warn about the dangers of illegal e-bikes and e-scooters following a tragic incident involving a local teenager.",
        content_html=(
            "<h2>What happened</h2><p>Police have issued a warning to residents about the dangers of "
            "purchasing e-bikes and e-scooters this Christmas, following the tragic death of a teenager.</p>"
            "<p>Jacob, 16, died eight days after an accident involving an e-scooter.</p>"
            "<p>The warning is part of Operation Hurricane, which targets anti-social riding.</p>"
        ),
    )
    caption = fb.compose_caption(ebike)
    blocks = caption.split("\n\n")
    assert len(blocks) == 3, caption
    assert "dangers of illegal" not in caption and "What happened" not in caption, caption
    assert blocks[1].startswith("Jacob, 16, died eight days"), caption
    assert "Operation Hurricane" in blocks[1], caption
    # Nothing new anywhere: headline and the pointer only, never a reworded repeat.
    echo_only = story(
        "o", "2026-10-14T08:00:00Z",
        title="Bus station toilets reopen in Rochdale",
        excerpt="The toilets at the Rochdale bus station have reopened.",
    )
    caption = fb.compose_caption(echo_only)
    assert caption.split("\n\n")[0] == "Bus station toilets reopen in Rochdale", caption
    assert "have reopened" not in caption and len(caption.split("\n\n")) == 2, caption
    assert fb.echoes("Police warn about the dangers of e-bikes", fb.content_words("Police warn against buying e-bikes"))
    assert not fb.echoes("Jacob, 16, died eight days after the crash on Bury Road.", fb.content_words("Teenager dies after e-scooter crash"))

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

    # 7 Nov 2026 (editor): any real photo posts, stock included; a crime or
    # police story is never held back and uses the police photo if on a card;
    # only a non-crime story on a beige card waits.
    feed = [
        {"image_url": "assets/img/cards/abc-place-generated-card.jpg", "image_status": "place-generated-card"},
        *[{"image_url": "assets/img/cards/police.jpg", "image_status": "standard-police-image", "category": "crime"}] * 8,
        {"image_url": "assets/img/cards/warwick-mill.jpg", "image_status": "source-photo-cached"},
    ]
    usage = fb.image_usage(feed)
    assert not fb.has_story_photo(feed[0], usage)
    assert fb.has_story_photo(feed[1], usage)
    assert fb.has_story_photo(feed[-1], usage)
    crime_on_card = dict(feed[0], category="crime")
    assert fb.has_story_photo(crime_on_card, usage)
    assert fb.post_photo(crime_on_card) == "https://rochdaledaily.co.uk/assets/img/cards/police.jpg"
    assert fb.post_photo(feed[-1]).endswith("/assets/img/cards/warwick-mill.jpg")
    assert fb.post_photo(feed[0]) == ""
    # story_image.compose_story_card's area-category card is a card, not a
    # photo: it waits, and a crime story on one gets the police photo.
    area_card = {"image_url": "assets/img/cards/heywood-area-category-card.jpg", "image_status": "area-category-card"}
    assert not fb.has_story_photo(area_card, usage)
    assert fb.post_photo(dict(area_card, category="crime")).endswith("/assets/img/cards/police.jpg")
    renamed = {"image_url": "assets/img/cards/x.jpg", "image_status": "place-generated-card"}
    assert not fb.has_story_photo(renamed, usage)            # status alone marks a card

    print("Facebook photo-post and link-comment tests passed.")


def as_published() -> None:
    """Editor, 17 Nov 2026: post each story as it goes live, not in six slots."""
    with TemporaryDirectory() as temp:
        base = Path(temp)
        article_file = base / "articles.json"
        state_file = base / "facebook_state.json"
        result_file = base / "facebook_result.json"
        article_file.write_text(json.dumps([
            story("older", "2026-10-14T08:00:00Z", category="crime"),
            story("newer", "2026-10-14T13:05:00Z", category="community"),
        ]), encoding="utf-8")
        config = {
            "FACEBOOK_PAGE_ACCESS_TOKEN": "mock-token",
            "FACEBOOK_STATE_PATH": str(state_file),
            "FACEBOOK_RESULT_PATH": str(result_file),
            "FACEBOOK_SCHEDULE": "as-published",
            "FACEBOOK_POSTING_HOURS": "7-22",
            "FACEBOOK_MIN_POST_INTERVAL_MINUTES": "20",
            "FACEBOOK_MAX_POSTS_PER_DAY": "3",
            "FACEBOOK_SLOT_HOURS": "7,12",   # ignored in this mode
        }
        with patch.dict(os.environ, config), \
             patch.object(fb, "ARTICLES_PATH", article_file), \
             patch.object(fb, "datetime", FixedDateTime), \
             patch.object(fb, "resolve_page_id", return_value="1234"), \
             patch.object(fb, "graph_photo_post", return_value="1234_1") as photo, \
             patch.object(fb, "graph_comment", return_value="1_1"), \
             patch.object(fb, "graph_edit_caption"):
            # 14:17 BST is not a slot hour: as-published still posts, newest first.
            FixedDateTime.current = RealDatetime(2026, 10, 14, 13, 17, tzinfo=UTC)
            assert fb.main() == 0
            result = json.loads(result_file.read_text())
            assert result["status"] == "posted" and result["article_keys"] == ["newer"], result
            assert result["slot"].endswith("-live"), result
            state = json.loads(state_file.read_text())
            assert state["posted"]["newer"]["lane"] == "as-published"
            assert not state.get("slots"), "as-published posts do not use up slots"

            # Ten minutes later: the 20-minute gap holds the next one.
            FixedDateTime.current = RealDatetime(2026, 10, 14, 13, 27, tzinfo=UTC)
            assert fb.main() == 0
            assert photo.call_count == 1
            assert "cooldown" in json.loads(result_file.read_text())["reason"]

            # Twenty minutes after the first post the older story goes.
            FixedDateTime.current = RealDatetime(2026, 10, 14, 13, 38, tzinfo=UTC)
            photo.return_value = "1234_2"
            assert fb.main() == 0
            assert photo.call_count == 2
            assert json.loads(result_file.read_text())["article_keys"] == ["older"]

            # A story going live overnight waits for 07:00 UK time.
            article_file.write_text(json.dumps([story("night", "2026-10-15T00:30:00Z")]))
            FixedDateTime.current = RealDatetime(2026, 10, 15, 0, 47, tzinfo=UTC)    # 01:47 BST
            assert fb.main() == 0
            assert photo.call_count == 2
            assert "Outside Facebook posting hours" in json.loads(result_file.read_text())["reason"]
            FixedDateTime.current = RealDatetime(2026, 10, 15, 6, 7, tzinfo=UTC)     # 07:07 BST
            photo.return_value = "1234_3"
            assert fb.main() == 0
            assert photo.call_count == 3

            # The daily ceiling still applies (3 here; posts on the 14th do not count on the 15th).
            article_file.write_text(json.dumps([
                story("m1", "2026-10-15T06:30:00Z"), story("m2", "2026-10-15T06:40:00Z"),
                story("m3", "2026-10-15T06:50:00Z"),
            ]))
            for minute, post_id in ((30, "1234_4"), (55, "1234_5")):
                FixedDateTime.current = RealDatetime(2026, 10, 15, 6, minute, tzinfo=UTC)
                photo.return_value = post_id
                assert fb.main() == 0
            assert photo.call_count == 5
            FixedDateTime.current = RealDatetime(2026, 10, 15, 7, 20, tzinfo=UTC)
            assert fb.main() == 0
            assert photo.call_count == 5
            assert "Daily Facebook limit reached (3 posts)" in json.loads(result_file.read_text())["reason"]

    # Breaking news from the last three hours jumps the queue; older breaking does not.
    now = RealDatetime(2026, 10, 14, 13, 0, tzinfo=UTC)
    rows = [
        story("plain-new", "2026-10-14T12:50:00Z"),
        story("breaking", "2026-10-14T11:00:00Z", breaking_news=True),
        story("stale-breaking", "2026-10-14T08:00:00Z", breaking_news=True),
    ]
    assert [r["id"] for r in fb.as_published_order(rows, now)] == ["breaking", "plain-new", "stale-breaking"]
    with patch.dict(os.environ, {"FACEBOOK_SCHEDULE": "slots"}):
        assert fb.schedule_mode() == "slots"
    with patch.dict(os.environ, {"FACEBOOK_SCHEDULE": "as-published"}):
        assert fb.schedule_mode() == "as-published"
    with patch.dict(os.environ, {"FACEBOOK_POSTING_HOURS": "nonsense"}):
        assert fb.posting_hours() == (7, 22)
    print("Facebook as-published tests passed.")


if __name__ == "__main__":
    run()
    as_published()
