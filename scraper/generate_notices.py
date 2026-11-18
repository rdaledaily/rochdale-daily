#!/usr/bin/env python3
"""Build /notices/: free death notices and obituaries.

Rochdale Daily publishes death notices and obituaries free, forever, for
families and funeral directors (editor, 18 Nov 2026). Notices arrive by
email to news@ and are checked with the funeral director or family before
they go up. Each checked notice is one JSON file, notices/data/<slug>.json:

  {
    "slug": "jane-smith-2026-11-20",         # lowercase-hyphenated, unique
    "kind": "death_notice",                   # or "obituary"
    "name": "Jane Smith",
    "age": 84,                                # optional
    "town": "Heywood",                        # optional
    "died": "2026-11-15",                     # YYYY-MM-DD
    "published": "2026-11-20",                # YYYY-MM-DD
    "text": "Peacefully at home ...",         # plain text; blank lines split paragraphs
    "funeral": "Service at ... on ...",       # optional, plain text
    "funeral_director": "Mitchell Funeral Services",   # optional
    "donations": "Springhill Hospice",        # optional
    "verified_with": "funeral director"       # required: who confirmed it
  }

Notices are never articles: they never reach the front page, the newsletter,
RSS or the news sitemap. The index and each notice are in the XML sitemap.
Text is escaped, never treated as HTML, because it comes from the public.
A notice without "verified_with" is skipped and reported, never published.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from generate_category_pages import FOOT, SITE, chrome_head, esc, load_css

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "notices" / "data"
OUTPUT_DIR = ROOT / "notices"
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
KINDS = {"death_notice": "Death notice", "obituary": "Obituary"}
REQUIRED = ("slug", "kind", "name", "died", "published", "text", "verified_with")

NOTICES_CSS = (
    ".nt-body{max-width:720px}.nt-body p{font-size:17px;line-height:1.65}"
    ".nt-list{list-style:none;padding:0;margin:0}.nt-list li{border-top:1px solid var(--line);padding:14px 0}"
    ".nt-list a{font-family:var(--font-display);font-size:21px;font-weight:700;color:var(--ink);text-decoration:none}"
    ".nt-list a:hover{text-decoration:underline;text-underline-offset:3px}.nt-list p{margin:4px 0 0;color:var(--muted)}"
    ".nt-facts{border-left:4px solid var(--line);padding:6px 14px;margin:18px 0}.nt-facts p{margin:4px 0;font-size:16px}"
    ".nt-note{border-left:4px solid var(--accent);padding:10px 14px;background:var(--card,#fff);margin:18px 0}"
    ".nt-note a,.nt-body a{color:var(--accent);font-weight:600}"
)

SUBMIT_NOTE = (
    '<div class="nt-note"><p><strong>Death notices and obituaries are free, forever.</strong> '
    'Families and funeral directors can send a notice to '
    '<a href="mailto:news@rochdaledaily.co.uk">news@rochdaledaily.co.uk</a> with the funeral details and, '
    'if they wish, a photo. We check every notice with the funeral director or family before it goes online. '
    'There is no charge, and notices stay online permanently.</p></div>'
)


def nice_date(value: str) -> str:
    return date.fromisoformat(value).strftime("%-d %B %Y")


def load_notices(data_dir: Path = DATA_DIR) -> tuple[list[dict], list[str]]:
    notices, problems, seen = [], [], set()
    if not data_dir.is_dir():
        return [], []
    for path in sorted(data_dir.glob("*.json")):
        try:
            n = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            problems.append(f"{path.name}: invalid JSON ({exc})")
            continue
        missing = [k for k in REQUIRED if not n.get(k)]
        if missing:
            problems.append(f"{path.name}: missing {', '.join(missing)}")
            continue
        if not SLUG_RE.match(str(n["slug"])) or n["slug"] != path.stem or n["slug"] in seen:
            problems.append(f"{path.name}: slug must match the file name, be unique and lowercase-hyphenated")
            continue
        if n["kind"] not in KINDS:
            problems.append(f"{path.name}: kind must be death_notice or obituary")
            continue
        try:
            date.fromisoformat(str(n["died"]))
            date.fromisoformat(str(n["published"]))
        except ValueError:
            problems.append(f"{path.name}: died and published must be YYYY-MM-DD")
            continue
        seen.add(n["slug"])
        notices.append(n)
    notices.sort(key=lambda n: (n["published"], n["name"]), reverse=True)
    return notices, problems


def headline(n: dict) -> str:
    age = f", {int(n['age'])}" if str(n.get("age") or "").isdigit() else ""
    town = f", {n['town']}" if n.get("town") else ""
    return f"{n['name']}{age}{town}"


def paragraphs(text: str) -> str:
    return "".join(f"<p>{esc(p.strip())}</p>" for p in re.split(r"\n\s*\n", str(text)) if p.strip())


def photo_markup(n: dict) -> str:
    """A photo the family sent, if it is in the card library (email intake puts it there)."""
    photo = str(n.get("photo") or "")
    if not re.fullmatch(r"assets/img/cards/[A-Za-z0-9._-]+\.(jpg|jpeg|png|webp)", photo) or not (ROOT / photo).exists():
        return ""
    return (f'<figure class="nt-photo"><img src="/{esc(photo)}" alt="{esc(n["name"])}" loading="lazy" '
            'style="max-width:320px;width:100%;height:auto"></figure>')


def render_notice(n: dict) -> str:
    canonical = f"{SITE}/notices/{n['slug']}.html"
    kind = KINDS[n["kind"]]
    facts = [f"<p><strong>Died:</strong> {esc(nice_date(n['died']))}</p>"]
    for key, label in (("funeral", "Funeral"), ("funeral_director", "Funeral director"), ("donations", "Donations")):
        if n.get(key):
            facts.append(f"<p><strong>{label}:</strong> {esc(n[key])}</p>")
    parts = [
        f'<span class="rd-kicker">{esc(kind)}</span>',
        f'<h1>{esc(headline(n))}</h1>',
        f'<p class="rd-meta">Published {esc(nice_date(n["published"]))} · <a href="/notices/">All notices</a></p>',
        '<div class="nt-body">', photo_markup(n), paragraphs(n["text"]),
        f'<div class="nt-facts">{"".join(facts)}</div>',
        SUBMIT_NOTE, '</div>',
    ]
    title = f"{n['name']}: {kind.lower()}"
    if len(title) > 53:
        title = n["name"][:53]
    description = f"{kind} for {headline(n)}, who died on {nice_date(n['died'])}."
    json_ld = json.dumps({
        "@context": "https://schema.org", "@type": "WebPage", "name": f"{kind}: {headline(n)}",
        "url": canonical, "datePublished": n["published"],
        "isPartOf": {"@type": "WebSite", "name": "Rochdale Daily", "url": SITE + "/"},
        "breadcrumb": {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Rochdale Daily", "item": SITE + "/"},
            {"@type": "ListItem", "position": 2, "name": "Death notices", "item": f"{SITE}/notices/"},
            {"@type": "ListItem", "position": 3, "name": headline(n), "item": canonical},
        ]},
    }, ensure_ascii=False).replace("</", "<\\/")
    return chrome_head(title, description, canonical, load_css() + NOTICES_CSS, json_ld) + "".join(parts) + FOOT


def render_index(notices: list[dict]) -> str:
    canonical = f"{SITE}/notices/"
    if notices:
        items = "".join(
            f'<li><a href="/notices/{esc(n["slug"])}.html">{esc(headline(n))}</a>'
            f'<p>{esc(KINDS[n["kind"]])} · died {esc(nice_date(n["died"]))}</p></li>'
            for n in notices)
        listing = f'<ul class="nt-list">{items}</ul>'
    else:
        listing = '<p class="rd-meta">No notices have been published yet.</p>'
    parts = [
        '<span class="rd-kicker">Notices</span><h1>Rochdale death notices and obituaries</h1>',
        '<p class="rd-lede">Death notices and obituaries for Rochdale, Heywood, Middleton, Littleborough, '
        'Milnrow, Wardle and the rest of the borough.</p>',
        SUBMIT_NOTE, listing,
        '<p class="rd-links"><a href="/guides/death-notices-funerals-rochdale.html">Guide: registering a death, '
        'funerals and funeral directors in Rochdale</a></p>',
    ]
    json_ld = json.dumps({
        "@context": "https://schema.org", "@type": "CollectionPage",
        "name": "Rochdale death notices and obituaries", "url": canonical,
        "isPartOf": {"@type": "WebSite", "name": "Rochdale Daily", "url": SITE + "/"},
    }, ensure_ascii=False)
    return chrome_head("Rochdale death notices and obituaries",
                       "Free death notices and obituaries for the Rochdale borough, from Rochdale Daily.",
                       canonical, load_css() + NOTICES_CSS, json_ld) + "".join(parts) + FOOT


def notice_slugs(data_dir: Path = DATA_DIR) -> list[str]:
    return [n["slug"] for n in load_notices(data_dir)[0]]


def main() -> list[str]:
    notices, problems = load_notices()
    for problem in problems:
        print(f"Notice skipped: {problem}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    for n in notices:
        (OUTPUT_DIR / f"{n['slug']}.html").write_text(render_notice(n), encoding="utf-8")
        written.append(f"notices/{n['slug']}.html")
    (OUTPUT_DIR / "index.html").write_text(render_index(notices), encoding="utf-8")
    written.append("notices/index.html")
    print(f"Notices written: {len(notices)}")
    return written


if __name__ == "__main__":
    main()
