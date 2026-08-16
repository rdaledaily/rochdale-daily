"""Regression checks for the production discovery/image/length policy shim."""
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

    google_sources = core.google_news_sources()
    assert google_sources
    for source in google_sources:
        query = (parse_qs(urlparse(source["url"]).query).get("q") or [""])[0]
        assert "-site:rochdaletimes.co.uk" not in query
        assert "-site:rochdaleonline.co.uk" not in query

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

    print("Production newsroom source and no-padding policy checks passed.")


if __name__ == "__main__":
    main()
