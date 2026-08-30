#!/usr/bin/env python3
"""Tests for the GMP breaking watcher.

Run: PYTHONPATH=scraper python scraper/test_gmp_watch.py

The legal gate and the locality filter are the two things that must not drift,
so most of this file is about them. Nothing here touches the network.
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gmp_watch as gw

FAILURES: list[str] = []


def check(condition: bool, label: str) -> None:
    if condition:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}")
        FAILURES.append(label)


def section(title: str) -> None:
    print(f"\n{title}")


# --------------------------------------------------------------------------
section("The legal gate holds what it must")
# --------------------------------------------------------------------------

MUST_HOLD = [
    ("Man charged with burglary in Rochdale", "", "charge"),
    ("Rochdale man to appear before magistrates", "", "court"),
    ("Man sentenced for Heywood robbery", "", "sentencing"),
    ("Appeal after Middleton incident", "He pleaded guilty at Manchester Crown Court.", "court"),
    ("Rochdale man convicted", "", "conviction"),
    ("Trial date set for Milnrow case", "", "proceedings"),
    ("Inquest opens into Littleborough death", "", "coronial proceedings"),
    ("Appeal after rape in Rochdale town centre", "", "sexual offence"),
    ("Witness appeal", "The victim was sexually assaulted near the station.", "sexual offence"),
    ("Appeal for information", "A 9-year-old girl was subjected to abuse over two years.", "child safeguarding"),
]
for title, body, expected in MUST_HOLD:
    reason = gw.hold_reason(title, body)
    check(reason == expected, f"holds ({expected}): {title[:48]}")

MUST_PUBLISH = [
    ("Appeal for witnesses after Bury Road collision", "Officers were called at 4.15pm to a collision in Rochdale."),
    ("Missing Rochdale teenager found safe", "We are pleased to say she has been found safe and well."),
    ("Road closed after Heywood crash", "Manchester Road is closed in both directions."),
    ("Man arrested after Middleton burglary", "A 34-year-old man has been arrested on suspicion of burglary."),
    ("Warning after Littleborough distraction thefts", "We are urging residents to be alert."),
    ("Appeal after 12-year-old boy hurt in collision", "The boy was taken to hospital with a leg injury."),
]
for title, body in MUST_PUBLISH:
    reason = gw.hold_reason(title, body)
    check(reason == "", f"publishes: {title[:48]}" + (f"  [held: {reason}]" if reason else ""))

# The child pattern alone must not hold -- only child + safeguarding language.
check(
    gw.hold_reason("Appeal after 12-year-old boy hurt in collision", "") == "",
    "a child mentioned in an ordinary incident does not hold",
)
check(
    gw.hold_reason("Appeal", "A child was neglected over several months.") == "child safeguarding",
    "child plus safeguarding language holds",
)

# --------------------------------------------------------------------------
section("Locality: GMP covers ten boroughs, we take one")
# --------------------------------------------------------------------------

LOCAL = [
    ("Appeal after collision on Bury Road, Rochdale", "Officers were called to Bury Road in Rochdale."),
    ("Missing man from Heywood found safe", "The man from Heywood has been found."),
    ("Witness appeal after Middleton town centre assault", "The incident happened in Middleton town centre, Rochdale borough."),
]
for title, body in LOCAL:
    local, area = gw.is_borough_story(title, body, "https://www.gmp.police.uk/news/x")
    check(local, f"local: {title[:48]}  (area={area or 'none'})")

NOT_LOCAL = [
    ("Appeal after Wigan town centre robbery", "The robbery happened in Wigan."),
    ("Stockport man jailed", "A man from Stockport."),
    ("Bolton collision closes road", "The A666 in Bolton is closed."),
]
for title, body in NOT_LOCAL:
    local, _ = gw.is_borough_story(title, body, "https://www.gmp.police.uk/news/x")
    check(not local, f"not ours: {title[:48]}")

# Known and deliberate: Rochdale has a Bury Road, an Oldham Road and a Bolton
# Road. A GMP post naming only the street reads as another borough's story to
# the shared locality rules. Rather than loosen a guard the whole pipeline
# depends on, the watcher records every rejection in its state file so this can
# be judged on real GMP copy after a day of running.
street_only, _ = gw.is_borough_story(
    "Appeal after Bury Road collision",
    "Officers were called to a collision on Bury Road.",
    "https://www.gmp.police.uk/news/x",
)
check(not street_only, "a rival-borough street name with no town named is rejected (known limitation)")
named, _ = gw.is_borough_story(
    "Appeal after Bury Road collision",
    "Officers were called to a collision on Bury Road, Rochdale.",
    "https://www.gmp.police.uk/news/x",
)
check(named, "the same post passes once GMP names the town, which their copy normally does")

# --------------------------------------------------------------------------
section("Entry building: status routing and no invented copy")
# --------------------------------------------------------------------------

now = datetime(2026, 8, 30, 18, 0, tzinfo=timezone.utc)

live = gw.build_entry(
    {
        "title": "Rochdale | Appeal for witnesses after Bury Road collision",
        "body": "Officers were called at around 4.15pm on Saturday 30 August to a collision on Bury Road, Rochdale.",
        "url": "https://www.gmp.police.uk/news/a",
        "published": "2026-08-30T17:50:00Z",
    },
    now=now,
)
check(live["status"] == "live", "a clean borough appeal goes live")
check(live["title"] == "Appeal for witnesses after Bury Road collision", "location prefix stripped from the headline")
check("Officers were called" in live["quote"], "GMP's own words are carried verbatim")
check(live["quote"].count("Officers were called") == 1, "no duplication of the statement")
check(live["attribution"] == "Greater Manchester Police said:", "attribution is explicit")
check(live["source_url"] == "https://www.gmp.police.uk/news/a", "source URL preserved")
check(live["expires_at"] > live["published_at"], "entry carries an expiry")

held = gw.build_entry(
    {
        "title": "Man charged after Rochdale burglary",
        "body": "A Rochdale man has been charged with burglary.",
        "url": "https://www.gmp.police.uk/news/b",
        "published": "2026-08-30T17:50:00Z",
    },
    now=now,
)
check(held["status"] == "held", "charge language is held, not published")
check(held["hold_reason"] == "charge", "hold reason recorded for the editor")

ignored = gw.build_entry(
    {
        "title": "Appeal after Wigan robbery",
        "body": "The robbery happened in Wigan town centre.",
        "url": "https://www.gmp.police.uk/news/c",
        "published": "2026-08-30T17:50:00Z",
    },
    now=now,
)
check(ignored["status"] == "ignored", "out-of-borough posts are ignored entirely")

# --------------------------------------------------------------------------
section("Freshness: a backlog cannot flood the front page")
# --------------------------------------------------------------------------

old = dict(live, source_published_at="2026-08-28T09:00:00Z")
check(not gw.is_fresh(old, now=now), "a two-day-old post is not breaking news")
check(gw.is_fresh(live, now=now), "a ten-minute-old post is")
check(
    gw.is_fresh({"source_published_at": ""}, now=now),
    "an undated post is allowed through rather than silently dropped",
)

# --------------------------------------------------------------------------
section("Merge, prune and the live cap")
# --------------------------------------------------------------------------


def entry(slug: str, minutes_ago: int, status: str = "live") -> dict:
    stamp = now - timedelta(minutes=minutes_ago)
    return {
        "slug": slug,
        "title": slug,
        "source_url": f"https://www.gmp.police.uk/news/{slug}",
        "published_at": gw.iso_utc(stamp),
        "expires_at": gw.iso_utc(stamp + timedelta(hours=18)),
        "status": status,
    }


merged = gw.merge_breaking([entry("a", 10)], [entry("a", 5), entry("b", 2)])
check(len(merged) == 2, "the same source URL is never added twice")
check(merged[0]["slug"] == "b", "newest breaking entry sorts first")

capped = gw.merge_breaking([], [entry(str(i), i) for i in range(1, 7)])
check(
    len([e for e in capped if e["status"] == "live"]) == gw.MAX_LIVE_BREAKING,
    f"no more than {gw.MAX_LIVE_BREAKING} live breaking cards at once",
)

expired = entry("old", 10)
expired["expires_at"] = gw.iso_utc(now - timedelta(hours=1))
check(gw.prune([expired], now=now) == [], "expired entries drop out on their own")

superseded = dict(entry("done", 5), status="superseded")
check(gw.prune([superseded], now=now) == [], "superseded entries drop out")

held_entry = entry("held-one", 5, status="held")
kept = gw.prune([held_entry], now=now)
check(len(kept) == 1 and kept[0]["status"] == "held", "held entries are kept for the editor, not discarded")

# --------------------------------------------------------------------------
section("Parsing")
# --------------------------------------------------------------------------

feed_html = """
<html><head>
<link rel="alternate" type="application/rss+xml" title="News" href="/news/rss/">
<link rel="stylesheet" href="/x.css">
</head><body></body></html>
"""
check(
    gw.discover_feeds(feed_html, "https://www.gmp.police.uk/")
    == ["https://www.gmp.police.uk/news/rss/"],
    "declared feeds are discovered and made absolute",
)
check(
    gw.discover_feeds("<html><head></head></html>", "https://www.gmp.police.uk/") == [],
    "no feed is invented when none is declared",
)

listing = """
<ul>
  <li><a href="/news/greater-manchester/news/appeal-bury-road/">Appeal after Bury Road collision</a>
      <time datetime="2026-08-30T17:50:00Z">today</time></li>
  <li><a href="/news/news-search/?ct=News&page=2">Next page</a></li>
  <li><a href="/news/greater-manchester/news/missing-found/">Missing Rochdale man found safe and well</a></li>
