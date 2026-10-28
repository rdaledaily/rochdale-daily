#!/usr/bin/env python3
"""Build /rochdale-afc.html: the Rochdale AFC matchday hub.

Football is the most reliable reason a local reader comes back every week.
MEN runs the same rhythm for every match: preview, team news about an hour
before kick-off, a live page during the game, the report at full time. This
page holds that rhythm together for Dale:

  * the next fixture (from afc_fixtures.json, verified entries only),
  * this match's coverage: preview, team news, live, report, found from the
    paper's own published stories about that opponent around match day,
  * the latest Dale stories, and the confirmed fixture list.

Fixtures are never guessed. A fixture without verified:true and a source_url
is not shown; if there is no confirmed next match, the page says so.

Run inside generate_pages.main(), like the section pages, so every lane
rebuilds it.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from generate_category_pages import (
    ARTICLES_PATH, FOOT, SITE, chrome_head, esc, is_published, load_css,
    parse_iso, published_at, read_json, story_card,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES_PATH = ROOT / "afc_fixtures.json"
OUTPUT = ROOT / "rochdale-afc.html"
LONDON = ZoneInfo("Europe/London")
AFC_RE = re.compile(r"\brochdale afc\b|\bdale\b(?! (?:hall|park|street|road))|\bspotland\b|\bcrown oil arena\b|\brochdale (?:boss|manager|striker|midfielder|defender|keeper)\b", re.I)
EXCLUDE_RE = re.compile(r"\bwomen'?s?\b|\bunder[- ]?\d+|\bu\d{2}\b|\bnetball\b|\bhornets\b|\byouth cup\b", re.I)
STAGES = (
    ("preview", re.compile(r"\b(?:preview|set to face|prepares? for|ahead of|face[s]? .* (?:clash|tie))\b", re.I), "Preview"),
    ("team_news", re.compile(r"\b(?:team news|line-?up|starting xi|injur(?:y|ies) (?:update|news))\b", re.I), "Team news"),
    ("report", re.compile(r"\b(?:beat|beaten|draw|drew|lose|lost|win|won|thrash|held|defeat|victory|\d+\s*-\s*\d+)\b", re.I), "Report"),
)


def verified_fixtures(path: Path = FIXTURES_PATH) -> list[dict]:
    data = read_json(path, {})
    rows = data.get("fixtures") if isinstance(data, dict) else []
    out = []
    for row in rows or []:
        if not isinstance(row, dict) or row.get("verified") is not True:
            continue
        if not str(row.get("source_url") or "").startswith("https://"):
            continue
        try:
            day = date.fromisoformat(str(row.get("date")))
        except ValueError:
            continue
        out.append({**row, "_date": day})
    return sorted(out, key=lambda r: (r["_date"], str(r.get("kickoff") or "")))


def kickoff_dt(fixture: dict) -> datetime | None:
    kick = str(fixture.get("kickoff") or "")
    if not re.fullmatch(r"\d{1,2}:\d{2}", kick):
        return None
    hour, minute = (int(x) for x in kick.split(":"))
    return datetime(fixture["_date"].year, fixture["_date"].month, fixture["_date"].day, hour, minute, tzinfo=LONDON)


def next_fixture(fixtures: list[dict], now: datetime) -> dict | None:
    today = now.astimezone(LONDON).date()
    for row in fixtures:
        if row["_date"] >= today and not str(row.get("result") or "").strip():
            return row
    return None


def afc_stories(articles: list[dict]) -> list[dict]:
    rows = [
        a for a in articles
        if isinstance(a, dict) and is_published(a)
        and str(a.get("category") or "").lower() == "sport"
        and AFC_RE.search(str(a.get("title") or "") + " " + str(a.get("excerpt") or ""))
        and not EXCLUDE_RE.search(str(a.get("title") or ""))
    ]
    return sorted(rows, key=lambda a: parse_iso(published_at(a)), reverse=True)


def match_coverage(fixture: dict, stories: list[dict]) -> dict[str, dict]:
    """The paper's own stories about this match, by stage."""
    opponent = str(fixture.get("opponent") or "").lower()
    if not opponent:
        return {}
    start = datetime.combine(fixture["_date"] - timedelta(days=4), datetime.min.time(), tzinfo=timezone.utc)
    end = datetime.combine(fixture["_date"] + timedelta(days=2), datetime.min.time(), tzinfo=timezone.utc)
    found: dict[str, dict] = {}
    for story in stories:
        when = parse_iso(published_at(story))
        title = str(story.get("title") or "")
        if not (start <= when <= end) or opponent not in title.lower():
            continue
        after_kickoff = when.date() >= fixture["_date"]
        for key, pattern, _label in STAGES:
            if key in found:
                continue
            if key == "report" and not after_kickoff:
                continue
            if key != "report" and after_kickoff and when.date() > fixture["_date"]:
                continue
            if pattern.search(title):
                found[key] = story
                break
    return found


