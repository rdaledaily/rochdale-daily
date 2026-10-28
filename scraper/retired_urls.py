"""Never let a removed story become a 404.

Why (28 Oct 2026): Google Analytics showed 32 visits to "Page not found" in
19 days. Traced to takedowns: both remove_story.py and the explicit-takedown
pass in generate_pages.main() deleted the article page but wrote nothing in
its place, so the old Facebook post or Google result for that story landed
on a 404. 22 blocklisted slugs had no page and no redirect.

Every page deletion for a takedown now goes through retire_page(), which
first records a 301 in _redirects to the story's own section hub (read from
the page's breadcrumb, e.g. /news/sport) and only then deletes the file.
A page with no readable breadcrumb goes to /news/, the all-sections hub.

The redirect never points at another story: a legally removed story must not
be replaced by a different one under its URL. archive_identity_repair already
treats every /articles/ source in _redirects as retired, so the page also
stays deleted on later runs.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

NEWS_HUB = "/news/"
SECTION_HEADER = "# Retired by takedown: written automatically by scraper/retired_urls.py"
# Cloudflare Pages allows 2,000 static redirect rules. Warn well before it.
RULE_WARNING_THRESHOLD = 1800

# Generated pages write /news/<hub>.html; the theme pass rewrites it to
# /news/<hub>. Only a link inside the breadcrumb <nav> counts.
_BREADCRUMB_HUB = re.compile(
    r'class="article-breadcrumb"(?:(?!</nav>).)*?href="/news/([a-z0-9-]+)(?:\.html)?"', re.S
)
_SLUG = re.compile(r"[a-z0-9][a-z0-9-]*")


def _rule_sources(redirects_path: Path) -> set[str]:
    try:
        lines = redirects_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    return {
        line.split()[0]
        for line in lines
        if line.strip() and not line.lstrip().startswith("#") and len(line.split()) >= 2
    }


def has_redirect(redirects_path: Path, slug: str) -> bool:
    sources = _rule_sources(redirects_path)
    return f"/articles/{slug}" in sources or f"/articles/{slug}.html" in sources


def hub_for_page(page_html: str) -> str:
    """The section hub a page's breadcrumb names, else the all-sections hub."""
    match = _BREADCRUMB_HUB.search(page_html or "")
    return f"/news/{match.group(1)}" if match else NEWS_HUB


def record_redirect(redirects_path: Path, slug: str, destination: str) -> bool:
    """Append 301 rules for /articles/<slug> and /articles/<slug>.html.

    Returns True when rules were written; False when the slug is not a page
    slug or a rule for it already exists (an editor's hand-written rule,
    for example to a replacement story, always wins)."""
    slug = str(slug or "").strip().lower()
    if not _SLUG.fullmatch(slug) or has_redirect(redirects_path, slug):
        return False
    try:
        existing = redirects_path.read_text(encoding="utf-8")
    except OSError:
        existing = ""
    text = existing if existing.endswith("\n") or not existing else existing + "\n"
    lines = []
    if SECTION_HEADER not in existing:
        if text:
            lines.append("")
        lines.append(SECTION_HEADER)
    lines.append(f"/articles/{slug} {destination} 301")
    lines.append(f"/articles/{slug}.html {destination} 301")
    redirects_path.write_text(text + "\n".join(lines) + "\n", encoding="utf-8")
    count = len(_rule_sources(redirects_path))
    if count > RULE_WARNING_THRESHOLD:
        print(f"WARNING: _redirects holds {count} rules; Cloudflare Pages allows 2,000.")
    return True


def retire_page(page: Path, redirects_path: Path) -> str:
    """Record the redirect for a page, then delete it. Returns the destination."""
    try:
        page_html = page.read_text(encoding="utf-8")
    except OSError:
        page_html = ""
    destination = hub_for_page(page_html)
    record_redirect(redirects_path, page.stem, destination)
    if page.exists():
        page.unlink()
    return destination


def backfill(
    redirects_path: Path, pages_dir: Path, slugs: Iterable[str], destinations: dict[str, str] | None = None
) -> list[str]:
    """Write rules for slugs whose page is already gone with no redirect.

    `destinations` may name a hub per slug (read from an earlier version of
    the page); anything else goes to the all-sections hub."""
    destinations = destinations or {}
    written = []
    for slug in sorted({str(s).strip().lower() for s in slugs}):
        if (pages_dir / f"{slug}.html").exists():
            continue
        if record_redirect(redirects_path, slug, destinations.get(slug, NEWS_HUB)):
            written.append(slug)
    return written
