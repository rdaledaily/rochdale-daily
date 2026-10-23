"""Gambling, betting-tips and piracy-stream sites never reach the paper.

Regression for 23 Oct 2026: three live match stories linked apwin.com (an
illegal "watch online for free" stream site), bettingodds.com and whoscored.com
"bet builder" pages, partly through opaque Google News redirects.
Run: python -m pytest -q scraper/test_gambling_piracy_policy.py
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import locality_rules as L  # noqa: E402
import source_presentation as SP  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def test_known_offenders_denied_by_url_and_name():
    assert L.source_is_denied("", "https://www.apwin.com/streams/rochdale-vs-grimsby/")
    assert L.source_is_denied("APWin", "https://news.google.com/rss/articles/CBMi")
    assert L.source_is_denied("", "https://www.bettingodds.com/football/x")
    assert L.source_is_denied("WhoScored.com", "https://www.whoscored.com/articles/x")


def test_new_gambling_and_stream_domains_caught_by_pattern():
    for url in (
        "https://insights.betfred.com/a", "https://news.bet365.com/b",
        "https://best-uk-casino-sites.example/x", "https://nongamstopbets.example/x",
        "https://crackstreams.example/rochdale", "https://rochdale.tips.example/x",
    ):
        assert L.is_gambling_or_piracy_source("", url), url


def test_local_newsrooms_and_ordinary_words_not_denied():
    for name, url in (
        ("Rochdale Times", "https://www.rochdaletimes.co.uk/x"),
        ("Manchester Evening News", "https://www.manchestereveningnews.co.uk/x"),
        ("Rochdale AFC", "https://rochdaleafc.co.uk/x"),
        ("Roch Valley Radio", "https://www.rochvalleyradio.com/x"),
        ("Alphabet Inc", "https://alphabet.com/x"),
        ("Better Homes", "https://betterhomes.example/x"),
        ("Upstream Arts", "https://upstreamarts.example/x"),
        ("BBC", "https://www.bbc.co.uk/news/x"),
    ):
        assert not L.source_is_denied(name, url), (name, url)


def test_no_false_positive_on_any_published_source_host():
    """Every host the live feed cites, except the known offenders."""
    from urllib.parse import urlparse
    offenders = {"apwin.com", "bettingodds.com", "whoscored.com"}
    feed = json.loads((ROOT / "articles.json").read_text(encoding="utf-8"))
    flagged = set()
    for row in feed:
        for url in [row.get("source_url")] + list(row.get("source_urls") or []):
            host = (urlparse(url or "").hostname or "").removeprefix("www.")
            if host and L.is_gambling_or_piracy_source("", url) and host not in offenders:
                flagged.add(host)
    assert not flagged, flagged


def test_rendered_sources_never_link_gambling_or_opaque_redirects():
    article = {
        "source_url": "https://www.skysports.com/football/news/1",
        "source_urls": [
            "https://www.apwin.com/streams/rochdale-vs-grimsby/",
            "https://www.bettingodds.com/football/x",
            "https://news.google.com/rss/articles/CBMiUNRESOLVEDTOKEN?oc=5",
            "https://rochdaleafc.co.uk/report/",
        ],
    }
    hrefs = re.findall(r'href="([^"]+)"', SP.generic_sources_markup(article))
    assert hrefs == ["https://www.skysports.com/football/news/1", "https://rochdaleafc.co.uk/report/"]


def test_resolved_redirect_links_real_publisher_and_blocks_gambling_target():
    SP._GOOGLE_NEWS_RESOLUTIONS = {
        "CBMiGOOD": "https://www.manchestereveningnews.co.uk/news/x",
        "CBMiBAD": "https://www.apwin.com/streams/x",
    }
    try:
        article = {"source_urls": [
            "https://news.google.com/rss/articles/CBMiGOOD?oc=5",
            "https://news.google.com/rss/articles/CBMiBAD?oc=5",
        ]}
        hrefs = re.findall(r'href="([^"]+)"', SP.generic_sources_markup(article))
        assert hrefs == ["https://www.manchestereveningnews.co.uk/news/x"]
    finally:
        SP._GOOGLE_NEWS_RESOLUTIONS = None


def test_promo_title_patterns_present_and_clean_against_published_headlines():
    block = json.loads((ROOT / "story_blocklist.json").read_text(encoding="utf-8"))
    promo = ("watch online for free", "watch live for free", "live stream free",
             "free live stream", "free stream", "bet builder", "non gamstop",
             "non-gamstop", "not on gamstop", "free bets", "free bet",
             "betting odds", "odds & ", "prediction, odds", "casino bonus", "free spins")
    assert set(promo) <= set(block["title_patterns"])
    feed = json.loads((ROOT / "articles.json").read_text(encoding="utf-8"))
    hit = [r["title"] for r in feed for p in promo if p in r["title"].lower()]
    assert not hit, hit
