"""Immediate-news monitor (editor, 17 Nov 2026).

Headlines are the real items the three outlets carried on 16-17 Nov 2026.
Run: PYTHONPATH=scraper python scraper/test_immediate_watch.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("IMMEDIATE_WATCH_STATE", str(Path(tempfile.mkdtemp()) / "state.json"))
os.environ.setdefault("IMMEDIATE_WATCH_REPORT", str(Path(tempfile.mkdtemp()) / "report.json"))

import immediate_watch as watch  # noqa: E402
from immediate_news import MONITORED_SOURCES, clean_title, immediate_kind  # noqa: E402

UTC = timezone.utc
NOW = datetime(2026, 11, 17, 9, 0, tzinfo=UTC)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


# --- classification -----------------------------------------------------------

IMMEDIATE = {
    "Dozens of properties left without power": "utility-outage",
    "Heywood homes left without power after cable fault during snow warning": "utility-outage",
    "Cordon in place after stabbing in Middleton": "live-incident",
    "Fire crews tackle blaze at derelict Rochdale mill": "live-incident",
    "Man seriously injured in attack on Boundary Street, Rochdale - Manchester Evening News": "live-incident",
    "Urgent appeal for missing 16-year-old girl last seen in Norden": "missing-person",
    "M62 closed near Milnrow after lorry hits central reservation": "traffic-incident",
    "Tram services suspended between Shaw and Rochdale following police incident": "traffic-incident",
}
NOT_IMMEDIATE = [
    "Campaigners hit out at 'absurd' College Bank demolition decision",
    "Rochdale Business Awards 2026 winners announced",
    "Decision made on future of Rochdale's iconic College Bank towers",
    "Man admits murder of Keeley 'Kiki' Aspinall",
    "Man who died in flat fire named",
    "Old office block in Rochdale will be turned into apartments",
    "Today marks 215 years since the birth of John Bright",
    "Rochdale striker's late shot earns point at Bromley",
    "Firefighters remembered at Heywood memorial service",
]


def test_classifier() -> None:
    for title, kind in IMMEDIATE.items():
        check(immediate_kind(title) == kind, f"{title!r}: expected {kind}, got {immediate_kind(title)!r}")
    for title in NOT_IMMEDIATE:
        check(immediate_kind(title) == "", f"{title!r} is not immediate, got {immediate_kind(title)!r}")
    check(clean_title("Man hurt - Manchester Evening News") == "Man hurt", "Google News suffix stripped")


# --- reading feeds ------------------------------------------------------------

RT_FEED = """<?xml version="1.0"?><rss version="2.0"><channel><title>Rochdale Times</title>
<item><title>Dozens of properties left without power</title>
<link>https://www.rochdaletimes.co.uk/dozens-of-properties-left-without-power/</link>
<guid>https://www.rochdaletimes.co.uk/?p=101</guid>
<pubDate>Tue, 17 Nov 2026 07:27:14 +0000</pubDate><description>More than 60 properties in Heywood.</description></item>
<item><title>Rochdale Business Awards 2026 winners announced</title>
<link>https://www.rochdaletimes.co.uk/awards/</link><pubDate>Mon, 16 Nov 2026 17:58:30 +0000</pubDate></item>
</channel></rss>"""
RVR_FEED = """<?xml version="1.0"?><rss version="2.0"><channel><title>RVR</title>
<item><title>Cordon in place after stabbing in Bury town centre</title>
<link>https://www.rochvalleyradio.com/news/bury-stabbing</link><pubDate>Tue, 17 Nov 2026 08:10:00 GMT</pubDate>
<description>Police were called to Bury town centre.</description></item>
<item><title>Cordon in place after stabbing in Middleton</title>
<link>https://www.rochvalleyradio.com/news/middleton-stabbing</link><pubDate>Tue, 17 Nov 2026 08:20:00 GMT</pubDate>
<description>Police were called to Middleton, Rochdale borough, this morning.</description></item>
</channel></rss>"""
MEN_FEED = """<?xml version="1.0"?><rss version="2.0"><channel><title>Google News</title>
<item><title>Fire crews tackle blaze at derelict Rochdale mill - Manchester Evening News</title>
<link>https://news.google.com/rss/articles/CBMiabc?oc=5</link><pubDate>Tue, 17 Nov 2026 08:40:00 GMT</pubDate>
<description>Firefighters in Rochdale</description></item>
</channel></rss>"""


class Response:
    def __init__(self, status: int, body: str = "", payload: object = None) -> None:
        self.status_code = status
        self.content = body.encode()
        self._payload = payload

    def json(self) -> object:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise watch.requests.HTTPError(str(self.status_code))


def fake_get(feeds: dict[str, Response], queued: int = 0):
    calls: list[str] = []

    def get(url: str, **kwargs: object) -> Response:
        calls.append(url)
        if "api.github.com" in url:
            return Response(200, payload={"total_count": queued})
        for key, response in feeds.items():
            if key in url:
                return response
        return Response(404)
    get.calls = calls  # type: ignore[attr-defined]
    return get


def all_feeds(rt: Response | None = None) -> dict[str, Response]:
    return {"rochdaletimes": rt or Response(200, RT_FEED), "rochvalleyradio": Response(200, RVR_FEED),
            "news.google.com": Response(200, MEN_FEED)}


def fake_post():
    posts: list[str] = []

    def post(url: str, **kwargs: object) -> Response:
        posts.append(url)
        return Response(204)
    post.posts = posts  # type: ignore[attr-defined]
    return post


def test_refusal_is_reported_not_hidden() -> None:
    result = watch.fetch_feed(MONITORED_SOURCES[0], fake_get({"rochdaletimes": Response(403, "<html>no</html>")}))
    check(not result["ok"] and result["http_status"] == 403 and result["error"] == "http 403", f"403 reported: {result}")


def test_baseline_records_without_starting_the_lane() -> None:
    state: dict = {"items": {}}
    post = fake_post()
    outcome = watch.poll(state, now=NOW, token="t", get=fake_get(all_feeds()), post=post, published=[])
    check(post.posts == [], "first poll after a lost cache starts nothing")
    titles = {r["title"] for r in state["items"].values()}
    check(titles == {"Dozens of properties left without power", "Cordon in place after stabbing in Middleton",
                     "Fire crews tackle blaze at derelict Rochdale mill",
                     # 24 Nov 2026: every Rochdale Times / RVR borough headline is tracked
                     "Rochdale Business Awards 2026 winners announced"},
          f"borough immediate items plus rival headlines: {titles}")
    kinds = {r["title"]: r["kind"] for r in state["items"].values()}
    check(kinds["Rochdale Business Awards 2026 winners announced"] == "headline", f"ordinary rival headline kind: {kinds}")
    check("Cordon in place after stabbing in Bury town centre" not in titles, "out-of-borough RVR item still ignored")
    check(all(f["ok"] for f in outcome["feeds"]), "all three feeds read")


def test_new_uncovered_item_starts_the_fast_lane_once() -> None:
    state: dict = {"items": {"seed": {"first_seen_at": watch.iso(NOW), "covered_at": "x", "title": "seed",
                                      "published_at": watch.iso(NOW), "source": "x", "kind": "x", "link": ""}}}
    post = fake_post()
    outcome = watch.poll(state, now=NOW, token="t", get=fake_get(all_feeds()), post=post, published=[])
    check(len(post.posts) == 1 and post.posts[0].endswith("/actions/workflows/scrape-fast.yml/dispatches"), f"one dispatch: {post.posts}")
    check(outcome["kick"]["started"], "kick reported")
    # Two minutes later nothing new: no second start.
    watch.poll(state, now=NOW + timedelta(minutes=2), token="t", get=fake_get(all_feeds()), post=post, published=[])
    check(len(post.posts) == 1, "the same stories never start the lane twice")


def test_queued_run_is_not_doubled() -> None:
    state: dict = {"items": {"seed": {"first_seen_at": watch.iso(NOW), "covered_at": "x", "title": "seed",
                                      "published_at": watch.iso(NOW), "source": "x", "kind": "x", "link": ""}}}
    post = fake_post()
    outcome = watch.poll(state, now=NOW, token="t", get=fake_get(all_feeds(), queued=1), post=post, published=[])
    check(post.posts == [] and "already queued" in outcome["kick"]["detail"], f"queued run reused: {outcome['kick']}")


def test_covered_story_is_matched_and_timed() -> None:
    published = [{
        "slug": "heywood-homes-left-without-power-after-cable-fault-during-snow-warning",
        "title": "Heywood homes left without power after cable fault during snow warning",
        "first_published_at": "2026-11-17T09:44:00Z",
        "source_urls": ["https://www.rochdaletimes.co.uk/dozens-of-properties-left-without-power"],
    }]
    state: dict = {"items": {"seed": {"first_seen_at": watch.iso(NOW), "covered_at": "x", "title": "seed",
                                      "published_at": watch.iso(NOW), "source": "x", "kind": "x", "link": ""}}}
    post = fake_post()
    feeds = {"rochdaletimes": Response(200, RT_FEED), "rochvalleyradio": Response(200, "<rss><channel></channel></rss>"),
             "news.google.com": Response(200, "<rss><channel></channel></rss>")}
    watch.poll(state, now=NOW + timedelta(hours=1), token="t", get=fake_get(feeds), post=post, published=published)
    check(post.posts == [], "a covered story starts nothing (trailing slash ignored)")
    report = watch.build_report(state, NOW + timedelta(hours=1))
    row = next(s for s in report["stories"] if s["title"] == "Dozens of properties left without power")
    check(row["covered_after_min"] == 137, f"07:27 -> 09:44 is 137 min, got {row['covered_after_min']}")
    check(row["covered_by"].endswith("cable-fault-during-snow-warning"), "covering article linked")
    check("| Rochdale Times |" in watch.markdown(report), "summary table rendered")


def test_old_item_is_history_not_immediate() -> None:
    state: dict = {"items": {"seed": {"first_seen_at": watch.iso(NOW), "covered_at": "x", "title": "seed",
                                      "published_at": watch.iso(NOW), "source": "x", "kind": "x", "link": ""}}}
    post = fake_post()
    watch.poll(state, now=NOW + timedelta(hours=8), token="t", get=fake_get(all_feeds()), post=post, published=[])
    check(post.posts == [], "items over six hours old do not start the lane")


# --- the scrape lanes put immediate news first --------------------------------

def test_lane_writes_immediate_first() -> None:
    import scraper as core
    when = core.iso_utc(NOW - timedelta(minutes=30))
    power = core.Candidate("Rochdale Times", "https://www.rochdaletimes.co.uk/dozens-of-properties-left-without-power/",
                           "Dozens of properties left without power", "More than 60 properties", when, "heywood", "news")
    awards = core.Candidate("Rochdale Times", "https://www.rochdaletimes.co.uk/awards/",
                            "Rochdale Business Awards 2026 winners announced", "", when, "rochdale", "business")
    stale = core.Candidate("Roch Valley Radio", "https://www.rochvalleyradio.com/news/old",
                           "Cordon in place after stabbing in Middleton", "", core.iso_utc(NOW - timedelta(hours=9)), "middleton", "crime")
    chosen = core.immediate_first([awards, stale, power], [], now=NOW)
    check([c.source_title for c in chosen] == ["Dozens of properties left without power"], f"immediate first: {chosen}")
    check(core.immediate_first([power], [power], now=NOW) == [], "not taken twice")
    names = [s["name"] for s in core.RSS_SOURCES]
    check("Rochdale Times" in names, "Rochdale Times read from its own RSS feed in every lane")
    check(any(s["url"] == watch.MONITORED_SOURCES[2]["url"] for s in core.google_news_sources()),
          "the MEN borough query is read in every lane")


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"ok {test.__name__}")
    print(f"{len(tests)} immediate-watch tests passed")
