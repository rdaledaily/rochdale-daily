#!/usr/bin/env python3
"""A plain-HTML archive, one page per month, so every story is a few clicks from the homepage.

Measured 20 October 2026, following links from the homepage the way a crawler
does:

  * 888 of 1,205 indexable archived stories could not be reached at all, and
    435 had no internal link pointing at them. Google knew them only from the
    sitemap, and treats pages nothing links to as unimportant.
  * /archive lists stories with JavaScript from archive-index.json, so its HTML
    held no story links for a crawler to follow.

This builds:

  * /news/archive/            every month, with its story count
  * /news/archive/YYYY-MM     every indexable story published that month, newest
                              first, with links to the neighbouring months
  * a static list of months inside /archive, so the existing archive page (and
    everything that links to it) leads into them

Home -> /archive -> month -> story: every story is at most three clicks deep.

Only pages Google may index, at their own address, are listed; duplicates that
point their canonical elsewhere would waste the link. Applied by
normalise_public_theme.py after archive_integrity, so it is rebuilt by every
publishing lane and checked by CI.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from archive_integrity import _indexable
from generate_ward_pages import FOOT, chrome_head, esc, load_css, paste_friendly

SITE = "https://rochdaledaily.co.uk"
FOLDER = Path("news") / "archive"
MONTHS = "January February March April May June July August September October November December".split()
START, END = "<!-- rd-archive-months -->", "<!-- /rd-archive-months -->"
_MONTH_FILE_RE = re.compile(r"^\d{4}-\d{2}\.html$")
LIST_CSS = (
    '<style>.rd-archive-list{list-style:none;margin:0;padding:0}'
    '.rd-archive-list li{padding:14px 0;border-top:1px solid var(--line)}'
    '.rd-archive-list a{font-family:var(--font-display);font-size:19px;line-height:1.25;color:var(--ink);text-decoration:none}'
    '.rd-archive-list a:hover{text-decoration:underline;text-underline-offset:3px}'
    '.rd-archive-list p{margin:4px 0 0;color:var(--muted);font-size:14px;line-height:1.5}'
    '.rd-month-nav{display:flex;justify-content:space-between;gap:12px;margin:26px 0 0;font-weight:600}'
    '.rd-month-nav a{color:var(--accent)}'
    '.rd-months{columns:3 200px;margin:0;padding:0;list-style:none}.rd-months li{padding:4px 0}'
    '.rd-months a{color:var(--accent);font-weight:600}</style>'
)


def month_label(key: str) -> str:
    year, month = key.split("-")
    return f"{MONTHS[int(month) - 1]} {year}"


def stories_by_month(root: Path) -> dict[str, list[dict]]:
    try:
        index = json.loads((root / "archive-index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    months: dict[str, list[dict]] = defaultdict(list)
    seen = set()
    for item in index if isinstance(index, list) else []:
        slug = str(item.get("slug") or "")
        stamp = str(item.get("published_at") or "")
        if not slug or slug in seen or not re.match(r"\d{4}-\d{2}", stamp):
            continue
        page = root / "articles" / f"{slug}.html"
        if not page.is_file():
            continue
        html = page.read_text(encoding="utf-8", errors="ignore")
        if not _indexable(html, slug):
            continue
        seen.add(slug)
        months[stamp[:7]].append(item)
    for items in months.values():
        items.sort(key=lambda item: (str(item.get("published_at")), str(item.get("slug"))), reverse=True)
    return dict(months)


def _story(item: dict) -> str:
    day = str(item.get("published_at") or "")[:10]
    y, m, d = day.split("-")
    meta = f'{int(d)} {MONTHS[int(m) - 1][:3]} · {esc(item.get("category") or "News")}'
    description = str(item.get("description") or "").strip()
    return (f'<li><a href="/articles/{esc(item.get("slug"))}">{esc(item.get("title"))}</a>'
            f'<p><span class="rd-meta">{meta}</span>{" — " + esc(description[:160]) if description else ""}</p></li>')


def month_page(key: str, items: list[dict], previous: str | None, following: str | None, css: str) -> str:
    label = month_label(key)
    nav = '<nav class="rd-month-nav" aria-label="Other months">'
    nav += f'<a href="/news/archive/{previous}">← {month_label(previous)}</a>' if previous else "<span></span>"
    nav += '<a href="/news/archive/">All months</a>'
    nav += f'<a href="/news/archive/{following}">{month_label(following)} →</a>' if following else "<span></span>"
    nav += "</nav>"
    head = chrome_head(f"Rochdale news, {label}",
                       f"Every Rochdale Daily story published in {label}: {len(items)} reports from across Rochdale borough.",
                       f"{SITE}/news/archive/{key}", css, back_href="/news/archive/", back_label="All months")
    return paste_friendly(
        head.replace("</head>", LIST_CSS + "</head>", 1)
        + f'<span class="rd-kicker">Archive</span><h1>Rochdale news, {esc(label)}</h1>'
        + f'<p class="rd-lede">{len(items)} stories from across Rochdale borough, newest first.</p>'
        + nav + '<ol class="rd-archive-list">' + "".join(_story(item) for item in items) + "</ol>" + nav
        + FOOT
    )


def months_list(months: dict[str, list[dict]]) -> str:
    out = ""
    for year in sorted({key[:4] for key in months}, reverse=True):
        keys = sorted((k for k in months if k.startswith(year)), reverse=True)
        out += f'<h2 class="rd-h2">{year}</h2><ul class="rd-months">' + "".join(
            f'<li><a href="/news/archive/{k}">{MONTHS[int(k[5:]) - 1]}</a> ({len(months[k])})</li>' for k in keys) + "</ul>"
    return out


def hub_page(months: dict[str, list[dict]], css: str) -> str:
    total = sum(len(items) for items in months.values())
    head = chrome_head("Rochdale news archive by month",
                       f"Every Rochdale Daily story, month by month: {total} reports from across Rochdale borough.",
                       f"{SITE}/news/archive/", css, back_href="/archive", back_label="Search the archive")
    return paste_friendly(
        head.replace("</head>", LIST_CSS + "</head>", 1)
        + '<span class="rd-kicker">Archive</span><h1>Rochdale news, month by month</h1>'
        + f'<p class="rd-lede">{total} stories from across Rochdale borough. '
        + 'Browse <a href="/news/topics/">by topic and place</a>, or use the <a href="/archive">archive search</a>.</p>'
        + months_list(months) + FOOT
    )


def archive_block(months: dict[str, list[dict]]) -> str:
    links = " · ".join(f'<a href="/news/archive/{k}">{month_label(k)}</a>' for k in sorted(months, reverse=True))
    return (f'{START}<nav class="archive-months" aria-label="Browse the archive by month" style="margin:28px 0">'
            f'<h2>Browse by month</h2><p>{links}</p><p><a href="/news/archive/">Every month at a glance</a> · '
            f'<a href="/news/topics/">By topic and place</a></p></nav>{END}')


def with_archive_block(html: str, block: str) -> str:
    if START in html and END in html:
        return re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _: block, html, count=1, flags=re.S)
    return html.replace("</main>", block + "</main>", 1) if "</main>" in html else html


def build(root: Path) -> tuple[dict[Path, str], list[Path]]:
    """(pages to write, stale month pages to remove). Nothing if the archive index is missing."""
    months = stories_by_month(root)
    if not months:
        return {}, []
    css = load_css()
    keys = sorted(months)
    pages: dict[Path, str] = {root / FOLDER / "index.html": hub_page(months, css)}
    for i, key in enumerate(keys):
        previous = keys[i - 1] if i else None
        following = keys[i + 1] if i + 1 < len(keys) else None
        pages[root / FOLDER / f"{key}.html"] = month_page(key, months[key], previous, following, css)
    archive = root / "archive.html"
    if archive.is_file():
        pages[archive] = with_archive_block(archive.read_text(encoding="utf-8"), archive_block(months))
    stale = [path for path in (root / FOLDER).glob("*.html")
             if _MONTH_FILE_RE.match(path.name) and path not in pages] if (root / FOLDER).is_dir() else []
    return pages, stale
