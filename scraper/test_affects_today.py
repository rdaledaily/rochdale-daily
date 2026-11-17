"""Stories that affect readers today post to Facebook immediately (editor, 17 Nov 2026).

Headlines below are real Rochdale Daily headlines from the archive.
Run: PYTHONPATH=scraper python scraper/test_affects_today.py
"""
from __future__ import annotations

import json
import os
from datetime import datetime as RealDatetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import post_facebook_article as fb
from affects_today import today_kind

UTC = timezone.utc

TODAY = {
    "Power outage affects over 60 properties in Heywood due to underground cable incident": "utility-outage",
    "Norden residents report being without water since Friday morning as outage continues": "utility-outage",
    "M62 closed near Milnrow after lorry hits central reservation": "traffic-incident",
    "M62 Westbound Closed Between Junctions 22 and 21 After Multi-Vehicle Collision": "traffic-incident",
    "No Metrolink service between Rochdale Town Centre and Freehold after collision at Westwood": "traffic-incident",
    "Tram Services Suspended Between Shaw and Rochdale Following Police Incident": "traffic-incident",
    "Crash Closes Heywood Old Road in Middleton": "traffic-incident",
    "Urgent Appeal for Missing 16-Year-Old Girl Last Seen in Norden, Rochdale": "missing-person",
    "Police Concerned for Missing Woman from Littleborough": "missing-person",
    "URGENT: Police appeal to find missing 10-year-old Rayah in Rochdale": "missing-person",
    "St Cuthbert’s RC High School closes following bomb threat": "school-closure",
    "Weather warning issued for Rochdale as Storm Boelo approaches": "public-warning",
    "Students Evacuated from Wardle Academy After Handheld Fan Overheats": "public-warning",
}
NOT_TODAY = [
    "Clover Hall Crescent, roadworks in Rochdale from 17 November 2026",       # planned works
    "Road Closure on Baillie Street East Scheduled for 1 October 2026",
    "Meeting Requested to Discuss Hopwood Triangle Road Closure",
    "Teenager jailed for fatal crash in Middleton after teaching himself to drive",  # court
    "Inquest Finds Drink-Driving Contributed to Heywood Man's Fatal Crash",
    "Man Charged with Dangerous Driving After Collision in Littleborough",
    "Teen Arrested Following Motorbike Crash on Ashfield Road",
    "Missing Cat Gene Last Seen in Falinge Area of Rochdale",                 # pets
    "Search Underway for Missing Dog in Castleton",
    "Police Search for Woman After Human Tissue Found in Rochdale Street",    # not a missing person
    "Traffic Incident Reported at Caliber Collision in Middleton",           # a business
    "Secondary school applications close on 31 October: what Rochdale parents need to know",
    "Rochdale Leisure Centre small pool closed for repairs",
    "Seven Sisters to be demolished as RBH plans around 600 new homes at College Bank",
]


def story(key: str, title: str, published: str, **extra) -> dict:
    record = {
        "id": key, "slug": key, "title": title,
        "excerpt": "A verified local update with a detail the headline lacks.",
        "published_at": published, "first_published_at": published,
        "status": "published", "category": "community",
        "image_url": f"assets/img/cards/{key}.jpg", "image_status": "editorial-photo",
    }
    record.update(extra)
    return record


class FixedDateTime(RealDatetime):
    current = RealDatetime(2026, 11, 17, 9, 50, tzinfo=UTC)

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return cls.current.replace(tzinfo=None)
        return cls.current.astimezone(tz)


