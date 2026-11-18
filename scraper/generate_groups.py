#!/usr/bin/env python3
"""Build /groups/: the Rochdale community directory.

Rochdale Online ran a "sites" section where local clubs, churches and
charities had a page. Dozens of outside sites (swimming.org, CAMRA, the
Methodist Church, Railfuture, the Federation of British Historic Vehicle
Clubs...) still link to those pages, but the domain now promotes gambling.
This directory gives each group a free, permanent entry on Rochdale Daily
that those sites can link to instead (editor, 18 Nov 2026).

Data: groups/data.json, {"checked": "YYYY-MM-DD", "groups": [...]}, each
group {slug, name, category, town, about, website}. Every entry is anchored
at /groups/#<slug>. Entries are free, forever; groups can ask to update or
remove theirs by email.

Like the guides, the directory is never an article: it never reaches the
front page, newsletter, RSS or news sitemap. It is listed in the XML sitemap.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from generate_category_pages import FOOT, SITE, chrome_head, esc, load_css

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "groups" / "data.json"
OUTPUT = ROOT / "groups" / "index.html"
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
CATEGORY_ORDER = (
    "Charities and community support", "Churches and faith", "Clubs and societies",
    "Sport and fitness", "Arts and music", "Schools", "Local businesses",
)

GROUPS_CSS = (
    ".dir-body{max-width:820px}.dir-body h2{margin:34px 0 8px;padding-top:10px;border-top:3px solid var(--ink);"
    "font-family:var(--font-display);font-size:24px;letter-spacing:-.01em}"
    ".dir-list{list-style:none;padding:0;margin:0}.dir-entry{border-top:1px solid var(--line);padding:14px 0;scroll-margin-top:80px}"
    ".dir-entry:target{background:var(--card,#fff);box-shadow:inset 4px 0 0 var(--accent);padding-left:12px}"
    ".dir-entry h3{margin:0;font-family:var(--font-display);font-size:20px}"
    ".dir-entry p{margin:4px 0 0;font-size:16px;line-height:1.5}.dir-town{color:var(--muted);font-size:14px}"
    ".dir-entry a{color:var(--accent);font-weight:600}"
    ".dir-jump{display:flex;flex-wrap:wrap;gap:8px 14px;margin:0 0 10px;padding:0;list-style:none}"
    ".dir-jump a{font-family:var(--font-ui);font-size:14px;color:var(--ink)}"
    ".dir-note{border-left:4px solid var(--accent);padding:10px 14px;background:var(--card,#fff);margin:18px 0}"
)


def category_anchor(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def load_groups(path: Path = DATA_PATH) -> tuple[str, list[dict], list[str]]:
    problems: list[str] = []
    data = json.loads(path.read_text(encoding="utf-8"))
    checked = str(data.get("checked") or "")
    date.fromisoformat(checked)
    groups, seen = [], set()
    for g in data.get("groups") or []:
        slug = str(g.get("slug") or "")
        if not SLUG_RE.match(slug) or slug in seen:
            problems.append(f"bad or duplicate slug: {slug!r}")
            continue
        if not g.get("name") or not g.get("about") or g.get("category") not in CATEGORY_ORDER:
            problems.append(f"{slug}: needs name, about and a known category")
            continue
        website = str(g.get("website") or "")
        if website and not website.startswith("https://"):
            problems.append(f"{slug}: website must be https")
            continue
        seen.add(slug)
        groups.append(g)
    return checked, groups, problems


def render(checked: str, groups: list[dict]) -> str:
    canonical = f"{SITE}/groups/"
    by_cat: dict[str, list[dict]] = {c: [] for c in CATEGORY_ORDER}
    for g in groups:
        by_cat[g["category"]].append(g)
    present = [c for c in CATEGORY_ORDER if by_cat[c]]
    parts = [
        '<span class="rd-kicker">Community</span><h1>Rochdale community directory</h1>',
        '<p class="rd-lede">Clubs, churches, charities, schools and local businesses across the Rochdale borough. '
        'Every listing is free, forever.</p>',
        f'<p class="rd-meta">Checked {esc(date.fromisoformat(checked).strftime("%-d %B %Y"))} · '
        f'{len(groups)} listings · <a href="/guides/">Guides</a></p>',
        '<div class="dir-note"><p><strong>Is your group here, or should it be?</strong> Listings are free and always will be. '
        'To add, correct or remove an entry, email <a href="mailto:news@rochdaledaily.co.uk">news@rochdaledaily.co.uk</a>. '
        'Got news, an event or a fundraiser? <a href="/submit-story.html">Send it to us</a> and we will cover it for free.</p></div>',
        '<ul class="dir-jump">' + "".join(
            f'<li><a href="#{category_anchor(c)}">{esc(c)}</a></li>' for c in present) + '</ul>',
        '<div class="dir-body">',
    ]
    for cat in present:
        parts.append(f'<h2 id="{category_anchor(cat)}">{esc(cat)}</h2><ul class="dir-list">')
        for g in sorted(by_cat[cat], key=lambda g: g["name"].lower()):
            town = f'<span class="dir-town">{esc(g["town"])}</span>' if g.get("town") else ""
            site = (f'<p><a href="{esc(g["website"])}" rel="noopener" target="_blank">Website</a></p>'
                    if g.get("website") else "")
            parts.append(
                f'<li class="dir-entry" id="{esc(g["slug"])}"><h3>{esc(g["name"])}</h3>{town}'
                f'<p>{esc(g["about"])}</p>{site}</li>')
        parts.append('</ul>')
    parts.append(
        '<p class="rd-links">Looking for something Rochdale Online used to cover? '
        '<a href="/guides/rochdale-online-closed.html">Where to find it now</a></p></div>')
    json_ld = json.dumps({
        "@context": "https://schema.org", "@type": "CollectionPage",
        "name": "Rochdale community directory", "url": canonical, "dateModified": checked,
        "isPartOf": {"@type": "WebSite", "name": "Rochdale Daily", "url": SITE + "/"},
        "mainEntity": {"@type": "ItemList", "numberOfItems": len(groups), "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": g["name"], "url": f"{canonical}#{g['slug']}"}
            for i, g in enumerate(groups)]},
    }, ensure_ascii=False).replace("</", "<\\/")
    return chrome_head("Rochdale community groups, clubs and charities",
                       "Free directory of Rochdale borough clubs, churches, charities, schools and local "
                       "businesses, from Rochdale Daily.",
                       canonical, load_css() + GROUPS_CSS, json_ld) + "".join(parts) + FOOT


def group_slugs(path: Path = DATA_PATH) -> list[str]:
    return [g["slug"] for g in load_groups(path)[1]]


def main() -> list[str]:
    if not DATA_PATH.exists():
        print("No community directory data.")
        return []
    checked, groups, problems = load_groups()
    for problem in problems:
        print(f"Directory entry skipped: {problem}")
    OUTPUT.write_text(render(checked, groups), encoding="utf-8")
    print(f"Community directory written: {len(groups)} listings")
    return ["groups/index.html"]


if __name__ == "__main__":
    main()
