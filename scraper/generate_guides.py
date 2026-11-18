#!/usr/bin/env python3
"""Build /guides/: Rochdale Daily's evergreen local guides.

Rochdale Online still ranks for the borough's practical searches years after
it stopped publishing: "rochdale obituaries" (2,100 UK searches a month),
"hsbc rochdale" (450), "restaurants in rochdale", "charity shops rochdale"
(Ahrefs, November 2026). Its pages are out of date and the domain now
promotes gambling. These guides answer the same questions with checked,
current facts.

Each guide is one JSON file in guides/data/<slug>.json, written by the
editor (or Claude, checked against named sources):

  {
    "slug": "death-notices-funerals-rochdale",
    "title": "...",                 # the H1
    "seo_title": "...",             # <title>, <= 53 chars before the suffix
    "description": "...",           # meta description
    "kicker": "Guide",
    "checked": "2026-11-18",        # when every fact was last checked
    "lede": "...",
    "sections": [{"heading": "...", "html": "<p>...</p>"}],
    "sources": [{"name": "...", "url": "https://..."}]
  }

Guides are NOT articles: they never enter articles.json, so they never reach
the front page, the newsletter, RSS or the news sitemap (editor, 18 Nov 2026).
They are listed in the XML sitemap and on /guides/.

Run inside generate_pages.main(), like the section hubs, so every lane
rebuilds them. A guide whose JSON is invalid is skipped and reported, never
half-written.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from generate_category_pages import FOOT, SITE, chrome_head, esc, load_css

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "guides" / "data"
OUTPUT_DIR = ROOT / "guides"
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
REQUIRED = ("slug", "title", "seo_title", "description", "checked", "lede", "sections", "sources")

GUIDE_CSS = (
    ".guide-body{max-width:760px}.guide-body h2{margin:34px 0 12px;padding-top:10px;border-top:3px solid var(--ink);"
    "font-family:var(--font-display);font-size:24px;letter-spacing:-.01em}"
    ".guide-body p,.guide-body li{font-size:17px;line-height:1.6;color:var(--ink)}"
    ".guide-body ul,.guide-body ol{padding-left:22px}.guide-body li{margin:0 0 6px}"
    ".guide-body a{color:var(--accent);font-weight:600}"
    ".guide-body table{width:100%;border-collapse:collapse;font-size:15px;margin:6px 0 10px}"
    ".guide-body th,.guide-body td{text-align:left;padding:10px 8px;border-top:1px solid var(--line);vertical-align:top}"
    ".guide-body thead th{font-family:var(--font-ui);font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);border-top:0}"
    ".guide-scroll{overflow-x:auto}.guide-note{border-left:4px solid var(--accent);padding:8px 14px;background:var(--card,#fff)}"
    ".guide-checked{margin:0 0 20px}.guide-sources{margin-top:30px}.guide-sources li{font-size:15px}"
    ".guide-list{list-style:none;padding:0;margin:0}.guide-list li{border-top:1px solid var(--line);padding:14px 0}"
    ".guide-list a{font-family:var(--font-display);font-size:20px;font-weight:700;color:var(--ink);text-decoration:none}"
    ".guide-list a:hover{text-decoration:underline;text-underline-offset:3px}.guide-list p{margin:4px 0 0;color:var(--muted)}"
)


def load_guides(data_dir: Path = DATA_DIR) -> tuple[list[dict], list[str]]:
    guides, problems = [], []
    for path in sorted(data_dir.glob("*.json")):
        try:
            guide = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            problems.append(f"{path.name}: invalid JSON ({exc})")
            continue
        missing = [k for k in REQUIRED if not guide.get(k)]
        if missing:
            problems.append(f"{path.name}: missing {', '.join(missing)}")
            continue
        if not SLUG_RE.match(str(guide["slug"])) or guide["slug"] != path.stem:
            problems.append(f"{path.name}: slug must match the file name and be lowercase-hyphenated")
            continue
        try:
            date.fromisoformat(str(guide["checked"]))
        except ValueError:
            problems.append(f"{path.name}: checked must be YYYY-MM-DD")
            continue
        if len(str(guide["seo_title"])) > 53:
            problems.append(f"{path.name}: seo_title over 53 characters")
            continue
        guides.append(guide)
    return guides, problems


def checked_label(value: str) -> str:
    return date.fromisoformat(value).strftime("%-d %B %Y")


def render_guide(guide: dict) -> str:
    slug = guide["slug"]
    canonical = f"{SITE}/guides/{slug}.html"
    parts = [
        f'<span class="rd-kicker">{esc(guide.get("kicker") or "Guide")}</span>',
        f'<h1>{esc(guide["title"])}</h1>',
        f'<p class="rd-lede">{esc(guide["lede"])}</p>',
        f'<p class="rd-meta guide-checked">Checked {esc(checked_label(guide["checked"]))} · '
        '<a href="/guides/">All guides</a></p>',
        '<div class="guide-body">',
    ]
    for section in guide["sections"]:
        parts.append(f'<h2>{esc(section.get("heading"))}</h2>')
        # Section HTML is editor-written and reviewed in the pull request,
        # like manual article bodies; it is not reader input.
        parts.append(str(section.get("html") or ""))
    sources = "".join(
        f'<li><a href="{esc(s.get("url"))}" rel="noopener" target="_blank">{esc(s.get("name"))}</a></li>'
        for s in guide["sources"] if s.get("url")
    )
    parts.append(
        '<section class="guide-sources"><h2>Sources</h2>'
        f'<ul>{sources}</ul>'
        '<p>Spotted something out of date? Email <a href="mailto:news@rochdaledaily.co.uk">news@rochdaledaily.co.uk</a> '
        'and we will check and correct it.</p></section></div>'
    )
    json_ld = json.dumps({
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": guide["title"],
        "headline": guide["title"],
        "description": guide["description"],
        "url": canonical,
        "dateModified": guide["checked"],
        "isPartOf": {"@type": "WebSite", "name": "Rochdale Daily", "url": SITE + "/"},
        "breadcrumb": {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Rochdale Daily", "item": SITE + "/"},
            {"@type": "ListItem", "position": 2, "name": "Guides", "item": f"{SITE}/guides/"},
            {"@type": "ListItem", "position": 3, "name": guide["title"], "item": canonical},
        ]},
    }, ensure_ascii=False).replace("</", "<\\/")
    return chrome_head(guide["seo_title"], guide["description"], canonical, load_css() + GUIDE_CSS, json_ld) \
        + "".join(parts) + FOOT


def render_index(guides: list[dict]) -> str:
    canonical = f"{SITE}/guides/"
    items = "".join(
        f'<li><a href="/guides/{esc(g["slug"])}.html">{esc(g["title"])}</a><p>{esc(g["description"])}</p></li>'
        for g in sorted(guides, key=lambda g: g["title"])
    )
    parts = [
        '<span class="rd-kicker">Guides</span><h1>Rochdale guides</h1>',
        '<p class="rd-lede">Practical guides to life in the Rochdale borough: Rochdale, Heywood, Middleton, '
        'Littleborough, Milnrow and Wardle. Every fact is checked against its source, and each guide says when.</p>',
        f'<ul class="guide-list">{items}</ul>',
        '<p class="rd-links"><a href="/weather/">Weather</a> · <a href="/roadworks.html">Roadworks</a> · '
        '<a href="/whats-on.html">What\'s on</a></p>',
    ]
    json_ld = json.dumps({
        "@context": "https://schema.org", "@type": "CollectionPage", "name": "Rochdale guides", "url": canonical,
        "isPartOf": {"@type": "WebSite", "name": "Rochdale Daily", "url": SITE + "/"},
    }, ensure_ascii=False)
    return chrome_head("Rochdale guides: practical local information",
                       "Practical, checked guides to the Rochdale borough from Rochdale Daily.",
                       canonical, load_css() + GUIDE_CSS, json_ld) + "".join(parts) + FOOT


def guide_slugs(data_dir: Path = DATA_DIR) -> list[str]:
    guides, _ = load_guides(data_dir)
    return [g["slug"] for g in guides]


def main() -> list[str]:
    guides, problems = load_guides()
    for problem in problems:
        print(f"Guide skipped: {problem}")
    if not guides:
        print("No guides to write.")
        return []
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    for guide in guides:
        (OUTPUT_DIR / f"{guide['slug']}.html").write_text(render_guide(guide), encoding="utf-8")
        written.append(f"guides/{guide['slug']}.html")
    (OUTPUT_DIR / "index.html").write_text(render_index(guides), encoding="utf-8")
    written.append("guides/index.html")
    print(f"Guides written: {len(guides)}")
    return written


if __name__ == "__main__":
    main()
