#!/usr/bin/env python3
"""Generate the permanent searchable Rochdale Daily public archive."""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

PAGES_DIR = Path("articles")
INDEX_PATH = Path("archive-index.json")
ARCHIVE_PATH = Path("archive.html")
SEARCH_PATH = Path("search.html")


def _meta(source: str, prop: str) -> str:
    patterns = [
        rf'<meta[^>]+property=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']*)',
        rf'<meta[^>]+name=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']*)',
    ]
    for pattern in patterns:
        match = re.search(pattern, source, re.I)
        if match:
            return html.unescape(match.group(1)).strip()
    return ""


def _text(source: str, pattern: str) -> str:
    match = re.search(pattern, source, re.I | re.S)
    if not match:
        return ""
    return re.sub(
        r"\s+",
        " ",
        html.unescape(re.sub(r"<[^>]+>", " ", match.group(1))),
    ).strip()


def read_article(path: Path) -> dict[str, str] | None:
    source = path.read_text(encoding="utf-8", errors="ignore")
    title = (
        _meta(source, "og:title")
        or _text(source, r"<h1[^>]*>(.*?)</h1>")
        or _text(source, r"<title>(.*?)</title>")
    )
    title = re.sub(r"\s*[|–-]\s*Rochdale Daily\s*$", "", title, flags=re.I).strip()
    if not title:
        return None
    return {
        "title": title,
        "url": f"/articles/{path.name}",
        "slug": path.stem,
        "published_at": _meta(source, "article:published_time") or _meta(source, "date"),
        "category": _meta(source, "article:section")
        or _text(
            source,
            r'<span[^>]+class=["\'][^"\']*story-kicker[^"\']*["\'][^>]*>(.*?)</span>',
        ),
        "description": _meta(source, "description") or _meta(source, "og:description"),
    }


def build_index() -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    if PAGES_DIR.exists():
        for path in PAGES_DIR.glob("*.html"):
            item = read_article(path)
            if item:
                records.append(item)
    records.sort(key=lambda item: item.get("published_at", ""), reverse=True)
    return records


def render(records: list[dict[str, str]]) -> str:
    records_json = json.dumps(records, ensure_ascii=False, separators=(",", ":")).replace(
        "</", "<\\/"
    )
    total = f"{len(records):,}"
    page = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>News Archive | Rochdale Daily</title>
<meta name="description" content="Search the complete Rochdale Daily news archive by subject, section, month and year.">
<link rel="stylesheet" href="/assets/css/site.css">
<link rel="stylesheet" href="/assets/css/archive.css">
</head>
<body class="archive-page">
<header class="site-header">
  <div class="archive-header-inner">
    <a class="brand" href="/" aria-label="Rochdale Daily home">
      <img class="brand-logo" src="/assets/img/logo.png" alt="Rochdale Daily">
    </a>
  </div>
</header>
<main class="archive-wrap">
  <section class="archive-masthead" aria-labelledby="archive-title">
    <p class="archive-kicker">Archive</p>
    <h1 id="archive-title">All Stories</h1>
    <p class="archive-deck">Search Rochdale Daily's retained reporting by subject, section and date. Stories remain in the public archive after they leave the homepage unless they are formally removed.</p>
  </section>
  <section class="archive-tools" aria-label="Archive search and filters">
    <div class="archive-search-grid">
      <div class="archive-control archive-control-search">
        <label for="archive-search">Search the archive</label>
        <input id="archive-search" class="archive-input" type="search" placeholder="Person, place, business, road, club or headline" autocomplete="off">
      </div>
      <div class="archive-control">
        <label for="archive-year">Year</label>
        <select id="archive-year" class="archive-select"><option value="all">All years</option></select>
      </div>
      <div class="archive-control">
        <label for="archive-month">Month</label>
        <select id="archive-month" class="archive-select">
          <option value="all">All months</option>
          <option value="0">January</option><option value="1">February</option>
          <option value="2">March</option><option value="3">April</option>
          <option value="4">May</option><option value="5">June</option>
          <option value="6">July</option><option value="7">August</option>
          <option value="8">September</option><option value="9">October</option>
          <option value="10">November</option><option value="11">December</option>
        </select>
      </div>
    </div>
    <div class="archive-sections-shell">
      <p class="archive-sections-label">Browse by section</p>
      <div id="archive-sections" class="archive-sections" role="group" aria-label="Filter by section"></div>
    </div>
    <div class="archive-summary" aria-live="polite">
      <span id="archive-summary"><strong>__TOTAL__</strong> stories in the archive</span>
      <button id="archive-clear" class="archive-clear" type="button">Clear filters</button>
    </div>
  </section>
  <div id="archive-results" class="archive-results"></div>
  <button id="load-more" class="load-more" type="button">Load more stories</button>
  <noscript><p class="archive-noscript">JavaScript is required to search and browse this archive.</p></noscript>
</main>
<script>window.__RD_ARCHIVE__=__RECORDS_JSON__;</script>
<script src="/assets/js/archive.js" defer></script>
</body>
</html>
"""
    return page.replace("__TOTAL__", total).replace("__RECORDS_JSON__", records_json)


def main() -> int:
    records = build_index()
    INDEX_PATH.write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    page = render(records)
    ARCHIVE_PATH.write_text(page, encoding="utf-8")
    SEARCH_PATH.write_text(page, encoding="utf-8")
    print(f"Archive indexed {len(records)} retained article pages.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
