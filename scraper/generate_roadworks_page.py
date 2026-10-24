#!/usr/bin/env python3
"""Build /roadworks.html: every current council roadworks notice in one page.

"Roadworks in Rochdale" and "road closures Rochdale this week" are repeat
local searches. The council publishes each closure as a directory record;
primary_data.council_roadworks reads the whole listing every six hours and
saves it to roadworks.json. Only a few notices a day become stories, so this
page lists them all, grouped by start date in Europe/London time:

  * Starting this week (today to seven days ahead)
  * Started recently (up to fourteen days ago; most notices give no end date)
  * Coming up (later)

Each row links to the council's own notice, which holds the detail (times,
diversions, end dates), and to Rochdale Daily's story where one exists.
Nothing is written until roadworks.json exists, so the page never goes out
empty. Notices with no date in their title are listed separately, not
guessed.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from generate_category_pages import FOOT, SITE, chrome_head, esc, load_css, read_json

LONDON = ZoneInfo("Europe/London")
DATA = Path("roadworks.json")
OUTPUT = Path("roadworks.html")
CANONICAL = f"{SITE}/roadworks.html"
RECENT_DAYS = 14
TOWN_LABELS = {"rochdale": "Rochdale", "heywood": "Heywood", "middleton": "Middleton",
               "littleborough": "Littleborough", "milnrow": "Milnrow", "newhey": "Newhey",
               "wardle": "Wardle", "castleton": "Castleton", "norden": "Norden", "bamford": "Bamford"}
_SPLIT = re.compile(r"^(?P<road>.+?),\s*(?P<kind>roadworks|road closures?)\b(?P<rest>.*)$", re.I)


def _date(value) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def describe(title: str) -> tuple[str, str]:
    """"Joy Street, roadworks in Rochdale from 2 November 2026" ->
    ("Joy Street", "Roadworks in Rochdale from 2 November 2026")."""
    title = re.sub(r"\s+-\s+Rochdale Borough Council\s*$", "", str(title or "")).strip()
    match = _SPLIT.match(title)
    if not match:
        return title, ""
    detail = (match.group("kind") + match.group("rest")).strip()
    return match.group("road").strip(), detail[:1].upper() + detail[1:]


def story_links(articles: list[dict]) -> dict[str, str]:
    """Council notice URL -> our story slug, for notices we have written up."""
    links: dict[str, str] = {}
    for article in articles:
        for url in [article.get("source_url")] + list(article.get("source_urls") or []):
            url = str(url or "")
            if "rochdale.gov.uk/directory-record/" in url and article.get("slug"):
                links.setdefault(url.split("?")[0].rstrip("/"), str(article["slug"]))
    return links


def group(notices: list[dict], today: date) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {"week": [], "recent": [], "later": [], "undated": []}
    for notice in notices:
        start = _date(notice.get("start"))
        if start is None:
            groups["undated"].append(notice)
        elif today <= start <= today + timedelta(days=7):
            groups["week"].append(notice)
        elif today - timedelta(days=RECENT_DAYS) <= start < today:
            groups["recent"].append(notice)
        elif start > today + timedelta(days=7):
            groups["later"].append(notice)
    for key in ("week", "later"):
        groups[key].sort(key=lambda n: (n["start"], n.get("title", "")))
    groups["recent"].sort(key=lambda n: (n["start"], n.get("title", "")), reverse=True)
    return groups


def row(notice: dict, stories: dict[str, str]) -> str:
    road, detail = describe(notice.get("title", ""))
    start = _date(notice.get("start"))
    town = TOWN_LABELS.get(str(notice.get("area") or ""), "")
    when = start.strftime("%a %-d %b") if start else "Date on notice"
    story = stories.get(str(notice.get("url") or "").rstrip("/"))
    extra = f' · <a href="/articles/{esc(story)}.html">Our report</a>' if story else ""
    return (
        '<li class="rw-row">'
        f'<span class="rw-when">{esc(when)}</span>'
        f'<span class="rw-what"><strong>{esc(road)}</strong>'
        f'{(" · " + esc(town)) if town else ""}<br><span class="rw-detail">{esc(detail)}</span></span>'
        f'<span class="rw-links"><a href="{esc(notice.get("url"))}" rel="noopener">Council notice</a>{extra}</span>'
        "</li>"
    )


def render(payload: dict, articles: list[dict], now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(LONDON).date()
    notices = [n for n in payload.get("notices") or [] if isinstance(n, dict) and n.get("url")]
    groups = group(notices, today)
    stories = story_links(articles)
    fetched = payload.get("fetched_at") or ""
    try:
        checked = datetime.fromisoformat(fetched.replace("Z", "+00:00")).astimezone(LONDON)
        checked_label = checked.strftime("%-d %B %Y, %-I:%M%p").replace("AM", "am").replace("PM", "pm")
    except ValueError:
        checked_label = ""
    description = ("Roadworks and road closures in Rochdale this week and coming up, from Rochdale "
                   "Borough Council's own notices: Rochdale, Heywood, Middleton, Littleborough and Milnrow.")

    def section(heading: str, rows: list[dict], empty: str) -> str:
        if not rows:
            return f'<h2 class="rd-h2">{esc(heading)}</h2><p class="rd-lede">{esc(empty)}</p>'
        return (f'<h2 class="rd-h2">{esc(heading)} <span class="rw-count">({len(rows)})</span></h2>'
                '<ul class="rw-list">' + "".join(row(n, stories) for n in rows) + "</ul>")

    css = (".rw-list{list-style:none;margin:0;padding:0}"
           ".rw-row{display:grid;grid-template-columns:110px 1fr auto;gap:6px 16px;padding:12px 0;border-bottom:1px solid var(--line)}"
           ".rw-when{font-family:var(--font-ui);font-size:13px;font-weight:700;color:var(--ink)}"
           ".rw-detail{color:var(--muted);font-size:14px}.rw-links{font-size:14px;white-space:nowrap}"
           ".rw-links a{color:var(--accent);font-weight:600}.rw-count{font-size:16px;color:var(--muted);font-weight:600}"
           "@media(max-width:640px){.rw-row{grid-template-columns:1fr}.rw-links{white-space:normal}}")
    body = (
        '<p class="rd-kicker">Traffic and travel</p><h1>Roadworks in Rochdale</h1>'
        f'<p class="rd-lede">{esc(description)}'
        + (f" Council list checked {esc(checked_label)}." if checked_label else "")
        + " Times, diversions and end dates are on each council notice.</p>"
        '<p class="rd-links"><a href="/news/traffic">Traffic news</a> · '
        '<a href="https://tfgm.com/travel-updates" rel="noopener">Buses and trams</a> · '
        '<a href="https://nationalhighways.co.uk/travel-updates/" rel="noopener">Motorways</a></p>'
        + section("Starting this week", groups["week"], "No new roadworks are listed to start in the next seven days.")
        + section("Started recently", groups["recent"], "None listed in the last two weeks.")
        + section("Coming up", groups["later"], "Nothing further is listed yet.")
        + (section("Date given on the notice", groups["undated"], "") if groups["undated"] else "")
        + f'<p class="rd-links">Source: <a href="{esc(payload.get("source_url") or "")}" rel="noopener">'
          "Rochdale Borough Council roadworks directory</a>.</p>"
    )
    graph = {
        "@context": "https://schema.org", "@type": "CollectionPage", "@id": CANONICAL,
        "name": "Roadworks in Rochdale", "url": CANONICAL, "inLanguage": "en-GB",
        "description": description,
        "isPartOf": {"@type": "WebSite", "name": "Rochdale Daily", "url": SITE},
    }
    head = chrome_head("Roadworks and road closures in Rochdale this week", description, CANONICAL,
                       load_css() + css, json.dumps(graph, ensure_ascii=False).replace("</", "<\\/"))
    return head + body + FOOT


def main() -> int:
    payload = read_json(DATA, None)
    if not isinstance(payload, dict) or not payload.get("notices"):
        print("Roadworks page not written: no council listing saved yet (roadworks.json).")
        return 0
    articles = read_json(Path("articles.json"), [])
    OUTPUT.write_text(render(payload, articles if isinstance(articles, list) else []), encoding="utf-8")
    print(f"Roadworks page written: {OUTPUT} ({len(payload['notices'])} notices)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
