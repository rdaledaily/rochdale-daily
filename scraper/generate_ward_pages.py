#!/usr/bin/env python3
"""Generate Rochdale Daily ward pages with councillors, portraits, votes and news."""
from __future__ import annotations

import html
import json
import re
import unicodedata
from pathlib import Path

from councillor_photos import build_local_portrait_map

ROOT = Path(__file__).resolve().parents[1]
WARD_MAP_PATH = ROOT / "ward_areas.json"
ARTICLES_PATH = ROOT / "articles.json"
VOTES_PATH = ROOT / "council_votes.json"
CSS_PATH = ROOT / "assets" / "css" / "site.css"
OUTPUT_DIR = ROOT / "wards"
SITE = "https://rochdaledaily.co.uk"
MAX_STORIES = 12
ARCHIVE_INDEX_PATH = ROOT / "archive-index.json"
PLACE_OUTPUT_DIR = ROOT

# Root-level place pages. heywood.html and milnrow.html began life as early
# prototypes pointing at a stylesheet that no longer existed, so they rendered
# unstyled. They are real places people search for, so they are now generated
# here from the same data as the ward pages: a township page draws on every
# ward inside it. The archive has no area tag, so older stories are matched on
# the place name appearing in the headline or standfirst -- a story with
# "Heywood" in its headline is a Heywood story.
PLACE_PAGES = {
    "heywood.html": {
        "name": "Heywood",
        "kind": "TOWNSHIP",
        "wards": ["North Heywood", "West Heywood"],
        "keywords": ["heywood", "darnhill", "hopwood"],
        "filter_area": "heywood-township",
        "description": "Heywood news from Rochdale Daily, with the councillors for North Heywood and West Heywood and what they have voted on.",
    },
    "milnrow.html": {
        "name": "Milnrow and Newhey",
        "kind": "WARD",
        "wards": ["Milnrow and Newhey"],
        "keywords": ["milnrow", "newhey"],
        "filter_area": "pennines-township",
        "description": "Milnrow and Newhey news from Rochdale Daily, with the ward's councillors and what they have voted on.",
    },
}
MAX_PLACE_STORIES = 18
MAX_ARCHIVE_STORIES = 30

SIDE_LABEL = {"for": "Voted for", "against": "Voted against", "abstain": "Abstained"}
SIDE_CLASS = {"for": "dem-vote-for", "against": "dem-vote-against", "abstain": "dem-vote-abstain"}


def esc(value):
    return html.escape(str(value or ""), quote=True)


def slugify(value):
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower())


def read(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


TOKEN_IMPORT_PATTERN = re.compile(
    r'@import\s+url\(\s*[\'"]?/?assets/css/rd-tokens\.css[\'"]?\s*\)\s*;\s*', re.I
)

# Ward pages are a primary destination in the new navigation, so they have to
# look like the rest of the paper rather than falling back to the browser's
# default sans. These pages never load editorial-theme.css, so the tokens and
# the two faces are linked here explicitly.
HEAD_ASSETS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700'
    '&family=Libre+Franklin:wght@600;700;800&display=swap" rel="stylesheet">'
    '<link rel="stylesheet" href="/assets/css/rd-tokens.css">'
)


def load_css():
    """site.css for inlining, with the token @import lifted into a <link>.

    An @import inside an inline <style> is invisible to the preload scanner, so
    it costs a serial round trip before the page has a colour or a font.
    """
    try:
        css = CSS_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""
    return TOKEN_IMPORT_PATTERN.sub("", css, count=1)


def chrome_head(title, description, canonical, css):
    return f'''<!DOCTYPE html><html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="index,follow"><title>{esc(title)} | Rochdale Daily</title><meta name="description" content="{esc(description)}"><link rel="canonical" href="{esc(canonical)}">{HEAD_ASSETS}<style>{css}
.ward-wrap{{max-width:1000px;margin:0 auto;padding:28px 20px 60px}}.ward-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}}.ward-card{{border:1px solid #ddd;padding:15px;background:#fff}}.ward-card h3{{font-size:18px;margin:10px 0 6px}}.ward-meta{{font-size:12px;color:#667;text-transform:uppercase}}.ward-h2{{border-top:3px solid #111;padding-top:8px;margin-top:34px}}.cllr-photo{{width:100%;aspect-ratio:4/3;object-fit:cover;background:#eceff1;display:block}}.cllr-placeholder{{width:100%;aspect-ratio:4/3;background:#eceff1;display:grid;place-items:center;font-size:46px;font-weight:800;color:#89939d}}.dem-vote-side{{font-weight:800}}.dem-vote-for{{color:#18733a}}.dem-vote-against{{color:#a51d25}}.dem-vote-abstain{{color:#695b00}}</style></head><body><header class="masthead"><div class="wrap masthead-row"><a class="brand" href="/index.html">ROCHDALE DAILY</a> <a href="/wards/">All wards</a></div></header><main class="ward-wrap">'''


