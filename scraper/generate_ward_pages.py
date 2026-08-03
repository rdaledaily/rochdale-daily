#!/usr/bin/env python3
"""
Rochdale Daily — ward pages.

Builds one page per council ward at wards/<slug>.html, plus a wards/index.html
listing all twenty. Each ward page carries the stories filed under that ward's
areas and the councillors who represent it, with any recorded votes.

The script also keeps the homepage ward picker directly after Top stories and
before Latest news. That makes ward browsing a primary way into the news rather
than leaving it near the bottom of the homepage.

WHY WARDS AND AREAS ARE MAPPED IN DATA
--------------------------------------
The council's twenty wards and the area tags this site files stories under are
different lists. Spotland and Falinge is one ward covering two areas; Middleton
is one area covering four wards. Keeping that mapping in ward_areas.json rather
than in code means it can be corrected by hand when a story is filed oddly,
without a code change.

Where the mapping is imprecise the ward page says so, rather than presenting
borough-wide Middleton coverage as though it were specific to West Middleton.

Usage:
    python scraper/generate_ward_pages.py
"""

from __future__ import annotations

import html
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WARD_MAP_PATH = REPO_ROOT / "ward_areas.json"
ARTICLES_PATH = REPO_ROOT / "articles.json"
VOTES_PATH = REPO_ROOT / "council_votes.json"
CSS_PATH = REPO_ROOT / "assets" / "css" / "site.css"
OUTPUT_DIR = REPO_ROOT / "wards"
HOME_PATH = REPO_ROOT / "index.html"
SITE = "https://rochdaledaily.co.uk"

MAX_STORIES = 12


def esc(value) -> str:
    return html.escape(str(value or ""), quote=True)


def slugify(name: str) -> str:
    text = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return re.sub(r"-{2,}", "-", text)


def read_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def load_css() -> str:
    try:
        return CSS_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""


SIDE_LABEL = {"for": "Voted for", "against": "Voted against", "abstain": "Abstained"}
SIDE_CLASS = {"for": "dem-vote-for", "against": "dem-vote-against", "abstain": "dem-vote-abstain"}


