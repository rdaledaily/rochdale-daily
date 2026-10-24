#!/usr/bin/env python3
"""Link stories to the paper's place and topic hubs, and keep those hubs complete.

Measured 20 October 2026: not one of 1,534 indexable story bodies linked to
anything else on the site. Every internal link sat in menus, "read next" boxes
and lists, which search engines weigh least. Links inside the text are what
tell Google which page is the paper's authority on Heywood, on crime, on
Reform UK.

What this does, on every page, every run:

  * In each story's own text (the article-copy paragraphs only; never
    headlines, standfirsts, captions, sources or existing links) the FIRST
    mention of each place or topic below becomes a link to its hub. At most
    MAX_LINKS per story. Nothing is reworded: the words stay exactly as they
    are, only wrapped in a link.
  * Place names are only linked when they stand as a place: not next to
    another capitalised name ("Glenn Middleton", "Heywood Road").
  * Topic hubs that have no page of their own are built at /news/topics/<slug>,
    listing every indexable story that mentions the topic, newest first.
    Section pages that are hubs (/news/crime and the like) get the same full
    list appended, because they otherwise show only the latest few stories.
  * A hub is only created, and only linked to, once it has MIN_STORIES
    stories. The same rule applies to every political party.

Auto links carry class="rd-auto-link" and are removed and re-applied each run,
so changing the rules here changes every page. Applied by
normalise_public_theme.py after the archive sweep, so only indexable pages are
listed and linked.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from archive_integrity import _indexable
from generate_ward_pages import FOOT, chrome_head, esc, load_css, paste_friendly

SITE = "https://rochdaledaily.co.uk"
TOPICS_DIR = Path("news") / "topics"
MAX_LINKS = 6
MIN_STORIES = 5
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()

# kind: "place" (guarded against people and street names), "topic".
# page: an existing page (path relative to the site root) or None to build one
#       at /news/topics/<slug>.
# full_list: append the complete story list to an existing hub page.
HUBS: list[dict] = [
    # Townships and places with their own page.
    {"slug": "heywood", "name": "Heywood", "kind": "place", "page": "heywood.html", "full_list": True, "pattern": r"Heywood|Darnhill"},
    {"slug": "middleton", "name": "Middleton", "kind": "place", "page": "middleton.html", "full_list": True, "pattern": r"Middleton"},
    {"slug": "littleborough", "name": "Littleborough", "kind": "place", "page": "littleborough.html", "full_list": True,
     "pattern": r"Littleborough|Smithy Bridge"},
    {"slug": "milnrow", "name": "Milnrow and Newhey", "kind": "place", "page": "milnrow.html", "full_list": True, "pattern": r"Milnrow|Newhey"},
    # Wards whose name is a place people search for.
    {"slug": "norden", "name": "Norden", "kind": "place", "page": "wards/norden.html", "full_list": True, "pattern": r"Norden"},
    {"slug": "bamford", "name": "Bamford", "kind": "place", "page": "wards/bamford.html", "full_list": True, "pattern": r"Bamford"},
    {"slug": "castleton", "name": "Castleton", "kind": "place", "page": "wards/castleton.html", "full_list": True, "pattern": r"Castleton"},
    {"slug": "healey", "name": "Healey", "kind": "place", "page": "wards/healey.html", "full_list": True, "pattern": r"Healey"},
    {"slug": "kingsway", "name": "Kingsway", "kind": "place", "page": "wards/kingsway.html", "full_list": True, "pattern": r"Kingsway"},
    {"slug": "kirkholt", "name": "Balderstone and Kirkholt", "kind": "place", "page": "wards/balderstone-and-kirkholt.html", "full_list": True,
     "pattern": r"Kirkholt|Balderstone"},
    {"slug": "spotland", "name": "Spotland and Falinge", "kind": "place", "page": "wards/spotland-and-falinge.html", "full_list": True,
     "pattern": r"Falinge|Spotland(?! Stadium)"},
    {"slug": "smallbridge", "name": "Smallbridge and Firgrove", "kind": "place", "page": "wards/smallbridge-and-firgrove.html", "full_list": True,
     "pattern": r"Smallbridge|Firgrove"},
    {"slug": "deeplish", "name": "Milkstone and Deeplish", "kind": "place", "page": "wards/milkstone-and-deeplish.html", "full_list": True,
     "pattern": r"Deeplish|Milkstone"},
    {"slug": "wardle", "name": "Wardle, Shore and West Littleborough", "kind": "place",
     "page": "wards/wardle-shore-and-west-littleborough.html", "full_list": True, "pattern": r"Wardle"},
    # Sections that are already hubs: link to them and give them the full list.
    {"slug": "crime", "name": "Crime and policing", "kind": "topic", "page": "news/crime.html", "full_list": True,
     "pattern": r"Greater Manchester Police|GMP|police|arrested|sentenced|jailed|charged with"},
    {"slug": "schools", "name": "Schools and education", "kind": "topic", "page": "news/education.html", "full_list": True,
     "pattern": r"schools?|Ofsted|pupils"},
    {"slug": "health", "name": "Health and the NHS", "kind": "topic", "page": "news/health.html", "full_list": True,
     "pattern": r"NHS|Rochdale Infirmary|Fairfield General"},
    {"slug": "roads", "name": "Roads and roadworks", "kind": "topic", "page": "news/traffic.html", "full_list": True,
     "pattern": r"roadworks|road closures?"},
    {"slug": "transport", "name": "Buses, trams and trains", "kind": "topic", "page": "news/transport.html", "full_list": True,
     "pattern": r"Bee Network|Metrolink"},
    # Umbrella topics with no page of their own: built at /news/topics/<slug>.
    {"slug": "rochdale-borough-council", "name": "Rochdale Borough Council", "kind": "topic", "page": None,
     "pattern": r"Rochdale Borough Council|Rochdale Council"},
    {"slug": "rochdale-afc", "name": "Rochdale AFC", "kind": "topic", "page": None, "pattern": r"Rochdale AFC|Crown Oil Arena"},
    {"slug": "rochdale-hornets", "name": "Rochdale Hornets", "kind": "topic", "page": None, "pattern": r"Rochdale Hornets|Hornets"},
    {"slug": "housing", "name": "Housing", "kind": "topic", "page": None, "pattern": r"housing"},
    {"slug": "planning", "name": "Planning applications", "kind": "topic", "page": None,
     "pattern": r"planning (?:application|permission|committee)s?"},
    {"slug": "atom-valley", "name": "Atom Valley and the Northern Gateway", "kind": "topic", "page": None,
     "pattern": r"Atom Valley|Northern Gateway"},
    {"slug": "flooding", "name": "Flooding", "kind": "topic", "page": None, "pattern": r"flood (?:risk|warnings?|alerts?|defences?|resilience|water|damage)|floods|flooding(?! (?:the|it|them|our|their|his|her)\b)|flooded"},
    {"slug": "greater-manchester-mayor", "name": "The Greater Manchester mayor", "kind": "topic", "page": None,
     "pattern": r"mayoral election|Mayor of Greater Manchester|Greater Manchester mayor"},
    # Political parties: one rule for every party.
    {"slug": "labour", "name": "Labour", "kind": "party", "page": None, "pattern": r"Labour(?= (?:Party|councillor|candidate|group|MP|leader|government)|\b(?! (?:market|shortages?|costs?)))"},
    {"slug": "reform-uk", "name": "Reform UK", "kind": "party", "page": None,
     "pattern": r"Reform UK|Reform(?= (?:councillors?|candidates?|party|group|leader|MPs?)\b)"},
    {"slug": "conservatives", "name": "The Conservatives", "kind": "party", "page": None, "pattern": r"Conservatives?(?: Party)?|Tories|Tory"},
    {"slug": "liberal-democrats", "name": "The Liberal Democrats", "kind": "party", "page": None, "pattern": r"Liberal Democrats?|Lib Dems?"},
    {"slug": "green-party", "name": "The Green Party", "kind": "party", "page": None, "pattern": r"Green Party|Greens(?= (?:councillor|candidate)s?\b)"},
    {"slug": "workers-party", "name": "The Workers Party", "kind": "party", "page": None, "pattern": r"Workers Party(?: of Britain)?"},
]

_BODY_START = '<div class="article-copy">'
# The story's own text ends where the Background box (story_background.py)
# begins: those cited facts are context, not what the story is about, so they
# neither put a story in a topic hub nor take auto links.
_BODY_END_RE = re.compile(r'<div class="rd-background"|<details class="article-sources"|<section class="(?:comments|read-next|editorial-legal|report-box)')
_PARA_RE = re.compile(r"<p>(.*?)</p>", re.S)
_AUTO_RE = re.compile(r'<a class="rd-auto-link" href="[^"]*">(.*?)</a>', re.S)
_TOKEN_RE = re.compile(r"(<[^>]+>)")
# A capitalised neighbour that is not just the start of a sentence or a common
# lead-in word means the place name is part of another name.
_LEAD_INS = {"In", "At", "From", "To", "Of", "The", "And", "Near", "Across", "Around", "Through", "Into", "On", "For",
             "North", "South", "East", "West", "Central", "Upper", "Lower", "Greater", "Rochdale", "Borough", "By", "With"}


def hub_url(hub: dict) -> str:
    if hub["page"]:
        path = hub["page"][:-5]
        return "/" + path
    return f"/news/topics/{hub['slug']}"


def _compiled(hub: dict) -> re.Pattern[str]:
    flags = 0 if hub["kind"] in ("place", "party") or any(c.isupper() for c in hub["pattern"]) else re.I
    return re.compile(r"\b(?:" + hub["pattern"] + r")\b", flags)


def body_span(html: str) -> tuple[int, int] | None:
    start = html.find(_BODY_START)
    if start < 0:
        return None
    end = _BODY_END_RE.search(html, start)
    return start, end.start() if end else len(html)


def body_text(html: str) -> str:
    span = body_span(html)
    if not span:
        return ""
    return " ".join(re.sub(r"<[^>]+>", " ", html[span[0]:span[1]]).split())


def _stands_alone(text: str, start: int, end: int, kind: str) -> bool:
    if kind != "place":
        return True
    before = re.search(r"([A-Za-z][\w'’-]*)\W{0,2}$", text[:start])
    after = re.match(r"^\W{0,2}([A-Za-z][\w'’-]*)", text[end:])
    joined_before = before and re.search(r"\w\s+$|\w$", text[:start])
    if before and joined_before and before.group(1)[0].isupper() and before.group(1) not in _LEAD_INS:
        # A capitalised word straight before: "Glenn Middleton". A sentence
        # break between them ("... Rochdale. Middleton ...") is fine.
        if not re.search(r"[.!?:;]\s*$", text[:start]):
            return False
    if after and re.match(r"^\s+[A-Z]", text[end:]) and after.group(1)[0].isupper():
        return False      # "Heywood Road", "Middleton Arena"
    return True


def _link_text(text: str, hubs: list[tuple[dict, re.Pattern[str]]], used: set[str], budget: list[int]) -> str:
    """Find each unused hub's first standalone mention in the ORIGINAL text, then wrap them all at once."""
    found: list[tuple[int, int, dict]] = []
    for hub, pattern in hubs:
        if hub["slug"] in used:
            continue
        for match in pattern.finditer(text):
            if _stands_alone(text, match.start(), match.end(), hub["kind"]):
                found.append((match.start(), match.end(), hub))
                break
    chosen: list[tuple[int, int, dict]] = []
    for start, end, hub in sorted(found, key=lambda f: f[0]):
        if budget[0] <= 0:
            break
        if chosen and start < chosen[-1][1]:
            continue          # overlaps a link already placed
        chosen.append((start, end, hub))
        used.add(hub["slug"])
        budget[0] -= 1
    for start, end, hub in reversed(chosen):
        text = text[:start] + f'<a class="rd-auto-link" href="{hub_url(hub)}">{text[start:end]}</a>' + text[end:]
    return text