def fixture_line(row: dict) -> str:
    where = "home" if str(row.get("venue")).lower() == "home" else "away"
    vs = f"Rochdale v {row.get('opponent')}" if where == "home" else f"{row.get('opponent')} v Rochdale"
    day = row["_date"].strftime("%a %-d %b")
    kick = f" · {esc(row.get('kickoff'))}" if row.get("kickoff") else ""
    tv = f" · {esc(row.get('tv'))}" if row.get("tv") else ""
    result = str(row.get("result") or "").strip()
    res = f' <strong class="afc-result">{esc(result)}</strong>' if result else ""
    return (f'<li><span class="afc-date">{esc(day)}{kick}</span> <span class="afc-vs">{esc(vs)}</span>{res} '
            f'<span class="rd-meta">{esc(row.get("competition") or "")}{tv}</span> '
            f'<a class="afc-src" href="{esc(row.get("source_url"))}" rel="noopener" target="_blank">source</a></li>')


def render(articles: list[dict], fixtures: list[dict], now: datetime) -> str:
    stories = afc_stories(articles)
    nxt = next_fixture(fixtures, now)
    canonical = f"{SITE}/rochdale-afc"
    title = "Rochdale AFC: fixtures, team news and match reports"
    description = "Rochdale AFC matchday hub: the next fixture, previews, team news, live coverage and reports from Rochdale Daily."

    parts = ['<span class="rd-kicker">Sport</span><h1>Rochdale AFC</h1>',
             '<p class="rd-lede">Every Dale matchday in one place: preview, team news about an hour before kick-off, '
             'live coverage during the game and the report at full time.</p>']
    parts.append('<section class="afc-live" id="afc-live" hidden><span class="live-pill">LIVE</span> '
                 '<a id="afc-live-link" href="#"></a></section>')

    if nxt:
        kick = kickoff_dt(nxt)
        where = "Home" if str(nxt.get("venue")).lower() == "home" else "Away"
        vs = (f"Rochdale v {nxt.get('opponent')}" if where == "Home" else f"{nxt.get('opponent')} v Rochdale")
        when = nxt["_date"].strftime("%A %-d %B") + (f", kick-off {nxt.get('kickoff')}" if nxt.get("kickoff") else "")
        cover = match_coverage(nxt, stories)
        steps = []
        plan = (("preview", "Preview", "The day before"),
                ("team_news", "Team news", "About an hour before kick-off"),
                ("live", "Live", "During the match"),
                ("report", "Report", "At full time"))
        for key, label, timing in plan:
            story = cover.get(key)
            body = (f'<a href="/articles/{esc(story.get("slug"))}">{esc(story.get("title"))}</a>'
                    if story else f'<span class="rd-meta">{esc(timing)}</span>')
            steps.append(f'<li class="afc-step{" afc-step--done" if story else ""}" data-stage="{key}"><strong>{esc(label)}</strong>{body}</li>')
        parts.append(
            '<section class="afc-next" aria-labelledby="afc-next-title">'
            '<h2 class="rd-h2" id="afc-next-title">Next match</h2>'
            f'<p class="afc-fixture"><span class="afc-vs-big">{esc(vs)}</span>'
            f'<span class="afc-when">{esc(when)}{" · " + esc(nxt.get("ground")) if nxt.get("ground") else ""}'
            f'{" · " + esc(nxt.get("tv")) if nxt.get("tv") else ""}</span>'
            f'<span class="rd-meta">{esc(nxt.get("competition") or "")} · {where}</span></p>'
            + (f'<p class="afc-countdown" data-kickoff="{kick.isoformat()}"></p>' if kick else "")
            + '<ol class="afc-steps">' + "".join(steps) + '</ol></section>'
        )
    else:
        parts.append('<section class="afc-next"><h2 class="rd-h2">Next match</h2>'
                     '<p class="rd-lede">The next fixture will appear here once it is confirmed by the club.</p></section>')

    if stories:
        parts.append('<h2 class="rd-h2">Latest Dale news</h2><div class="rd-grid">'
                     + "".join(story_card(s) for s in stories[:12]) + "</div>")

    upcoming = [f for f in fixtures if f["_date"] >= now.astimezone(LONDON).date() and not f.get("result")]
    played = [f for f in fixtures if f.get("result")]
    if upcoming:
        parts.append('<h2 class="rd-h2">Confirmed fixtures</h2><ul class="afc-list">' + "".join(fixture_line(f) for f in upcoming) + "</ul>")
    if played:
        parts.append('<h2 class="rd-h2">Results</h2><ul class="afc-list">' + "".join(fixture_line(f) for f in reversed(played[-10:])) + "</ul>")
    parts.append('<p class="rd-links">Fixtures are listed once confirmed by the club, the opposition or the EFL. '
                 '<a href="https://www.rochdaleafc.co.uk/" rel="noopener" target="_blank">Rochdale AFC official site</a></p>')

    json_ld = json.dumps({
        "@context": "https://schema.org", "@type": "CollectionPage", "name": title, "url": canonical,
        "about": {"@type": "SportsTeam", "name": "Rochdale AFC", "sport": "Association football"},
        "isPartOf": {"@type": "WebSite", "name": "Rochdale Daily", "url": SITE + "/"},
    }, ensure_ascii=False).replace("</", "<\\/")
    css = load_css() + (
        ".afc-next{margin-bottom:8px}.afc-fixture{display:flex;flex-direction:column;gap:4px;margin:0 0 8px}"
        ".afc-vs-big{font-family:var(--font-display);font-size:clamp(26px,5vw,36px);font-weight:700;line-height:1.1;color:var(--ink)}"
        ".afc-when{font-size:16px;color:var(--ink)}.afc-countdown{font-family:var(--font-ui);font-weight:700;color:var(--breaking,#8c3a25);margin:0 0 12px}"
        ".afc-steps{list-style:none;padding:0;margin:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px}"
        ".afc-step{border:1px solid var(--line);border-top:3px solid var(--line);padding:10px 12px;display:flex;flex-direction:column;gap:4px}"
        ".afc-step--done{border-top-color:var(--ink)}.afc-step a{font-family:var(--font-display);font-weight:700;color:var(--ink)}"
        ".afc-list{list-style:none;padding:0;margin:0}.afc-list li{border-top:1px solid var(--line);padding:10px 0;display:flex;flex-wrap:wrap;gap:4px 10px;align-items:baseline}"
        ".afc-date{font-family:var(--font-ui);font-weight:700;min-width:120px}.afc-vs{font-weight:600}.afc-src{font-size:12px}"
        ".afc-live{border:1px solid var(--breaking,#8c3a25);border-left-width:4px;padding:10px 14px;margin:0 0 18px;display:flex;gap:10px;align-items:center}"
        ".afc-live a{font-family:var(--font-display);font-weight:700;color:var(--ink)}.afc-live[hidden]{display:none}"
    )
    script = (
        "<script>(function(){var c=document.querySelector('.afc-countdown');if(c){var k=Date.parse(c.getAttribute('data-kickoff'));"
        "function t(){var m=Math.round((k-Date.now())/60000);if(m>2880){c.textContent='';return}"
        "c.textContent=m>120?'Kick-off in '+Math.floor(m/60)+' hours':m>0?'Kick-off in '+m+' minutes':m>-120?'Match under way':'';}t();setInterval(t,60000);}"
        "fetch('/api/live-updates?index=1').then(function(r){return r.ok?r.json():null}).then(function(d){var l=(d&&d.live||[]).filter(function(i){return /sport/.test(i.category||'')&&/rochdale|dale/i.test(i.title||'')})[0];"
        "if(!l||!/^[a-z0-9-]+$/.test(l.slug))return;var a=document.getElementById('afc-live-link');a.href='/articles/'+l.slug;a.textContent=l.title;document.getElementById('afc-live').hidden=false;}).catch(function(){});})();</script>"
    )
    return chrome_head(title, description, canonical, css, json_ld) + "".join(parts) + script + FOOT


def main(now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    articles = read_json(ARTICLES_PATH, [])
    if not isinstance(articles, list):
        return False
    OUTPUT.write_text(render(articles, verified_fixtures(), now), encoding="utf-8")
    print("Rochdale AFC hub written.")
    return True


if __name__ == "__main__":
    main()