</ul>
"""
parsed = gw.parse_listing(listing, "https://www.gmp.police.uk/news/news-search/?ct=News")
check(len(parsed) == 2, "listing parser skips pagination furniture")
check(parsed[0]["url"].endswith("/appeal-bury-road/"), "listing links made absolute")
check(parsed[0]["published"] == "2026-08-30T17:50:00Z", "listing time picked up")
check(parsed[0]["body"] == "", "listing parser never guesses the statement text")

article = """
<html><head><meta property="article:published_time" content="2026-08-30T17:50:00Z"></head>
<body><article>
<p>Short.</p>
<p>Officers were called at around 4.15pm on Saturday 30 August to reports of a collision on Bury Road, Rochdale.</p>
<p>Anyone with information is asked to contact police quoting log number 1234 of 30/08/26.</p>
</article></body></html>
"""
detail = gw.parse_article(article)
check("Officers were called" in detail["body"], "article statement extracted")
check("Short." not in detail["body"], "furniture paragraphs dropped")
check(detail["published"] == "2026-08-30T17:50:00Z", "article publication time extracted")

# --------------------------------------------------------------------------
section("A full poll cycle, with a stubbed fetcher")
# --------------------------------------------------------------------------


class StubFetcher:
    """Serves canned pages and records what was requested."""

    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.validators: dict[str, dict[str, str]] = {}
        self.requested: list[str] = []

    def get(self, url: str, timeout: int = 20):
        self.requested.append(url)
        if url in self.pages:
            return 200, self.pages[url]
        return 404, ""


home = "<html><head></head></html>"  # no declared feed -> listing fallback
pages = {
    gw.GMP_HOME: home,
    gw.GMP_LISTINGS[0]: listing,
    gw.GMP_LISTINGS[1]: "",
    "https://www.gmp.police.uk/news/greater-manchester/news/appeal-bury-road/": article,
    "https://www.gmp.police.uk/news/greater-manchester/news/missing-found/": """
      <html><head><meta property="article:published_time" content="2026-08-30T17:55:00Z"></head><body><article>
      <p>We are pleased to say the missing Rochdale man has been found safe and well this afternoon.</p>
      </article></body></html>""",
}

state: dict = {}
stub = StubFetcher(pages)
found = gw.poll_once(stub, state, now=now)
check(len(found) == 2, f"both borough stories detected (got {len(found)})")
check(all(e["status"] == "live" for e in found), "both go live")
check(state.get("feed_discovery_done") is True, "feed discovery runs once")
check(len(state.get("seen", [])) == 2, "seen list recorded")

# Second poll: nothing new.
again = gw.poll_once(stub, state, now=now)
check(again == [], "a second poll of unchanged pages publishes nothing")

# A 304 costs nothing.
class NotModifiedFetcher(StubFetcher):
    def get(self, url: str, timeout: int = 20):
        self.requested.append(url)
        return 304, ""


quiet = NotModifiedFetcher({})
quiet_state = {"feeds": [], "feed_discovery_done": True, "seen": []}
check(gw.poll_once(quiet, quiet_state, now=now) == [], "304 responses yield nothing and do not error")

# --------------------------------------------------------------------------
section("run_once writes the files it promises")
# --------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as tmp:
    gw.BREAKING_FILE = Path(tmp) / "breaking.json"
    gw.STATE_FILE = Path(tmp) / "reports" / "gmp_watch_state.json"
    fresh_state: dict = {}
    live_count = gw.run_once(StubFetcher(pages), fresh_state, push=False)
    check(live_count == 2, "run_once reports the number published")
    payload = json.loads(gw.BREAKING_FILE.read_text(encoding="utf-8"))
    check(len(payload["items"]) == 2, "breaking.json written with both items")
    check("generated_at" in payload, "breaking.json carries generated_at")
    check(gw.STATE_FILE.exists(), "watch state written")
    for item in payload["items"]:
        check(bool(item["quote"]), f"entry carries a statement: {item['slug'][:34]}")
        check(item["source_url"].startswith("https://www.gmp.police.uk/"), "entry links back to GMP")

# --------------------------------------------------------------------------
section("Rejections are recorded, not silently dropped")
# --------------------------------------------------------------------------

reject_state: dict = {"feeds": [], "feed_discovery_done": True, "seen": []}


class OneRejectFetcher(StubFetcher):
    pass


reject_pages = {
    gw.GMP_LISTINGS[0]: """
      <ul><li><a href="/news/greater-manchester/news/wigan-robbery/">Appeal after Wigan town centre robbery</a>
      <time datetime="2026-08-30T17:50:00Z">today</time></li></ul>""",
    gw.GMP_LISTINGS[1]: "",
    "https://www.gmp.police.uk/news/greater-manchester/news/wigan-robbery/": """
      <html><body><article><p>The robbery happened in Wigan town centre on Saturday afternoon.</p>
      </article></body></html>""",
}
out = gw.poll_once(OneRejectFetcher(reject_pages), reject_state, now=now)
check(out == [], "an out-of-borough post publishes nothing")
check(len(reject_state.get("rejected_recent", [])) == 1, "the rejection is recorded for review")
check(
    "Wigan" in reject_state["rejected_recent"][0]["title"],
    "the rejection ledger keeps the headline so the filter can be judged",
)

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED:")
    for name in FAILURES:
        print(f"  - {name}")
    raise SystemExit(1)
print("all gmp_watch tests passed")