def chrome_head(title: str, description: str, canonical: str, css: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en-GB">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="index,follow">
  <title>{esc(title)} | Rochdale Daily</title>
  <meta name="description" content="{esc(description)}">
  <link rel="canonical" href="{esc(canonical)}">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Roboto+Condensed:wght@600;700;800&family=Roboto:wght@400;500;700;900&family=Source+Serif+4:opsz,wght@8..60,600;8..60,700;8..60,900&display=swap" rel="stylesheet">
  <style>{css}
    .ward-wrap {{ max-width: 1000px; margin: 0 auto; padding: 28px 20px 60px; }}
    .ward-kicker {{ font-family: "Roboto Condensed", Arial, sans-serif; font-size: 13px; font-weight: 800;
      letter-spacing: .14em; text-transform: uppercase; color: var(--accent); }}
    .ward-wrap h1 {{ font-family: "Roboto Condensed", Arial, sans-serif; font-size: clamp(30px,5vw,46px);
      line-height: 1.05; margin: 6px 0 10px; }}
    .ward-lede {{ font-size: 18px; color: #333; margin: 0 0 26px; }}
    .ward-h2 {{ font-family: "Roboto Condensed", Arial, sans-serif; font-size: 22px; text-transform: uppercase;
      border-top: 3px solid #111; padding-top: 8px; margin: 34px 0 14px; }}
    .ward-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; }}
    .ward-card {{ border: 1px solid var(--line); padding: 15px; background: #fff; }}
    .ward-card h3 {{ font-family: "Roboto Condensed", Arial, sans-serif; font-size: 18px; margin: 0 0 6px; }}
    .ward-card a {{ color: inherit; text-decoration: none; }}
    .ward-card a:hover {{ color: var(--accent); }}
    .ward-meta {{ font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }}
    .ward-note {{ background: #fdf6dc; border-left: 6px solid #f5c400; padding: 12px 14px; font-size: 14px; margin: 0 0 18px; }}
    .ward-index {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 10px; }}
    .ward-index a {{ display: block; border: 1px solid var(--line); padding: 13px 15px; text-decoration: none;
      color: var(--ink); font-family: "Roboto Condensed", Arial, sans-serif; font-weight: 800; font-size: 16px; }}
    .ward-index a:hover {{ border-color: var(--accent); color: var(--accent); }}
    .ward-index span {{ display: block; font-family: Roboto, Arial, sans-serif; font-weight: 400;
      font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; margin-top: 3px; }}
  </style>
</head>
<body>
  <header class="masthead">
    <div class="wrap masthead-row">
      <a class="brand" href="/index.html" aria-label="Rochdale Daily home"><span class="brand-text-fallback">ROCHDALE DAILY</span></a>
      <div class="masthead-actions">
        <a class="header-button" href="/index.html">All stories</a>
        <a class="header-button" href="/wards/">All wards</a>
      </div>
    </div>
  </header>
  <main class="ward-wrap">
"""


CHROME_FOOT = """  </main>
  <footer style="background:#111;color:#cfcfcf;padding:26px 20px;font-size:13px">
    <div style="max-width:1000px;margin:0 auto">
      <p style="margin:0 0 8px"><strong style="color:#fff">Rochdale Daily</strong> &mdash; independent local news for the Rochdale borough.</p>
      <p style="margin:0">
        <a href="/about.html" style="color:#f5c400;text-decoration:none">About</a> &middot;
        <a href="/contact.html" style="color:#f5c400;text-decoration:none">Contact</a> &middot;
        <a href="/privacy.html" style="color:#f5c400;text-decoration:none">Privacy</a> &middot;
        <a href="/terms.html" style="color:#f5c400;text-decoration:none">Terms</a> &middot;
        <a href="/accessibility.html" style="color:#f5c400;text-decoration:none">Accessibility</a> &middot;
        <a href="#" data-cookie-settings style="color:#f5c400;text-decoration:none">Cookie settings</a>
      </p>
    </div>
  </footer>
  <script defer src="/assets/js/cookie-consent.js"></script>
  <script defer src="/assets/ads.js"></script>
</body>
</html>
"""


def story_card(article: dict) -> str:
    slug = esc(article.get("slug"))
    title = esc(article.get("title"))
    excerpt = esc((article.get("excerpt") or "")[:150])
    area = esc(str(article.get("area") or "").title())
    return (f'<article class="ward-card"><div class="ward-meta">{area}</div>'
            f'<h3><a href="/articles/{slug}.html">{title}</a></h3>'
            f"<p>{excerpt}</p></article>")


def councillor_card(person: dict) -> str:
    votes = ""
    for vote in person.get("votes") or []:
        side = vote.get("side") if vote.get("side") in SIDE_LABEL else "abstain"
        label = SIDE_LABEL[side]
        cls = SIDE_CLASS[side]
        title = esc(vote.get("title"))
        link = (f'<a href="{esc(vote.get("url"))}" target="_blank" rel="noopener">{title}</a>'
                if vote.get("url") else title)
        votes += (f'<li style="padding:6px 0;border-top:1px solid #eee">'
                  f'<span class="dem-vote-side {cls}">{esc(label)}</span> {link}</li>')
    body = (f'<p style="margin:10px 0 4px"><b>Recorded votes</b></p>'
            f'<ul style="list-style:none;padding:0;margin:0;font-size:14px">{votes}</ul>'
            if votes else
            "<p style=\"font-size:14px;color:#5f6b78\">No recorded vote has named this councillor yet.</p>")
    return (f'<article class="ward-card"><h3>{esc(person.get("name"))}</h3>'
            f'<div class="ward-meta">{esc(person.get("party"))}</div>{body}</article>')


def build_ward_page(ward: str, config: dict, articles: list[dict], votes: dict, css: str) -> str:
    slug = slugify(ward)
    areas = {a.lower() for a in config.get("areas") or []}
    stories = [a for a in articles if str(a.get("area") or "").lower() in areas][:MAX_STORIES]
    people = (votes.get("wards") or {}).get(ward) or []

    note = config.get("note")
    note_html = f'<p class="ward-note">{esc(note)}</p>' if note else ""

    story_html = ("".join(story_card(a) for a in stories) if stories
                  else '<p style="color:#5f6b78">No stories filed for this ward yet.</p>')
    people_html = ("".join(councillor_card(p) for p in people) if people
                   else '<p style="color:#5f6b78">Councillor details for this ward are not yet listed.</p>')

    head = chrome_head(
        f"{ward} news and councillors",
        f"News from {ward} and what the ward's councillors have voted on.",
        f"{SITE}/wards/{slug}.html", css)

    return head + f"""    <span class="ward-kicker">Ward</span>
    <h1>{esc(ward)}</h1>
    <p class="ward-lede">News from {esc(ward)}, and what the councillors representing it have voted on.</p>
    {note_html}
    <h2 class="ward-h2">Your councillors</h2>
    <div class="ward-grid">{people_html}</div>
    <p style="font-size:13px;color:#5f6b78;margin-top:12px">Only votes taken by name are listed. The council
    records these for the budget and council tax, and otherwise only when a recorded vote is requested.
    Every other vote is minuted as carried or lost without names.</p>
    <h2 class="ward-h2">Ward news</h2>
    <div class="ward-grid">{story_html}</div>
    <p style="margin-top:26px"><a href="/wards/">All wards</a> &middot; <a href="/index.html">All stories</a></p>
""" + CHROME_FOOT


def build_index(wards: dict, articles: list[dict], css: str) -> str:
    rows = []
    for ward in sorted(wards):
        areas = {a.lower() for a in (wards[ward].get("areas") or [])}
        count = sum(1 for a in articles if str(a.get("area") or "").lower() in areas)
        label = f"{count} stor{'y' if count == 1 else 'ies'}" if count else "No stories yet"
        rows.append(f'<a href="/wards/{slugify(ward)}.html">{esc(ward)}<span>{label}</span></a>')
    head = chrome_head("News by ward",
                       "Every Rochdale borough ward: local news and what your councillors voted on.",
                       f"{SITE}/wards/", css)
    return head + f"""    <span class="ward-kicker">Rochdale borough</span>
    <h1>News by ward</h1>
    <p class="ward-lede">Choose your ward for local stories and what the councillors representing you have voted on.</p>
    <div class="ward-index">{''.join(rows)}</div>
""" + CHROME_FOOT


def move_homepage_ward_picker() -> bool:
    """Place the homepage ward picker after Top stories, before Latest news.

    The homepage is a long-lived hand-authored shell whose story cards are
    populated by JavaScript. This small idempotent transform means later page
    generation or editorial changes cannot quietly push ward navigation back
    below the full news feed.
    """
    try:
        page = HOME_PATH.read_text(encoding="utf-8")
    except OSError:
        return False

    ward_pattern = re.compile(
        r'\n\s*<section class="section" id="news-by-ward"\b.*?</section>\s*',
        re.DOTALL,
    )
    match = ward_pattern.search(page)
    if not match:
        return False

    ward_section = match.group(0).strip()
    page_without_ward = page[:match.start()] + "\n\n" + page[match.end():]
    latest_anchor = '<section class="section" aria-labelledby="latest-news-title">'
    anchor_at = page_without_ward.find(latest_anchor)
    if anchor_at < 0:
        return False

    moved = (
        page_without_ward[:anchor_at]
        + ward_section
        + "\n\n      "
        + page_without_ward[anchor_at:]
    )
    if moved == page:
        return False

    HOME_PATH.write_text(moved, encoding="utf-8")
    return True


def main() -> int:
    config = read_json(WARD_MAP_PATH, {})
    wards = config.get("wards") or {}
    if not wards:
        print("generate_ward_pages: no wards configured")
        return 0

    raw = read_json(ARTICLES_PATH, [])
    articles = raw if isinstance(raw, list) else raw.get("articles", [])
    votes = read_json(VOTES_PATH, {})
    css = load_css()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for ward, ward_config in wards.items():
        path = OUTPUT_DIR / f"{slugify(ward)}.html"
        path.write_text(build_ward_page(ward, ward_config, articles, votes, css), encoding="utf-8")

    (OUTPUT_DIR / "index.html").write_text(build_index(wards, articles, css), encoding="utf-8")
    homepage_moved = move_homepage_ward_picker()

    counts = {w: sum(1 for a in articles
                     if str(a.get("area") or "").lower() in {x.lower() for x in (c.get("areas") or [])})
              for w, c in wards.items()}
    total = sum(counts.values())
    print(f"ward pages written: {len(wards)} + index")
    print(f"stories placed: {total} of {len(articles)}")
    print("homepage ward picker: moved below Top stories" if homepage_moved
          else "homepage ward picker: already in place or unavailable")
    for ward in sorted(counts, key=lambda w: -counts[w])[:6]:
        print(f"   {counts[ward]:>3}  {ward}")
    empty = [w for w, n in counts.items() if not n]
    if empty:
        print(f"wards with no stories: {len(empty)} ({', '.join(sorted(empty)[:4])}...)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
