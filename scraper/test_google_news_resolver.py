from __future__ import annotations

from google_news_resolver import _metadata_candidates, _query_candidates, _is_publisher_url


def main() -> int:
    wrapper = (
        "https://news.google.com/rss/articles/token?oc=5&"
        "url=https%3A%2F%2Fexample.com%2Fnews%2Frochdale-story"
    )
    assert _query_candidates(wrapper) == ["https://example.com/news/rochdale-story"]

    html = '''
    <html><head>
      <link rel="canonical" href="https://publisher.example/news/local-story">
      <meta property="og:url" content="https://publisher.example/news/local-story">
    </head></html>
    '''
    assert _metadata_candidates(html, "https://news.google.com/x") == [
        "https://publisher.example/news/local-story"
    ]

    # Google-owned URLs and media assets must never be accepted as publishers.
    assert not _is_publisher_url("https://news.google.com/rss/articles/token")
    assert not _is_publisher_url("https://example.com/photo.jpg")
    assert _is_publisher_url("https://example.com/article/123")

    print("Google News lightweight resolver checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