def link_paragraph(inner: str, hubs: list[tuple[dict, re.Pattern[str]]], used: set[str], budget: list[int]) -> str:
    parts = _TOKEN_RE.split(inner)
    depth = 0
    for i, part in enumerate(parts):
        if part.startswith("<"):
            if re.match(r"<a\b", part, re.I):
                depth += 1
            elif re.match(r"</a>", part, re.I):
                depth = max(0, depth - 1)
            continue
        if depth or not part.strip() or budget[0] <= 0:
            continue
        parts[i] = _link_text(part, hubs, used, budget)
    return "".join(parts)


def unlink(html: str) -> str:
    return _AUTO_RE.sub(lambda m: m.group(1), html)


def link_article(html: str, hubs: list[tuple[dict, re.Pattern[str]]]) -> str:
    html = unlink(html)
    span = body_span(html)
    if not span or not hubs:
        return html
    start, end = span
    used: set[str] = set()
    budget = [MAX_LINKS]

    def para(match: re.Match[str]) -> str:
        return "<p>" + link_paragraph(match.group(1), hubs, used, budget) + "</p>"

    return html[:start] + _PARA_RE.sub(para, html[start:end]) + html[end:]


def membership(root: Path, pages: dict[str, str]) -> tuple[dict[str, list[dict]], list[dict]]:
    """hub slug -> stories (newest first) that mention it; and all indexable stories."""
    try:
        index = json.loads((root / "archive-index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        index = []
    meta = {str(item.get("slug")): item for item in index if isinstance(item, dict) and item.get("slug")}
    compiled = [(hub, _compiled(hub)) for hub in HUBS]
    members: dict[str, list[dict]] = defaultdict(list)
    stories = []
    for slug, html in pages.items():
        if slug not in meta or not _indexable(html, slug):
            continue
        item = meta[slug]
        text = f'{item.get("title") or ""} {body_text(html)}'
        stories.append(item)
        for hub, pattern in compiled:
            if any(_stands_alone(text, m.start(), m.end(), hub["kind"]) for m in pattern.finditer(text)):
                members[hub["slug"]].append(item)
    for items in members.values():
        items.sort(key=lambda item: (str(item.get("published_at")), str(item.get("slug"))), reverse=True)
    return dict(members), stories


def _story(item: dict) -> str:
    day = str(item.get("published_at") or "")[:10]
    when = f"{int(day[8:10])} {MONTHS[int(day[5:7]) - 1]} {day[:4]}" if re.match(r"\d{4}-\d{2}-\d{2}", day) else ""
    description = str(item.get("description") or "").strip()
    return (f'<li><a href="/articles/{esc(item.get("slug"))}">{esc(item.get("title"))}</a>'
            f'<p><span class="rd-meta">{when} · {esc(item.get("category") or "News")}</span>'
            f'{" — " + esc(description[:160]) if description else ""}</p></li>')


LIST_CSS = (
    '<style>.rd-archive-list{list-style:none;margin:0;padding:0}'
    '.rd-archive-list li{padding:14px 0;border-top:1px solid var(--line)}'
    '.rd-archive-list a{font-family:var(--font-display);font-size:19px;line-height:1.25;color:var(--ink);text-decoration:none}'
    '.rd-archive-list a:hover{text-decoration:underline;text-underline-offset:3px}'
    '.rd-archive-list p{margin:4px 0 0;color:var(--muted);font-size:14px;line-height:1.5}'
    '.rd-topics{columns:3 200px;margin:0;padding:0;list-style:none}.rd-topics li{padding:4px 0}'
    '.rd-topics a{color:var(--accent);font-weight:600}</style>'
)


def topic_page(hub: dict, items: list[dict], css: str) -> str:
    name = hub["name"]
    noun = "Rochdale" if hub["kind"] != "party" else "Rochdale borough"
    title = f"{name} in {noun}: news and coverage" if hub["kind"] == "party" else f"{name}: Rochdale news and coverage"
    head = chrome_head(title, f"Every Rochdale Daily story about {name}: {len(items)} reports from across Rochdale borough, newest first.",
                       f"{SITE}/news/topics/{hub['slug']}", css, back_href="/news/topics/", back_label="All topics")
    return paste_friendly(
        head.replace("</head>", LIST_CSS + "</head>", 1)
        + f'<span class="rd-kicker">Topic</span><h1>{esc(name)}</h1>'
        + f'<p class="rd-lede">Every Rochdale Daily story that mentions {esc(name)}: {len(items)} reports, newest first. '
        + 'Stories are listed because they mention the subject; inclusion is not a judgement about it.</p>'
        + '<ol class="rd-archive-list">' + "".join(_story(item) for item in items) + "</ol>"
        + '<p class="rd-links"><a href="/news/topics/">All topics</a> · <a href="/news/archive/">The archive by month</a></p>'
        + FOOT
    )


def topics_index(live_hubs: list[tuple[dict, int]], css: str) -> str:
    head = chrome_head("Rochdale news by topic and place", "Rochdale Daily's coverage gathered by place and by subject.",
                       f"{SITE}/news/topics/", css, back_href="/news/archive/", back_label="Archive by month")
    groups = (("place", "Places"), ("topic", "Subjects"), ("party", "Political parties"))
    body = ""
    for kind, label in groups:
        rows = [(hub, n) for hub, n in live_hubs if hub["kind"] == kind]
        if rows:
            body += f'<h2 class="rd-h2">{label}</h2><ul class="rd-topics">' + "".join(
                f'<li><a href="{hub_url(hub)}">{esc(hub["name"])}</a> ({n})</li>' for hub, n in rows) + "</ul>"
    return paste_friendly(head.replace("</head>", LIST_CSS + "</head>", 1)
                          + '<span class="rd-kicker">Topics</span><h1>Rochdale news by topic and place</h1>'
                          + '<p class="rd-lede">Every story Rochdale Daily has published, gathered by where it happened and what it is about.</p>'
                          + body + FOOT)


START, END = "<!-- rd-hub-full-list -->", "<!-- /rd-hub-full-list -->"


def full_list_block(hub: dict, items: list[dict]) -> str:
    return (f'{START}<section class="rd-page" aria-labelledby="rd-all-{hub["slug"]}" style="padding-top:0">'
            f'<h2 class="rd-h2" id="rd-all-{hub["slug"]}">All coverage: {esc(hub["name"])} ({len(items)})</h2>'
            f'{LIST_CSS}<ol class="rd-archive-list">' + "".join(_story(item) for item in items) + f"</ol></section>{END}")


def with_block(html: str, block: str) -> str:
    if START in html and END in html:
        return re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _: block, html, count=1, flags=re.S)
    return html.replace("</main>", block + "</main>", 1) if "</main>" in html else html


def build(root: Path) -> tuple[dict[Path, str], list[Path]]:
    """(pages to write, stale topic pages to remove)."""
    folder = root / "articles"
    if not folder.is_dir() or not (root / "archive-index.json").is_file():
        return {}, []
    files = {path.stem: path for path in folder.glob("*.html")}
    pages = {slug: path.read_text(encoding="utf-8", errors="ignore") for slug, path in files.items()}
    members, _ = membership(root, pages)
    css = load_css()
    out: dict[Path, str] = {}
    live: list[tuple[dict, int]] = []
    for hub in HUBS:
        items = members.get(hub["slug"], [])
        if len(items) < MIN_STORIES:
            continue
        if hub["page"]:
            page = root / hub["page"]
            if not page.is_file():
                continue
            if hub.get("full_list"):
                out[page] = with_block(page.read_text(encoding="utf-8"), full_list_block(hub, items))
        else:
            out[root / TOPICS_DIR / f"{hub['slug']}.html"] = topic_page(hub, items, css)
        live.append((hub, len(items)))
    if not live:
        return {}, []
    out[root / TOPICS_DIR / "index.html"] = topics_index(live, css)

    linkable = [(hub, _compiled(hub)) for hub, _ in live]
    for slug, html in pages.items():
        linked = link_article(html, linkable if _indexable(html, slug) else [])
        if linked != html:
            out[files[slug]] = linked
    keep = {root / TOPICS_DIR / f"{hub['slug']}.html" for hub, _ in live if not hub["page"]} | {root / TOPICS_DIR / "index.html"}
    stale = [p for p in (root / TOPICS_DIR).glob("*.html") if p not in keep] if (root / TOPICS_DIR).is_dir() else []
    return out, stale