def run() -> None:
    for title, kind in TODAY.items():
        assert today_kind({"title": title}) == kind, (title, today_kind({"title": title}))
    for title in NOT_TODAY:
        assert today_kind({"title": title}) == "", (title, today_kind({"title": title}))

    with TemporaryDirectory() as temp:
        base = Path(temp)
        article_file = base / "articles.json"
        state_file = base / "state.json"
        result_file = base / "result.json"
        config = {
            "FACEBOOK_PAGE_ACCESS_TOKEN": "mock-token",
            "FACEBOOK_STATE_PATH": str(state_file),
            "FACEBOOK_RESULT_PATH": str(result_file),
            "FACEBOOK_MIN_POST_INTERVAL_MINUTES": "60",
            "FACEBOOK_SLOT_HOURS": "7,12,15,17,20,22",
            "FACEBOOK_MAX_POSTS_PER_DAY": "7",
        }
        # The real 17 Nov case: the 07:00 slot went to roadworks at 07:12; the
        # Heywood power cut went live at 07:27 on a beige place card and was
        # still waiting at 09:50.
        power_cut = story(
            "p", "Power outage affects over 60 properties in Heywood due to underground cable incident",
            "2026-11-17T07:27:14Z", category="business",
            image_url="assets/img/cards/08f8052744fd-place-generated-card.jpg",
            image_status="place-generated-card",
        )
        ordinary = story("o", "Rochdale Business Awards 2026 winners announced", "2026-11-17T08:00:00Z")
        state_file.write_text(json.dumps({"posted": {"r": {
            "facebook_post_id": "1_1", "posted_at": "2026-11-17T07:12:58Z", "slot": "2026-11-17:07",
            "title": "Clover Hall Crescent, roadworks", "url": "https://rochdaledaily.co.uk/articles/r",
        }}, "slots": {"2026-11-17:07": {}}}))
        article_file.write_text(json.dumps([power_cut, ordinary]))

        with patch.dict(os.environ, config), \
             patch.object(fb, "ARTICLES_PATH", article_file), \
             patch.object(fb, "datetime", FixedDateTime), \
             patch.object(fb, "resolve_page_id", return_value="1234"), \
             patch.object(fb, "graph_photo_post", return_value="1234_2") as photo, \
             patch.object(fb, "graph_comment", return_value="2_1"), \
             patch.object(fb, "graph_edit_caption"):
            # 09:50 is between slots: the power cut posts anyway, on the red
            # Incident card; the ordinary story waits for 12:00.
            assert fb.main() == 0
            result = json.loads(result_file.read_text())
            assert result["status"] == "posted" and result["article_keys"] == ["p"], result
            assert photo.call_count == 1
            assert photo.call_args.args[2] == "https://rochdaledaily.co.uk/assets/img/cards/incident-card.jpg"
            assert result["today_posts"][0]["kind"] == "utility-outage"
            state = json.loads(state_file.read_text())
            assert state["posted"]["p"]["lane"] == "today"
            assert set(state["slots"]) == {"2026-11-17:07"}, "an immediate post must not use up a slot"

            # Overnight, and over the daily limit and inside the cooldown: a
            # missing child still posts at once. Two headlines about the same
            # appeal are one post.
            missing = story("m", "URGENT: Police appeal to find missing 10-year-old Rayah in Rochdale",
                            "2026-11-18T02:05:00Z", category="crime", police_matter=True,
                            image_url="", img="")
            repeat = story("m2", "Police appeal to find missing 10-year-old Rayah last seen in Rochdale",
                           "2026-11-18T02:10:00Z", category="crime")
            outage = story("w", "Norden residents report being without water since Friday morning",
                           "2026-11-18T02:12:00Z")
            article_file.write_text(json.dumps([power_cut, ordinary, missing, repeat, outage]))
            st = json.loads(state_file.read_text())
            for i in range(7):  # seven scheduled posts already today, last one 5 minutes ago
                st["posted"][f"s{i}"] = {"facebook_post_id": f"9_{i}", "posted_at": "2026-11-18T02:15:00Z",
                                         "url": f"https://rochdaledaily.co.uk/articles/s{i}"}
            state_file.write_text(json.dumps(st))
            FixedDateTime.current = RealDatetime(2026, 11, 18, 2, 20, tzinfo=UTC)
            photo.return_value = "1234_3"
            assert fb.main() == 0
            result = json.loads(result_file.read_text())
            assert result["article_keys"] == ["m", "w"], result
            assert photo.call_args_list[1].args[2] == "https://rochdaledaily.co.uk/assets/img/cards/police.jpg"

            # Nothing left that affects today: the ordinary story still obeys the slots.
            assert fb.main() == 0
            assert photo.call_count == 3
            assert json.loads(result_file.read_text())["status"] == "idle"

            # A story that affects today but went live more than 12 hours ago
            # has been overtaken; it does not jump the queue.
            stale = story("x", "Crash Closes Heywood Old Road in Middleton", "2026-11-17T12:00:00Z")
            article_file.write_text(json.dumps([stale]))
            assert fb.main() == 0
            assert photo.call_count == 3

            # A failed second post: the first is still saved (no double post),
            # the failure is named, and the next run retries it.
            article_file.write_text(json.dumps([
                story("f1", "M62 closed near Milnrow after lorry hits central reservation", "2026-11-18T02:00:00Z"),
                story("f2", "Police Concerned for Missing Woman from Littleborough", "2026-11-18T02:01:00Z"),
            ]))
            photo.side_effect = ["1234_4", RuntimeError("Graph API down")]
            assert fb.main() == 0
            result = json.loads(result_file.read_text())
            assert result["status"] == "posted" and result["article_keys"] == ["f1"], result
            assert "Graph API down" in result["reason"]
            assert "f1" in json.loads(state_file.read_text())["posted"]
            photo.side_effect = None
            photo.return_value = "1234_5"
            assert fb.main() == 0
            assert json.loads(result_file.read_text())["article_keys"] == ["f2"]

    print("Affects-today Facebook tests passed.")


if __name__ == "__main__":
    run()
