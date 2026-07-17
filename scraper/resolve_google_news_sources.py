#!/usr/bin/env python3
"""Resolve Google News wrapper URLs to original publisher pages.

The script scans articles.json and replaces Google News URLs with a publisher
URL when one can be recovered from redirects, metadata, or external links.

It is deliberately conservative: it will never replace a URL unless the
candidate is a normal HTTP(S) page outside Google's domains.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urljoin, urlparse
from urllib.request import Request, build_opener

from bs4 import BeautifulSoup

GOOGLE_HOST_SUFFIXES = (
    "google.com",
    "google.co.uk",
    "googleusercontent.com",
    "gstatic.com",
)
MAX_PAGE_BYTES = 5 * 1024 * 1024
USER_AGENT = (
    "Mozilla/5.0 (compatible; RochdaleDaily/2.0; "
    "+https://rochdaledaily.co.uk/)"
)


def clean(value: Any) -> str:
    return str(value or "").strip()


def is_http_url(value: Any) -> bool:
    value = clean(value)
    return value.startswith("https://") or value.startswith("http://")


def hostname(url: str) -> str:
    return urlparse(url).netloc.lower().split(":", 1)[0].removeprefix("www.")


def is_google_host(url: str) -> bool:
    host = hostname(url)
    return any(host == suffix or host.endswith("." + suffix) for suffix in GOOGLE_HOST_SUFFIXES)


def is_google_news_url(url: str) -> bool:
    host = hostname(url)
    return host == "news.google.com" or host.endswith(".news.google.com")


def is_valid_publisher_url(url: str) -> bool:
    if not is_http_url(url):
        return False
    if is_google_host(url):
        return False
    parsed = urlparse(url)
    if not parsed.netloc:
        return False
    bad_suffixes = (
        ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
        ".css", ".js", ".xml", ".json",
    )
    return not parsed.path.lower().endswith(bad_suffixes)


def fetch_page(url: str, timeout: int) -> tuple[bytes, str]:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.2",
            "Accept-Language": "en-GB,en;q=0.9",
        },
    )
    with build_opener().open(request, timeout=timeout) as response:
        final_url = response.geturl()
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = response.read(min(65536, MAX_PAGE_BYTES - size + 1))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_PAGE_BYTES:
                raise ValueError("Google News page exceeded size limit")
        return b"".join(chunks), final_url


def query_string_candidates(url: str) -> list[str]:
    result: list[str] = []
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    for key in ("url", "u", "q", "target", "dest", "destination"):
        for value in query.get(key, []):
            decoded = unquote(html.unescape(value))
            if is_valid_publisher_url(decoded):
                result.append(decoded)
    return result


def metadata_candidates(page: bytes, page_url: str) -> list[str]:
    soup = BeautifulSoup(page, "html.parser")
    result: list[str] = []

    # Meta refresh.
    for node in soup.find_all("meta"):
        http_equiv = clean(node.get("http-equiv")).lower()
        if http_equiv == "refresh":
            content = clean(node.get("content"))
            match = re.search(r"url\s*=\s*(.+)$", content, flags=re.I)
            if match:
                result.append(urljoin(page_url, match.group(1).strip(" '\"")))

    # Canonical / Open Graph URL if Google has exposed the publisher URL.
    for node in soup.find_all(["link", "meta"]):
        rel = " ".join(node.get("rel") or []).lower() if node.name == "link" else ""
        prop = clean(node.get("property")).lower()
        name = clean(node.get("name")).lower()
        if rel == "canonical":
            result.append(urljoin(page_url, clean(node.get("href"))))
        elif prop == "og:url" or name == "twitter:url":
            result.append(urljoin(page_url, clean(node.get("content"))))

    # External anchors. Prefer article-looking URLs over homepages.
    anchors: list[tuple[int, str]] = []
    for anchor in soup.find_all("a", href=True):
        href = urljoin(page_url, html.unescape(clean(anchor.get("href"))))
        if not is_valid_publisher_url(href):
            continue
        path = urlparse(href).path
        score = 0
        if len(path.strip("/").split("/")) >= 2:
            score += 3
        if re.search(r"/20\d{2}/|/news/|/article/|/story/", path, flags=re.I):
            score += 3
        if clean(anchor.get_text(" ", strip=True)):
            score += 1
        anchors.append((score, href))

    anchors.sort(key=lambda item: item[0], reverse=True)
    result.extend(url for _, url in anchors)

    deduped: list[str] = []
    for candidate in result:
        candidate = clean(candidate)
        if is_valid_publisher_url(candidate) and candidate not in deduped:
            deduped.append(candidate)
    return deduped


def resolve_google_news_url(url: str, timeout: int = 20) -> str | None:
    for candidate in query_string_candidates(url):
        return candidate

    try:
        page, final_url = fetch_page(url, timeout)
    except (HTTPError, URLError, TimeoutError, ValueError, OSError):
        return None

    if is_valid_publisher_url(final_url):
        return final_url

    candidates = metadata_candidates(page, final_url)
    return candidates[0] if candidates else None


def publisher_name(url: str) -> str:
    host = hostname(url)
    parts = host.split(".")
    if len(parts) >= 2:
        label = parts[-2]
    else:
        label = host
    return label.replace("-", " ").replace("_", " ").title() or "Original publisher"


def article_urls(article: dict[str, Any]) -> list[tuple[str, str]]:
    fields = (
        "source_url",
        "url",
        "link",
        "article_url",
        "original_url",
        "publisher_url",
    )
    result: list[tuple[str, str]] = []
    for field in fields:
        value = clean(article.get(field))
        if is_http_url(value):
            result.append((field, value))
    return result


def resolve_article(article: dict[str, Any], timeout: int) -> tuple[bool, str]:
    google_fields = [(field, url) for field, url in article_urls(article) if is_google_news_url(url)]
    if not google_fields:
        return False, "not-google-news"

    # First prefer a publisher URL already present elsewhere in the record.
    for field, url in article_urls(article):
        if is_valid_publisher_url(url):
            resolved = url
            break
    else:
        resolved = None

    if resolved is None:
        for _, google_url in google_fields:
            resolved = resolve_google_news_url(google_url, timeout)
            if resolved:
                break

    if not resolved:
        article["google_news_resolution_status"] = "unresolved"
        return False, "unresolved"

    original_google_url = google_fields[0][1]
    article["google_news_url"] = original_google_url
    article["source_url"] = resolved
    article["source_name"] = publisher_name(resolved)
    article["publisher_url"] = resolved
    article["google_news_resolution_status"] = "resolved"

    source_urls = [
        clean(value) for value in (article.get("source_urls") or [])
        if is_http_url(value)
    ]
    source_urls = [value for value in source_urls if not is_google_news_url(value)]
    if resolved not in source_urls:
        source_urls.insert(0, resolved)
    article["source_urls"] = source_urls

    # Remove known Google image candidates so the next stage cannot reuse them.
    for field in (
        "image_url",
        "source_image_candidate_url",
        "source_image_url",
        "rss_image_url",
        "media_content_url",
        "media_thumbnail_url",
        "enclosure_url",
        "thumbnail_url",
    ):
        value = clean(article.get(field))
        if value and is_google_host(value):
            article.pop(field, None)

    return True, "resolved"


def atomic_write(path: Path, value: Any) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--articles", type=Path, default=Path("articles.json"))
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("google_news_resolution_report.json"),
    )
    args = parser.parse_args(argv or sys.argv[1:])

    articles = json.loads(args.articles.read_text(encoding="utf-8"))
    if not isinstance(articles, list):
        raise SystemExit("articles.json must contain a JSON array")

    resolved = 0
    unresolved = 0
    untouched = 0
    items: list[dict[str, str]] = []

    for article in articles:
        if not isinstance(article, dict):
            continue
        changed, status = resolve_article(article, args.timeout)
        if changed:
            resolved += 1
        elif status == "unresolved":
            unresolved += 1
        else:
            untouched += 1
        if status != "not-google-news":
            items.append({
                "title": clean(article.get("title")),
                "status": status,
                "source_url": clean(article.get("source_url")),
                "google_news_url": clean(article.get("google_news_url")),
            })

    atomic_write(args.articles, articles)
    atomic_write(args.report, {
        "resolved": resolved,
        "unresolved": unresolved,
        "untouched": untouched,
        "items": items,
    })

    print(json.dumps({
        "resolved": resolved,
        "unresolved": unresolved,
        "untouched": untouched,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
