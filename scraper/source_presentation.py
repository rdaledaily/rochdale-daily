"""Public source-presentation rules for Rochdale Daily.

Roch Valley Radio remains an allowed discovery/source publisher, but its brand is
not repeated in public headlines, excerpts, image credits or article footers.
The original URL is retained and presented as a small generic ``Source`` link.
"""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import urlparse

SUBTLE_SOURCE_NAMES = {"roch valley radio"}
SUBTLE_SOURCE_DOMAINS = {"rochvalleyradio.com"}

_PUBLIC_TEXT_FIELDS = (
    "title",
    "excerpt",
    "summary",
    "content_html",
    "image_credit",
    "legal_disclaimer",
    "right_to_reply",
    "social_context_note",
)


def _domain(value: Any) -> str:
    host = (urlparse(str(value or "")).hostname or "").casefold()
    return host[4:] if host.startswith("www.") else host


def is_subtle_source(source_name: Any = "", source_url: Any = "") -> bool:
    name = str(source_name or "").casefold()
    domain = _domain(source_url)
    return (
        any(item in name for item in SUBTLE_SOURCE_NAMES)
        or any(domain == item or domain.endswith("." + item) for item in SUBTLE_SOURCE_DOMAINS)
    )


def clean_title(value: Any) -> str:
    text = str(value or "")
    # Search/RSS titles commonly arrive as ``Headline - Publisher``.
    text = re.sub(
        r"\s*(?:-|–|—|\||:)\s*roch\s+valley\s+radio\s*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\broch\s+valley\s+radio\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"https?://(?:www\.)?rochvalleyradio\.com\S*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+(?:-|–|—|\||:)\s*$", "", text)
    text = re.sub(r"\s{2,}", " ", text).strip(" \t\r\n-|:–—")
    return text or "Local news update"


def clean_public_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(
        r"\s*(?:-|–|—|\||:)\s*roch\s+valley\s+radio(?=\s*(?:<|$|[.!?,;]))",
        "",
        text,
        flags=re.IGNORECASE,
    )
    # In prose, replace the publisher name rather than leaving a broken sentence.
    text = re.sub(
        r"\broch\s+valley\s+radio\b",
        "the source",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"https?://(?:www\.)?rochvalleyradio\.com\S*",
        "the source",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\bthe source\s+the source\b", "the source", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _slugify(value: Any) -> str:
    cleaned = clean_title(value).casefold()
    slug = re.sub(r"[^a-z0-9]+", "-", cleaned).strip("-")[:80]
    return slug or "local-news-update"


def clean_candidate_public_text(candidate: Any) -> Any:
    """Remove publisher branding from text passed into rewriting.

    The source name and source URL stay intact for provenance and linking.
    """
    if not is_subtle_source(
        getattr(candidate, "source_name", ""),
        getattr(candidate, "source_url", ""),
    ):
        return candidate

    candidate.source_title = clean_title(getattr(candidate, "source_title", ""))
    candidate.source_summary = clean_public_text(getattr(candidate, "source_summary", ""))
    candidate.source_body_excerpt = clean_public_text(
        getattr(candidate, "source_body_excerpt", "")
    )

    for related in getattr(candidate, "related_sources", []) or []:
        if not isinstance(related, dict):
            continue
        if is_subtle_source(related.get("name", ""), related.get("url", "")):
            related["title"] = clean_title(related.get("title", ""))
            related["summary"] = clean_public_text(related.get("summary", ""))
            related["body_excerpt"] = clean_public_text(
                related.get("body_excerpt", "")
            )
    return candidate


def sanitise_article(article: dict[str, Any]) -> dict[str, Any]:
    """Return a public-safe article record while preserving source URLs."""
    if not isinstance(article, dict):
        return article

    source_name = article.get("source_name", "")
    source_url = article.get("source_url", "")
    source_names = article.get("source_names") or []
    source_urls = article.get("source_urls") or []

    subtle = is_subtle_source(source_name, source_url) or any(
        is_subtle_source(
            source_names[index] if index < len(source_names) else "",
            url,
        )
        for index, url in enumerate(source_urls)
    )

    if not subtle:
        return article

    original_title = str(article.get("title") or "")
    for field in _PUBLIC_TEXT_FIELDS:
        if field not in article:
            continue
        article[field] = (
            clean_title(article[field])
            if field == "title"
            else clean_public_text(article[field])
        )

    # Keep provenance in the URL, but do not repeat the publisher brand in the
    # public JSON feed, card, caption or footer.
    if is_subtle_source(source_name, source_url):
        article["source_name"] = "Source"

    cleaned_names: list[str] = []
    for index, name in enumerate(source_names):
        url = source_urls[index] if index < len(source_urls) else ""
        cleaned_names.append("Source" if is_subtle_source(name, url) else str(name))
    if source_names:
        article["source_names"] = cleaned_names

    category = str(article.get("category") or "news").casefold()
    if category not in {
        "news", "crime", "traffic", "transport", "politics", "education",
        "sport", "events", "business", "community", "health", "environment",
    }:
        category = "news"

    # Do not reuse a publisher image without a visible credit. Use Rochdale
    # Daily's category artwork instead.
    article["image_url"] = f"assets/img/stock_{category}.jpg"
    article["image_credit"] = "Rochdale Daily category image"
    article["source_image_candidate_url"] = ""
    article["source_image_reuse_status"] = ""

    old_slug = str(article.get("slug") or "")
    if (
        "roch-valley-radio" in old_slug.casefold()
        or clean_title(original_title) != original_title.strip()
    ):
        article["slug"] = _slugify(article.get("title"))

    return article


def generic_sources_markup(article: dict[str, Any]) -> str:
    urls: list[str] = []
    primary = str(article.get("source_url") or "").strip()
    if primary:
        urls.append(primary)
    for value in article.get("source_urls") or []:
        url = str(value or "").strip()
        if url and url not in urls:
            urls.append(url)
    urls = [url for url in urls if url.startswith(("https://", "http://"))]
    if not urls:
        return ""
    items = "".join(
        f'<li><a href="{html.escape(url, quote=True)}" target="_blank" '
        f'rel="nofollow noopener noreferrer">Open source {index}</a></li>'
        for index, url in enumerate(urls[:12], start=1)
    )
    return (
        '<details class="article-sources">'
        '<summary>Sources</summary>'
        f'<ul>{items}</ul>'
        '</details>'
    )
