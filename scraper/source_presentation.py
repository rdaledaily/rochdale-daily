"""Public source-presentation rules for Rochdale Daily.

Discovery provenance is retained in article records, but social-media discovery
URLs are never exposed as public source links. Social posts are leads, not a
substitute for an attributable publisher or official source.
"""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import urlparse

SUBTLE_SOURCE_NAMES = {"roch valley radio"}
SUBTLE_SOURCE_DOMAINS = {"rochvalleyradio.com"}
SOCIAL_SOURCE_DOMAINS = {
    "facebook.com",
    "fb.com",
    "instagram.com",
    "threads.net",
    "tiktok.com",
    "x.com",
    "twitter.com",
    "youtube.com",
    "youtu.be",
    "reddit.com",
    "nextdoor.co.uk",
    "nextdoor.com",
}

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


def is_social_source(source_url: Any = "") -> bool:
    domain = _domain(source_url)
    return any(domain == item or domain.endswith("." + item) for item in SOCIAL_SOURCE_DOMAINS)


def is_subtle_source(source_name: Any = "", source_url: Any = "") -> bool:
    name = str(source_name or "").casefold()
    domain = _domain(source_url)
    return (
        any(item in name for item in SUBTLE_SOURCE_NAMES)
        or any(domain == item or domain.endswith("." + item) for item in SUBTLE_SOURCE_DOMAINS)
    )


def clean_title(value: Any) -> str:
    text = str(value or "")
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


COURT_POLICE_IMAGE_RE = re.compile(
    r"\b(sentenced|jailed|convicted|charged|arrested|imprisoned|prison|court|offences?)\b",
    re.IGNORECASE,
)


def enforce_police_image(article: dict[str, Any]) -> dict[str, Any]:
    title = str(article.get("title") or "")
    category = str(article.get("category") or "").casefold()
    police_matter = bool(article.get("police_matter")) or category == "crime"
    current = str(article.get("image_url") or "")
    fallback = (
        not current
        or "area-category-card" in current
        or "generated" in current
        or str(article.get("image_status") or "") in {"area-category-card", "category-fallback"}
    )
    if police_matter and fallback and COURT_POLICE_IMAGE_RE.search(title):
        article["image_url"] = "assets/img/cards/police.jpg"
        article["image_credit"] = "Rochdale Daily"
        article["image_credit_url"] = "https://rochdaledaily.co.uk/"
        article["image_status"] = "standard-police-image"
        article["image_placeholder_reason"] = "Standard police image used for court or sentencing report"
    return article


def sanitise_article(article: dict[str, Any]) -> dict[str, Any]:
    """Return a public-safe article record while retaining internal provenance."""
    if not isinstance(article, dict):
        return article

    source_name = article.get("source_name", "")
    source_url = article.get("source_url", "")
    source_names = article.get("source_names") or []
    source_urls = article.get("source_urls") or []

    social_urls = [
        url for url in [source_url, *source_urls]
        if is_social_source(url)
    ]
    if social_urls:
        article["public_source_hidden"] = True
        article["discovery_source_kind"] = "social"
        if is_social_source(source_url):
            article["source_name"] = "Community report"
        article["source_names"] = [
            "Community report" if index < len(source_urls) and is_social_source(source_urls[index]) else str(name)
            for index, name in enumerate(source_names)
        ]

    subtle = is_subtle_source(source_name, source_url) or any(
        is_subtle_source(
            source_names[index] if index < len(source_names) else "",
            url,
        )
        for index, url in enumerate(source_urls)
    )

    if not subtle:
        return enforce_police_image(article)

    original_title = str(article.get("title") or "")
    for field in _PUBLIC_TEXT_FIELDS:
        if field not in article:
            continue
        article[field] = (
            clean_title(article[field])
            if field == "title"
            else clean_public_text(article[field])
        )

    if is_subtle_source(source_name, source_url):
        article["source_name"] = "Source"

    cleaned_names: list[str] = []
    for index, name in enumerate(source_names):
        url = source_urls[index] if index < len(source_urls) else ""
        cleaned_names.append("Source" if is_subtle_source(name, url) else str(name))
    if source_names:
        article["source_names"] = cleaned_names

    article["image_url"] = ""
    article["image_credit"] = "Rochdale Daily"
    article["source_image_candidate_url"] = ""
    article["source_image_reuse_status"] = ""

    old_slug = str(article.get("slug") or "")
    if (
        "roch-valley-radio" in old_slug.casefold()
        or clean_title(original_title) != original_title.strip()
    ):
        article["slug"] = _slugify(article.get("title"))

    return enforce_police_image(article)


def generic_sources_markup(article: dict[str, Any]) -> str:
    """Render attributable web sources, never social-discovery links."""
    urls: list[str] = []
    primary = str(article.get("source_url") or "").strip()
    if primary:
        urls.append(primary)
    for value in article.get("source_urls") or []:
        url = str(value or "").strip()
        if url and url not in urls:
            urls.append(url)
    urls = [
        url for url in urls
        if url.startswith(("https://", "http://")) and not is_social_source(url)
    ]
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
