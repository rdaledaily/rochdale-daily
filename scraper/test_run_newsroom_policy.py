"""Regression checks for the production discovery/image/length/live policy shim."""
from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import run_newsroom_policy as policy


def _draft_words(count: int) -> dict:
    return {
        "publishable": True,
        "title": "Rochdale Hornets player set for league debut",
        "excerpt": "A player linked with Rochdale Hornets is set for a league debut after the clubs confirmed the latest team news.",
        "paragraphs": [" ".join(f"word{index}" for index in range(count))],
    }


def main() -> None:
    policy.install_runtime_policy()
    core = policy.core

    for name, url in (
        ("Roch Valley Radio", "https://www.rochvalleyradio.com/news-features/139/news/100/example"),
        ("Manchester Evening News", "https://www.manchestereveningnews.co.uk/news/greater-manchester-news/example"),
        ("Rochdale Times", "https://www.rochdaletimes.co.uk/example"),
    ):
        assert not core.source_is_denied(name, url), name
        assert core._priority_local_domain(urlparse(url).hostname or ""), name
        assert core._always_discover_news_domain(urlparse(url).hostname or ""), name
    assert not core.source_is_denied(
        "Rochdale Times",
        "https://rochdaletimes.co.uk/news/example",
    )
    assert not core.source_is_denied(
        "Rochdale Online",
        "https://rochdaleonline.co.uk/news/example",
    )
    assert not core.source_is_denied(
        "Rochdale Observer",
        "https://rochdaleobserver.co.uk/news/example",
    )
    assert core.source_is_denied(
        "PressReader",
        "https://pressreader.com/example",
    )
    # A valid independent rewrite is not thrown away just because the
    # original publisher is named; the source URL remains clickable below it.
    import json
    from pathlib import Path
    from tempfile import TemporaryDirectory
    import reject_publisher_leaks as source_gate
    from source_presentation import generic_sources_markup

    with TemporaryDirectory() as temp:
        root = Path(temp)
        original_articles, original_pages = source_gate.ARTICLES, source_gate.ARTICLE_PAGES
        try:
            source_gate.ARTICLES = root / "articles.json"
            source_gate.ARTICLE_PAGES = root / "articles"
            source_gate.ARTICLE_PAGES.mkdir()
            article = {
                "slug": "rochdale-community-story",
                "title": "Rochdale community story",
                "excerpt": "Manchester Evening News and Roch Valley Radio reported the announcement.",
                "content_html": "<p>Rochdale Times reported the same facts.</p>",
                "source_name": "Roch Valley Radio",
                "source_url": "https://www.rochvalleyradio.com/news-features/3/politics/905/example",
                "source_urls": ["https://www.manchestereveningnews.co.uk/news/example"],
                "publication_route": "ai-grounded-rewrite",
            }
            blocked = {
                "slug": "unsafe-copy-route",
                "title": "Old direct publication",
                "publication_route": "source-led-fallback",
            }
            source_gate.ARTICLES.write_text(json.dumps([article, blocked]), encoding="utf-8")
            assert source_gate.main() == 0
            published = json.loads(source_gate.ARTICLES.read_text(encoding="utf-8"))
            assert [entry["slug"] for entry in published] == ["rochdale-community-story"]
            assert published[0]["source_url"] == article["source_url"]
            source_links = generic_sources_markup(published[0])
            assert "Sources</summary>" in source_links
            assert "Open source 1</a>" in source_links
            assert article["source_url"] in source_links
            assert "Open source 2</a>" in source_links
        finally:
            source_gate.ARTICLES, source_gate.ARTICLE_PAGES = original_articles, original_pages

    google_sources = core.google_news_sources()
    assert google_sources
    for source in google_sources:
        query = (parse_qs(urlparse(source["url"]).query).get("q") or [""])[0]
        assert "-site:rochdaletimes.co.uk" not in query
        assert "-site:rochdaleonline.co.uk" not in query

    # Retrospective/archive pages must never be promoted as fresh hard news,
    # even when a search aggregator supplies a current timestamp.
    history_candidate = SimpleNamespace(
        source_url="https://www.politics.co.uk/history/galloway-wins-landslide-victory-in-chaotic-rochdale-by-election/",
        source_published_at="2026-09-22T00:21:50Z",
    )
    assert policy.pipeline._source_is_temporally_suspect(history_candidate)

    old_year_candidate = SimpleNamespace(
        source_url="https://example.com/2024/03/old-result/",
        source_published_at="2026-09-22T00:21:50Z",
    )
    assert policy.pipeline._source_is_temporally_suspect(old_year_candidate)

    current_candidate = SimpleNamespace(
        source_url="https://example.com/2026/09/current-result/",
        source_published_at="2026-09-22T00:21:50Z",
    )
    assert not policy.pipeline._source_is_temporally_suspect(current_candidate)

    competitor = SimpleNamespace(
        source_url="https://rochdaletimes.co.uk/news/example",
        image_candidate_url="https://rochdaletimes.co.uk/images/example.jpg",
    )
    assert not core._source_image_allowed(competitor)

    official = SimpleNamespace(
        source_url="https://www.rochdale.gov.uk/news/article/123/example",
        image_candidate_url="https://www.rochdale.gov.uk/images/example.jpg",
    )
    assert core._source_image_allowed(official)

    rich_source = " ".join(f"fact{index}" for index in range(420))
    length_issue = (
        "Write at least 200 body words using only facts already present in the sources; "
        "the draft currently has 197."
    )
    issues = policy._remove_near_target_length_issue(
        [length_issue, "Keep this other issue."],
        _draft_words(197),
        rich_source,
    )
    assert length_issue not in issues
    assert "Keep this other issue." in issues

    # The tolerance is deliberately narrow: 189 words still requires expansion,
    # and thin-source adaptive floors are not relaxed at all.
    issues = policy._remove_near_target_length_issue(
        [length_issue],
        _draft_words(189),
        rich_source,
    )
    assert length_issue in issues
    thin_source = "short factual source " * 20
    thin_issue = "Write at least 50 body words using only facts already present in the sources; the draft currently has 47."
    issues = policy._remove_near_target_length_issue(
        [thin_issue],
        _draft_words(47),
        thin_source,
    )
    assert thin_issue in issues

    # Legacy static council guidance accidentally carrying a LIVE flag must not
    # consume a recurring page-comparison fetch. Plausibly changing council news
    # and roadworks/directory records remain watchable, as do explicit live rows.
    assert not policy._should_watch_developing_article({
        "live_story": True,
        "is_ongoing": True,
        "source_kind": "article",
        "source_url": "https://www.rochdale.gov.uk/council-tax/pay-council-tax",
    })
    assert policy._should_watch_developing_article({
        "live_story": True,
        "source_kind": "article",
        "source_url": "https://www.rochdale.gov.uk/news/article/662/example",
    })
    assert policy._should_watch_developing_article({
        "live_story": True,
        "source_kind": "article",
        "source_url": "https://www.rochdale.gov.uk/directory-record/2544/example",
    })
    assert policy._should_watch_developing_article({
        "source_kind": "live",
        "source_url": "https://tfgm.com/travel-updates/travel-alerts",
    })
    assert policy._should_watch_developing_article({
        "live_story": True,
        "source_kind": "article",
        "source_url": "https://www.rochdale.gov.uk/council-tax/pay-council-tax",
        "live_updates": [{"timestamp": "2026-08-16T10:00:00Z", "text": "Verified update"}],
    })

    print("Production newsroom source, no-padding and live-watch policy checks passed.")


if __name__ == "__main__":
    main()
