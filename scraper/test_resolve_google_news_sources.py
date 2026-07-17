from __future__ import annotations

import resolve_google_news_sources as mod


def test_google_hosts_are_rejected_as_publishers() -> None:
    assert mod.is_google_news_url("https://news.google.com/articles/example")
    assert not mod.is_valid_publisher_url("https://news.google.com/articles/example")
    assert not mod.is_valid_publisher_url("https://lh3.googleusercontent.com/image.jpg")


def test_query_string_publisher_is_extracted() -> None:
    url = "https://news.google.com/example?url=https%3A%2F%2Fpublisher.example%2Fnews%2Fstory"
    candidates = mod.query_string_candidates(url)
    assert candidates == ["https://publisher.example/news/story"]


def test_existing_publisher_url_is_preferred() -> None:
    article = {
        "source_url": "https://news.google.com/articles/example",
        "publisher_url": "https://publisher.example/news/story",
        "image_url": "https://news.google.com/logo.png",
    }
    changed, status = mod.resolve_article(article, timeout=1)
    assert changed
    assert status == "resolved"
    assert article["source_url"] == "https://publisher.example/news/story"
    assert "image_url" not in article


if __name__ == "__main__":
    for test in (
        test_google_hosts_are_rejected_as_publishers,
        test_query_string_publisher_is_extracted,
        test_existing_publisher_url_is_preferred,
    ):
        test()
        print(f"PASS {test.__name__}")
