"""Regression checks for the production discovery/image policy shim."""
from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import run_newsroom_policy as policy


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

    print("Production newsroom source policy checks passed.")


if __name__ == "__main__":
    main()