FOOT = '</main><footer style="background:#111;color:#ccc;padding:26px 20px"><strong>Rochdale Daily</strong> — independent local news for the Rochdale borough.</footer></body></html>'


def story_card(article):
    return (
        f'<article class="ward-card"><div class="ward-meta">{esc(str(article.get("area") or "").title())}</div>'
        f'<h3><a href="/articles/{esc(article.get("slug"))}.html">{esc(article.get("title"))}</a></h3>'
        f'<p>{esc((article.get("excerpt") or "")[:150])}</p></article>'
    )


def councillor_card(person, photos):
    name = str(person.get("name") or "")
    photo = photos.get(name, {}) if isinstance(photos, dict) else {}
    image = str(photo.get("image_url") or "")
    initials = "".join(part[0] for part in name.split()[:2]).upper()

    # Portraits are local-only. Ignore any stale value that does not point to the
    # editor-controlled cards folder, even if an old councillor_photos.json file
    # somehow survives in a checkout.
    if image.startswith("/assets/img/cards/"):
        portrait = f'<img class="cllr-photo" src="{esc(image)}" alt="Portrait of {esc(name)}" loading="lazy">'
    else:
        portrait = f'<div class="cllr-placeholder" title="Portrait not yet matched">{esc(initials)}</div>'

    votes = ""
    for vote in person.get("votes") or []:
        side = vote.get("side") if vote.get("side") in SIDE_LABEL else "abstain"
        title = esc(vote.get("title"))
        if vote.get("url"):
            link = f'<a href="{esc(vote.get("url"))}" target="_blank" rel="noopener">{title}</a>'
        else:
            link = title
        votes += (
            f'<li style="padding:6px 0;border-top:1px solid #eee">'
            f'<span class="dem-vote-side {SIDE_CLASS[side]}">{SIDE_LABEL[side]}</span> {link}</li>'
        )

    if votes:
        body = f'<p><b>Recorded votes</b></p><ul style="list-style:none;padding:0">{votes}</ul>'
    else:
        body = '<p>No recorded vote has named this councillor yet.</p>'

    return (
        f'<article class="ward-card">{portrait}<h3>{esc(name)}</h3>'
        f'<div class="ward-meta">{esc(person.get("party"))}</div>{body}</article>'
    )


def paste_friendly(page):
    """Break the page onto many short lines instead of a handful of enormous ones.

    The editor works through GitHub's web editor, which mishandles single lines
    of 10-20k characters (heywood.html was one). Newlines between block
    elements change nothing the browser renders and make the file pasteable.
    """
    page = re.sub(r"(</(?:article|section|header|footer|main|ul|li|p|h[1-6]|div|nav|style|head)>)", r"\1\n", page)
    page = re.sub(r"(<(?:article|section|main|ul|div|nav|h[1-6])\b[^>]*>)", r"\n\1", page)
    page = re.sub(r"(<body[^>]*>|<head>|<html[^>]*>|<!DOCTYPE html>)", r"\1\n", page)
    return re.sub(r"\n{3,}", "\n\n", page).strip() + "\n"


def archive_card(item):
    when = str(item.get("published_at") or "")[:10]
    return (
        f'<article class="ward-card"><div class="ward-meta">{esc(item.get("category") or "")}'
        f'{" · " + esc(when) if when else ""}</div>'
        f'<h3><a href="{esc(item.get("url") or "/articles/" + str(item.get("slug") or "") + ".html")}">{esc(item.get("title"))}</a></h3>'
        f'<p>{esc((item.get("description") or "")[:150])}</p></article>'
    )


def mentions_place(item, keywords):
    haystack = f'{item.get("title") or ""} {item.get("description") or ""} {item.get("excerpt") or ""}'.lower()
    return any(word in haystack for word in keywords)


