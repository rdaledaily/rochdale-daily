#!/usr/bin/env python3
"""Synchronise the homepage's static top-story fallback with frontpage.json.

The JavaScript newsroom replaces the top-story area after load, but crawlers,
link unfurlers and no-JS readers see the committed HTML first. Historically that
fallback could keep an ended special live event long after the canonical
frontpage had moved on. This script keeps the static lead and ticker semantics
aligned with the same current feed used by the interactive homepage.
"""
from __future__ import annotations

import html
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
FRONTPAGE = ROOT / "articles" / "frontpage.json"

LEAD_RE = re.compile(
    r'<article class="lead-story" id="lead-story"[^>]*>.*?</article>',
    re.S,
)
BREAKING_LABEL_RE = re.compile(
    r'(<div class="breaking-bar">.*?<div class="breaking-label">)(.*?)(</div>)',
    re.S,
)
BREAKING_TEXT_RE = re.compile(
    r'(<div class="breaking-bar">.*?)(<span class="breaking-text">)(.*?)(</span>)',
    re.S,
)

LABEL_SYNC_MARKER = "// STATIC_TICKER_LABEL_SYNC"
LABEL_SYNC_SNIPPET = '''
          // STATIC_TICKER_LABEL_SYNC
          const breakingLabel = document.querySelector(".breaking-bar .breaking-label");
          if (breakingLabel) {
            breakingLabel.textContent = (!Array.isArray(payload) && payload.breaking) ? "Breaking" : "Latest";
          }
'''
LABEL_SYNC_ANCHOR = "          setBreakingTicker(stripMarkdownText(breakingMessage));\n"


def clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def image_src(article: dict[str, Any]) -> str:
    value = clean(article.get("image_url") or article.get("img"))
    if not value:
        return "/assets/img/category_news.svg"
    return value if value.startswith("/") else "/" + value


def article_url(article: dict[str, Any]) -> str:
    slug = clean(article.get("slug")).strip("/")
    return f"/articles/{slug}.html"


def date_label(article: dict[str, Any]) -> str:
    raw = clean(article.get("first_published_at") or article.get("published_at"))
    if not raw:
        return "Latest update"
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y · %H:%M UTC")
    except ValueError:
        return "Latest update"


def render_lead(article: dict[str, Any]) -> str:
    title = html.escape(clean(article.get("title")))
    excerpt = html.escape(clean(article.get("excerpt") or article.get("summary")))
    category = html.escape(clean(article.get("category") or "News").replace("_", " ").title())
    byline = html.escape(clean(article.get("byline") or "Rochdale Daily Newsdesk"))
    src = html.escape(image_src(article), quote=True)
    href = html.escape(article_url(article), quote=True)
    alt = title
    ongoing = bool(article.get("live_story") or article.get("is_ongoing") or article.get("breaking_news"))
    badge = '<span class="ongoing-badge">ONGOING</span>\n      ' if ongoing else ""
    return f'''<article class="lead-story" id="lead-story" data-content-slot="lead">
    <a href="{href}" class="story-link">
      <div class="story-image-wrap"><img src="{src}" alt="{alt}" loading="eager" decoding="async"></div>
      {badge}<span class="story-kicker">{category}</span>
      <h2 class="lead-headline">{title}</h2>
      <p class="story-summary">{excerpt}</p>
      <div class="story-meta">By {byline} · {html.escape(date_label(article))}</div>
      <span class="read-more-button" aria-hidden="true">Read More →</span>
    </a>
  </article>'''


def sync_ticker(document: str, payload: dict[str, Any], lead: dict[str, Any]) -> str:
    breaking = clean(payload.get("breaking"))
    label = "Breaking" if breaking else "Latest"
    message = breaking or clean(lead.get("title"))
    document, label_count = BREAKING_LABEL_RE.subn(
        lambda m: m.group(1) + html.escape(label) + m.group(3), document, count=1
    )
    if label_count != 1:
        raise SystemExit("homepage breaking label not found")

    # Update both duplicated ticker segments while remaining within the breaking bar.
    bar_match = re.search(r'<div class="breaking-bar">.*?</div>\s*<div class="traffic-bar"', document, re.S)
    if not bar_match:
        raise SystemExit("homepage breaking bar not found")
    bar = bar_match.group(0)
    bar = re.sub(
        r'(<span class="breaking-text">)(.*?)(</span>)',
        lambda m: m.group(1) + html.escape(message) + m.group(3),
        bar,
        flags=re.S,
    )
    bar = re.sub(
        r'(id="breaking-copy"[^>]*aria-label=")([^"]*)(")',
        lambda m: m.group(1) + html.escape(message, quote=True) + m.group(3),
        bar,
        count=1,
    )
    document = document[: bar_match.start()] + bar + document[bar_match.end() :]
    return document


def ensure_dynamic_label_sync(document: str) -> str:
    if LABEL_SYNC_MARKER in document:
        return document
    if LABEL_SYNC_ANCHOR not in document:
        raise SystemExit("breaking ticker JavaScript anchor not found")
    return document.replace(LABEL_SYNC_ANCHOR, LABEL_SYNC_SNIPPET + LABEL_SYNC_ANCHOR, 1)


def main() -> None:
    payload = json.loads(FRONTPAGE.read_text(encoding="utf-8"))
    rows = payload.get("articles") if isinstance(payload, dict) else None
    lead = next((row for row in rows or [] if isinstance(row, dict) and clean(row.get("slug"))), None)
    if lead is None:
        print("Homepage top-story sync: no current frontpage article; leaving fallback unchanged")
        return

    document = INDEX.read_text(encoding="utf-8")
    document, count = LEAD_RE.subn(render_lead(lead), document, count=1)
    if count != 1:
        raise SystemExit("homepage static lead article not found")
    document = sync_ticker(document, payload, lead)
    document = ensure_dynamic_label_sync(document)
    INDEX.write_text(document, encoding="utf-8")
    print(f"Homepage top-story sync: {clean(lead.get('title'))}")


if __name__ == "__main__":
    main()
