#!/usr/bin/env python3
"""Point every internal link, canonical and sitemap entry at the URL that answers 200.

Cloudflare Pages serves page.html at /page and answers /page.html with a 308
redirect to it. The site was written with .html addresses throughout, so on
19 October 2026 the live search audit (seo_live_audit.py) found:

  * all 36 section, ward and archive pages listed in sitemap.xml at their .html
    address and declaring that address canonical, which is a redirect. Google
    is told the authoritative page is one that does not exist.
  * 20,535 internal links across 1,783 pages pointing at .html addresses, so
    almost every link a crawler follows costs it an extra request.
  * two sitemap entries for stories that had been taken down, answering 404.

This module rewrites those references to the clean address and drops sitemap
entries whose page no longer exists. It is applied by normalise_public_theme.py,
which every publishing lane runs last, so new pages are cleaned as they are
written and the theme check in CI fails if any are missed.
"""
from __future__ import annotations

import re
from pathlib import Path

SITE = "https://rochdaledaily.co.uk"

# Absolute internal URLs ending .html, wherever they appear (href, canonical,
# og:url, JSON-LD "url"/"item"/"@id"). Assets never end .html.
_ABSOLUTE_RE = re.compile(r"(https://rochdaledaily\.co\.uk(?:/[^\"'\s<>#?]*)?)\.html(?=[\"'#?\s<]|$)")
# Relative or root-relative hrefs ending .html. Excludes anything with a scheme.
_HREF_RE = re.compile(r'(?P<attr>\bhref=")(?P<path>(?![a-z][a-z0-9+.-]*:)(?!//)[^"#?]*?)\.html(?P<tail>[#?][^"]*)?"', re.I)


def _strip_index(path: str) -> str:
    """'/news/index' -> '/news/', 'index' -> './', '/index' -> '/'."""
    if path == "index":
        return "./"
    if path.endswith("/index"):
        return path[: -len("index")]
    return path


# Paid links all go through the advertising click tracker. Google requires paid
# links to say so (rel="sponsored"); a paid link that passes ranking credit can
# bring a manual penalty on the whole site.
_TRACKER_A_RE = re.compile(r'<a\b[^>]*\bhref="https://rd-ads\.[^"/]+/go/[^"]*"[^>]*>', re.I)
_REL_RE = re.compile(r'\srel="([^"]*)"', re.I)
PAID_REL = ("sponsored", "nofollow", "noopener", "noreferrer")


def mark_paid_links(text: str) -> str:
    def fix(match: re.Match[str]) -> str:
        tag = match.group(0)
        rel = _REL_RE.search(tag)
        have = rel.group(1).split() if rel else []
        wanted = list(PAID_REL) + [r for r in have if r not in PAID_REL]
        if all(r in have for r in PAID_REL):
            return tag
        value = f' rel="{" ".join(wanted)}"'
        return _REL_RE.sub(value, tag, count=1) if rel else tag[:-1] + value + ">"
    return _TRACKER_A_RE.sub(fix, text)


try:
    from locality_rules import SOURCE_DENY_DOMAINS as DENIED_HOSTS
except Exception:  # pragma: no cover - the rules module is always shipped
    DENIED_HOSTS = set()

# A link to a denied host (spam, hijacked or piracy pages) must not appear on
# any page, whatever wrote it: such links tell Google the site vouches for a
# bad neighbourhood. A source-list item is removed; inline, the words stay.
_DENIED_ITEM_RE = re.compile(r'<li>\s*<a\b[^>]*\bhref="https?://([^"/:]+)[^"]*"[^>]*>.*?</a>\s*</li>', re.S | re.I)
_DENIED_A_RE = re.compile(r'<a\b[^>]*\bhref="https?://([^"/:]+)[^"]*"[^>]*>(.*?)</a>', re.S | re.I)


def _denied(host: str) -> bool:
    host = host.lower().removeprefix("www.")
    return any(host == d or host.endswith("." + d) for d in DENIED_HOSTS)


def strip_denied_links(text: str) -> str:
    if not DENIED_HOSTS or not any(d in text for d in DENIED_HOSTS):
        return text
    text = _DENIED_ITEM_RE.sub(lambda m: "" if _denied(m.group(1)) else m.group(0), text)
    return _DENIED_A_RE.sub(lambda m: m.group(2) if _denied(m.group(1)) else m.group(0), text)


def clean_text(text: str) -> str:
    def absolute(match: re.Match[str]) -> str:
        return _strip_index(match.group(1)) if match.group(1) != SITE else SITE + "/"

    def href(match: re.Match[str]) -> str:
        path = _strip_index(match.group("path"))
        return f'{match.group("attr")}{path}{match.group("tail") or ""}"'

    text = _ABSOLUTE_RE.sub(absolute, text)
    return strip_denied_links(mark_paid_links(_HREF_RE.sub(href, text)))


def file_for_url(url: str, root: Path) -> Path | None:
    """The file Cloudflare Pages would serve for an internal URL, or None."""
    if not url.startswith(SITE):
        return None
    path = url[len(SITE):].split("#", 1)[0].split("?", 1)[0].lstrip("/")
    candidates = []
    if path == "" or path.endswith("/"):
        candidates.append(root / path / "index.html")
    elif path.endswith(".html"):
        candidates.append(root / path)
    else:
        candidates += [root / f"{path}.html", root / path / "index.html", root / path]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


_HEAD_CANON_RE = re.compile(r'<link rel="canonical" href="([^"]+)"')
_HEAD_ROBOTS_RE = re.compile(r'<meta name="robots" content="([^"]+)"')


def indexable_as(page: Path, url: str) -> bool:
    """A sitemap may only list a page Google may index, at its own canonical address."""
    if page.suffix != ".html":
        return True
    head = page.read_text(encoding="utf-8", errors="ignore").split("</head>", 1)[0]
    robots = _HEAD_ROBOTS_RE.search(head)
    if robots and "noindex" in robots.group(1).lower():
        return False
    canonical = _HEAD_CANON_RE.search(head)
    if canonical and clean_text(canonical.group(1)).rstrip("/") != url.rstrip("/"):
        return False
    return True


_URL_BLOCK_RE = re.compile(r"\s*<url>.*?</url>", re.S)
_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")


def clean_sitemap_text(text: str, root: Path) -> tuple[str, int]:
    """Clean every address, and drop <url> entries whose page does not exist."""
    dropped = 0

    def block(match: re.Match[str]) -> str:
        nonlocal dropped
        loc = _LOC_RE.search(match.group(0))
        if loc and not re.search(r"\.(?:jpe?g|png|webp|gif|svg)$", loc.group(1), re.I):
            page = file_for_url(loc.group(1), root)
            if page is None or not indexable_as(page, clean_text(loc.group(1))):
                dropped += 1
                return ""
        return match.group(0)

    return clean_text(_URL_BLOCK_RE.sub(block, text)), dropped


SITEMAPS = ("sitemap.xml", "news-sitemap.xml", "image-sitemap.xml")


def clean_sitemaps(root: Path, *, check: bool = False) -> list[str]:
    changed = []
    for name in SITEMAPS:
        path = root / name
        if not path.is_file():
            continue
        original = path.read_text(encoding="utf-8")
        updated, _ = clean_sitemap_text(original, root)
        if updated != original:
            changed.append(name)
            if not check:
                path.write_text(updated, encoding="utf-8")
    return changed