def write_place_pages(wards, articles, votes, photos, css):
    """Root-level township / place pages built from their wards' data."""
    archive = read(ARCHIVE_INDEX_PATH, [])
    if not isinstance(archive, list):
        archive = []
    written = 0
    for filename, place in PLACE_PAGES.items():
        areas = set()
        people = []
        for ward in place["wards"]:
            config = wards.get(ward) or {}
            areas.update(area.lower() for area in config.get("areas", []))
            for person in (votes.get("wards") or {}).get(ward, []):
                people.append((ward, person))

        # Live stories: tagged with one of the place's areas, or naming the
        # place in the headline. Newest first, no duplicates.
        seen = set()
        live = []
        for article in articles:
            slug = str(article.get("slug") or "")
            if not slug or slug in seen:
                continue
            tagged = str(article.get("area") or "").lower() in areas
            if tagged or mentions_place(article, place["keywords"]):
                seen.add(slug)
                live.append(article)
        live = live[:MAX_PLACE_STORIES]

        older = [item for item in archive
                 if str(item.get("slug") or "") not in seen and mentions_place(item, place["keywords"])]
        older = older[:MAX_ARCHIVE_STORIES]

        councillors = "".join(
            councillor_card(person, photos).replace(
                '<div class="ward-meta">', f'<div class="ward-meta">{esc(ward)} · ', 1)
            for ward, person in people
        )
        ward_links = " · ".join(
            f'<a href="/wards/{slugify(ward)}.html">{esc(ward)}</a>' for ward in place["wards"]
        )
        filter_link = f'/index.html?area={place["filter_area"]}'
        name = place["name"]

        page = (
            chrome_head(f"{name} news", place["description"], f"{SITE}/{filename}", css)
            + f'<span>{esc(place["kind"])}</span><h1>{esc(name)}</h1>'
            + f'<p>Ward pages: {ward_links}. Or <a href="{esc(filter_link)}">filter the front page</a> to this area.</p>'
            + f'<h2 class="ward-h2">Latest {esc(name)} news</h2><div class="ward-grid">'
            + ("".join(story_card(article) for article in live) or f"<p>No live stories for {esc(name)} at the moment.</p>")
            + '</div>'
            + (f'<h2 class="ward-h2">From the archive</h2><div class="ward-grid">{"".join(archive_card(item) for item in older)}</div>' if older else "")
            + f'<h2 class="ward-h2">Your councillors</h2><div class="ward-grid">{councillors or "<p>No councillors on record.</p>"}</div>'
            + '<p>Only votes taken by name are listed. Rochdale Daily never infers an individual vote where the minutes do not name the councillor.</p>'
            + FOOT
        )
        (PLACE_OUTPUT_DIR / filename).write_text(paste_friendly(page), encoding="utf-8")
        written += 1
        print(f"  {filename}: {len(live)} live, {len(older)} archive, {len(people)} councillors")
    return written


def main():
    wards = read(WARD_MAP_PATH, {}).get("wards", {})
    raw = read(ARTICLES_PATH, [])
    articles = raw if isinstance(raw, list) else raw.get("articles", [])
    votes = read(VOTES_PATH, {})

    # Re-scan assets/img/cards every time ward pages are generated. This is the
    # important bit: uploading a councillor portrait is enough to make it appear
    # on the correct ward's democracy section on the next build. No hand-edited
    # portrait map and no remote image lookup are required.
    photos = build_local_portrait_map(write=False)

    css = load_css()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    missing = []

    for ward, config in wards.items():
        areas = {area.lower() for area in config.get("areas", [])}
        stories = [article for article in articles if str(article.get("area") or "").lower() in areas][:MAX_STORIES]
        people = (votes.get("wards") or {}).get(ward, [])

        for person in people:
            photo = photos.get(str(person.get("name") or ""), {})
            if not str(photo.get("image_url") or "").startswith("/assets/img/cards/"):
                missing.append(f'{ward}: {person.get("name")}')

        note = f'<p>{esc(config.get("note"))}</p>' if config.get("note") else ""
        councillors = "".join(councillor_card(person, photos) for person in people)
        page = (
            chrome_head(
                f"{ward} news and councillors",
                f"News from {ward} and what its councillors have voted on.",
                f"{SITE}/wards/{slugify(ward)}.html",
                css,
            )
            + f'<span>WARD</span><h1>{esc(ward)}</h1>{note}'
            + f'<h2 class="ward-h2">Your councillors</h2><div class="ward-grid">{councillors}</div>'
            + '<p>Only votes taken by name are listed. Rochdale Daily never infers an individual vote where the minutes do not name the councillor.</p>'
            + f'<h2 class="ward-h2">Ward news</h2><div class="ward-grid">{"".join(story_card(article) for article in stories) or "<p>No stories filed for this ward yet.</p>"}</div>'
            + FOOT
        )
        (OUTPUT_DIR / f"{slugify(ward)}.html").write_text(paste_friendly(page), encoding="utf-8")

    rows = "".join(
        f'<p><a href="/wards/{slugify(ward)}.html">{esc(ward)}</a></p>' for ward in sorted(wards)
    )
    (OUTPUT_DIR / "index.html").write_text(
        paste_friendly(
            chrome_head("News by ward", "Every Rochdale borough ward.", f"{SITE}/wards/", css)
            + "<h1>News by ward</h1>"
            + rows
            + FOOT
        ),
        encoding="utf-8",
    )

    place_count = write_place_pages(wards, articles, votes, photos, css)

    councillor_count = sum(len((votes.get("wards") or {}).get(ward, [])) for ward in wards)
    matched = councillor_count - len(missing)
    print(f"Generated {len(wards)} ward pages and {place_count} place pages; local councillor portraits matched {matched}/{councillor_count}.")
    if missing:
        print("Unmatched councillors:")
        for row in missing:
            print(" - " + row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
