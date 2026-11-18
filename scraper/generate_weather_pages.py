#!/usr/bin/env python3
"""Build the /weather/ pages: a seven-day Met Office forecast for each township.

"weather rochdale", "heywood weather", "weather littleborough" and the rest are
the biggest searches in the borough: about 96,000 UK searches a month between
the five towns (Ahrefs, November 2026), all at keyword difficulty 0. The paper
already fetched the Met Office forecast for the homepage panel, but no page
carried it, so none of those searches could find Rochdale Daily.

  weather/index.html          Rochdale        (from weather.json)
  weather/heywood.html        Heywood         (from weather_towns.json)
  weather/littleborough.html  Littleborough
  weather/middleton.html      Middleton
  weather/milnrow.html        Milnrow

Run by scraper/weather_forecast.py straight after it saves the forecasts, and
by the push-race rebuild. Days before today (Europe/London) are dropped at
build time. Nothing is padded: a value the Met Office did not give is left
out, and a town with no current days says so instead of showing old weather.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from generate_category_pages import FOOT, SITE, chrome_head, esc, load_css, read_json

ROOT = Path(__file__).resolve().parents[1]
ROCHDALE_PATH = ROOT / "weather.json"
TOWNS_PATH = ROOT / "weather_towns.json"
OUTPUT_DIR = ROOT / "weather"
LONDON = ZoneInfo("Europe/London")

# slug -> (display name, file name, search name used in the title)
PAGES = (
    ("rochdale", "Rochdale", "index.html", "Rochdale"),
    ("heywood", "Heywood", "heywood.html", "Heywood"),
    ("littleborough", "Littleborough", "littleborough.html", "Littleborough"),
    ("middleton", "Middleton", "middleton.html", "Middleton, Manchester"),
    ("milnrow", "Milnrow", "milnrow.html", "Milnrow"),
)

# A line of local use for each town: where its weather matters most.
LOCAL_NOTES = {
    "rochdale": "Covers Rochdale town centre and the surrounding wards.",
    "heywood": "Covers Heywood town centre and Queen's Park.",
    "littleborough": "Covers Littleborough, Hollingworth Lake and the Pennine routes over Blackstone Edge.",
    "middleton": "Covers Middleton town centre, Alkrington and Langley.",
    "milnrow": "Covers Milnrow, Newhey and the M62 at junction 21.",
}


def page_title(search_name: str) -> str:
    """Within 70 characters with the " | Rochdale Daily" suffix (Bing's limit)."""
    title = f"{search_name} weather: 7-day Met Office forecast"
    return title if len(title) <= 53 else f"{search_name} weather: 7-day forecast"


def page_url(file_name: str) -> str:
    return f"{SITE}/weather/" if file_name == "index.html" else f"{SITE}/weather/{file_name}"


def page_path(file_name: str) -> str:
    return "/weather/" if file_name == "index.html" else f"/weather/{file_name}"


def load_feeds() -> dict[str, dict]:
    feeds: dict[str, dict] = {}
    rochdale = read_json(ROCHDALE_PATH, None)
    if isinstance(rochdale, dict):
        feeds["rochdale"] = rochdale
    towns = read_json(TOWNS_PATH, {})
    if isinstance(towns, dict):
        for slug, feed in towns.items():
            if isinstance(feed, dict):
                feeds[slug] = feed
    return feeds


def current_days(feed: dict | None, today: date) -> list[dict]:
    days = []
    for day in (feed or {}).get("days") or []:
        try:
            when = date.fromisoformat(str(day.get("date"))[:10])
        except ValueError:
            continue
        if when >= today and isinstance(day.get("temperature_c"), (int, float)):
            days.append({**day, "_date": when})
    return days


def updated_label(feed: dict) -> str:
    try:
        stamp = datetime.fromisoformat(str(feed.get("generated_at"))).astimezone(LONDON)
    except (TypeError, ValueError):
        return ""
    return stamp.strftime("%-d %B %Y at %H:%M")


def day_name(when: date, today: date) -> str:
    if when == today:
        return "Today"
    if (when - today).days == 1:
        return "Tomorrow"
    return when.strftime("%A %-d %B")


def temps(day: dict) -> str:
    high = f"{day['temperature_c']}°C"
    if isinstance(day.get("min_temperature_c"), (int, float)):
        return f"{high} / {day['min_temperature_c']}°C"
    return high


def detail_bits(day: dict) -> list[str]:
    bits = []
    if isinstance(day.get("rain_chance_pct"), (int, float)):
        bits.append(f"{day['rain_chance_pct']}% chance of rain")
    if isinstance(day.get("wind_mph"), (int, float)):
        wind = f"wind {day['wind_mph']} mph"
        if isinstance(day.get("gust_mph"), (int, float)):
            wind += f", gusts {day['gust_mph']} mph"
        bits.append(wind)
    if isinstance(day.get("uv_index"), (int, float)):
        bits.append(f"UV {day['uv_index']}")
    return bits


def town_nav(current: str) -> str:
    links = []
    for slug, name, file_name, _ in PAGES:
        attrs = ' aria-current="page"' if slug == current else ""
        links.append(f'<a href="{page_path(file_name)}"{attrs}>{esc(name)}</a>')
    return '<nav class="cat-nav" aria-label="Weather by town">' + "".join(links) + "</nav>"


def render(slug: str, name: str, file_name: str, search_name: str, feed: dict | None, today: date) -> str:
    canonical = page_url(file_name)
    title = page_title(search_name)
    days = current_days(feed, today)
    updated = updated_label(feed or {})

    if days:
        first = days[0]
        description = (f"{name} weather forecast from the Met Office: {day_name(first['_date'], today).lower()} "
                       f"{first['condition'].lower()}, high of {first['temperature_c']}°C. "
                       f"Seven-day outlook, rain chance and wind.")
    else:
        description = f"{name} weather forecast from the Met Office, with a seven-day outlook, rain chance and wind."

    parts = [
        '<span class="rd-kicker">Weather</span>',
        f"<h1>{esc(name)} weather forecast</h1>",
        f'<p class="rd-lede">The Met Office forecast for {esc(name)} for the next seven days. '
        f"{esc(LOCAL_NOTES.get(slug, ''))}</p>",
        town_nav(slug),
    ]

    if days:
        first = days[0]
        bits = detail_bits(first)
        parts.append(
            '<section class="wx-now" aria-labelledby="wx-now-title">'
            f'<h2 class="rd-h2" id="wx-now-title">{esc(day_name(first["_date"], today))}</h2>'
            f'<p class="wx-big"><span class="wx-icon" aria-hidden="true">{esc(first.get("icon") or "")}</span>'
            f'<span class="wx-temp">{esc(temps(first))}</span>'
            f'<span class="wx-cond">{esc(first["condition"])}</span></p>'
            + (f'<p class="wx-detail">{esc(" · ".join(bits))}</p>' if bits else "")
            + "</section>"
        )
        rows = []
        for day in days:
            bits = detail_bits(day)
            rows.append(
                "<tr>"
                f'<th scope="row">{esc(day_name(day["_date"], today))}</th>'
                f'<td><span aria-hidden="true">{esc(day.get("icon") or "")}</span> {esc(day["condition"])}</td>'
                f"<td>{esc(temps(day))}</td>"
                f'<td>{esc(" · ".join(bits))}</td>'
                "</tr>"
            )
        parts.append(
            '<h2 class="rd-h2">Seven-day forecast</h2>'
            '<div class="wx-scroll"><table class="wx-table">'
            '<thead><tr><th scope="col">Day</th><th scope="col">Weather</th>'
            '<th scope="col">High / low</th><th scope="col">Rain and wind</th></tr></thead>'
            "<tbody>" + "".join(rows) + "</tbody></table></div>"
        )
    else:
        parts.append(
            '<p class="rd-lede">The forecast for this town is being updated. '
            'Please check back shortly, or see the <a href="https://www.metoffice.gov.uk/" rel="noopener" '
            'target="_blank">Met Office</a> directly.</p>'
        )

    parts.append(
        '<p class="rd-meta wx-source">Source: Met Office'
        + (f". Updated {esc(updated)}." if updated else ".")
        + ' For weather warnings, see the <a href="https://www.metoffice.gov.uk/weather/warnings-and-advice/uk-warnings" '
        'rel="noopener" target="_blank">Met Office warnings page</a>.</p>'
    )
    parts.append(
        '<h2 class="rd-h2">Getting about</h2><p class="rd-links">'
        '<a href="/roadworks.html">Roadworks and road closures</a> · '
        '<a href="/news/traffic.html">Traffic and travel news</a> · '
        '<a href="/whats-on.html">What\'s on this week</a></p>'
    )

    json_ld = json.dumps({
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": f"{name} weather forecast",
        "url": canonical,
        "description": description,
        "about": {"@type": "Place", "name": f"{name}, Greater Manchester"},
        "isPartOf": {"@type": "WebSite", "name": "Rochdale Daily", "url": SITE + "/"},
        "breadcrumb": {
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Rochdale Daily", "item": SITE + "/"},
                {"@type": "ListItem", "position": 2, "name": "Weather", "item": f"{SITE}/weather/"},
            ] + ([] if file_name == "index.html" else
                 [{"@type": "ListItem", "position": 3, "name": name, "item": canonical}]),
        },
    }, ensure_ascii=False).replace("</", "<\\/")

    css = load_css() + (
        ".wx-now{margin:0 0 18px}.wx-big{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 14px;margin:0 0 6px}"
        ".wx-icon{font-size:34px;line-height:1}.wx-temp{font-family:var(--font-display);font-size:clamp(28px,6vw,40px);font-weight:700;color:var(--ink)}"
        ".wx-cond{font-size:18px;color:var(--ink)}.wx-detail{margin:0;color:var(--muted)}"
        ".wx-scroll{overflow-x:auto}.wx-table{width:100%;border-collapse:collapse;font-size:15px}"
        ".wx-table th,.wx-table td{text-align:left;padding:10px 8px;border-top:1px solid var(--line);vertical-align:top}"
        ".wx-table thead th{font-family:var(--font-ui);font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);border-top:0}"
        ".wx-table tbody th{font-family:var(--font-ui);font-weight:700;white-space:nowrap}"
        ".wx-source{margin-top:14px}"
    )
    return chrome_head(title, description, canonical, css, json_ld) + "".join(parts) + FOOT


def main(now: datetime | None = None) -> list[str]:
    """Write every page. Returns the files written."""
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(LONDON).date()
    feeds = load_feeds()
    if not feeds:
        print("Weather pages not written: no saved forecast yet.")
        return []
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    for slug, name, file_name, search_name in PAGES:
        html = render(slug, name, file_name, search_name, feeds.get(slug), today)
        (OUTPUT_DIR / file_name).write_text(html, encoding="utf-8")
        written.append(f"weather/{file_name}")
    print(f"Weather pages written: {len(written)}")
    return written


if __name__ == "__main__":
    main()
