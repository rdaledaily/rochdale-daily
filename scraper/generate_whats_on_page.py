#!/usr/bin/env python3
"""Build /whats-on.html: an indexable What's On page for Rochdale.

"What's on in Rochdale this weekend" is one of the borough's most repeated
searches, but What's On existed only as a homepage section, which cannot rank
for it. This page is rebuilt on every lane from the event records already in
articles.json, grouped in Europe/London time:

  * This weekend (Friday evening to Sunday night; the coming weekend
    Monday to Thursday)
  * Next 7 days (excluding the weekend above)
  * Coming up (everything later)

Each event carries schema.org Event markup (date, venue, offline attendance)
so it can appear in Google's event listings. When nothing is on that weekend
the page says so plainly instead of padding the section.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from generate_category_pages import FOOT, SITE, chrome_head, esc, load_css, read_json

LONDON = ZoneInfo("Europe/London")
OUTPUT = Path("whats-on.html")
CANONICAL = f"{SITE}/whats-on.html"


def _when(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(LONDON)


def weekend_window(now: datetime) -> tuple[datetime, datetime]:
    """Friday 17:00 to Monday 00:00 London time, for this or the coming weekend."""
    local = now.astimezone(LONDON)
    friday = (local - timedelta(days=(local.weekday() - 4) % 7)).replace(hour=17, minute=0, second=0, microsecond=0)
    if local.weekday() < 4:  # Monday-Thursday: the coming weekend
        friday = (local + timedelta(days=4 - local.weekday())).replace(hour=17, minute=0, second=0, microsecond=0)
    end = (friday + timedelta(days=3)).replace(hour=0, minute=0)
    return friday, end


def upcoming_events(articles: list[dict], now: datetime) -> list[tuple[datetime, dict]]:
    floor = now - timedelta(hours=3)  # keep tonight's event while it is on
    events = []
    for article in articles:
        if str(article.get("status") or "published") != "published":
            continue
        start = _when(article.get("event_start_at"))
        if start is None or not article.get("slug"):
            continue
        end = _when(article.get("event_end_at")) or start
        if max(start, end) < floor:
            continue
        events.append((start, article))
    return sorted(events, key=lambda pair: (pair[0], str(pair[1].get("title") or "")))


def _venue(article: dict) -> str:
    return str(article.get("event_location") or "").strip()


def event_card(start: datetime, article: dict) -> str:
    slug = esc(article.get("slug"))
    image = str(article.get("image_url") or "").strip().lstrip("/")
    image_markup = (
        f'<a href="/articles/{slug}.html" tabindex="-1" aria-hidden="true">'
        f'<img src="/{esc(image)}" alt="{esc(article.get("image_alt") or article.get("title"))}" loading="lazy"></a>'
        if image else ""
    )
    when = start.strftime("%a %-d %b · %-I:%M%p").replace(":00", "").replace("AM", "am").replace("PM", "pm")
    venue = _venue(article)
    return (
        f'<article class="rd-card">{image_markup}'
        f'<div class="rd-meta"><time datetime="{esc(start.isoformat())}">{esc(when)}</time></div>'
        f'<h3><a href="/articles/{slug}.html">{esc(article.get("title"))}</a></h3>'
        + (f'<p>{esc(venue)}</p>' if venue else "")
        + "</article>"
    )


def event_json_ld(events: list[tuple[datetime, dict]]) -> str:
    items = []
    for index, (start, article) in enumerate(events[:40]):
        event = {
            "@type": "Event",
            "name": str(article.get("title") or "")[:200],
            "startDate": start.isoformat(),
            "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
            "eventStatus": "https://schema.org/EventScheduled",
            "url": f"{SITE}/articles/{article.get('slug')}.html",
        }
        end = _when(article.get("event_end_at"))
        if end and end >= start:
            event["endDate"] = end.isoformat()
        venue = _venue(article)
        if venue:
            event["location"] = {"@type": "Place", "name": venue[:120],
                                 "address": {"@type": "PostalAddress", "streetAddress": venue,
                                             "addressRegion": "Greater Manchester", "addressCountry": "GB"}}
        image = str(article.get("image_url") or "").strip().lstrip("/")
        if image:
            event["image"] = f"{SITE}/{image}"
        if article.get("excerpt"):
            event["description"] = str(article["excerpt"])[:300]
        items.append({"@type": "ListItem", "position": index + 1, "item": event})
    graph = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "@id": CANONICAL,
        "name": "What's on in Rochdale",
        "url": CANONICAL,
        "inLanguage": "en-GB",
        "isPartOf": {"@type": "WebSite", "name": "Rochdale Daily", "url": SITE},
        "mainEntity": {"@type": "ItemList", "itemListElement": items},
    }
    return json.dumps(graph, ensure_ascii=False).replace("</", "<\\/")


def render(articles: list[dict], now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    events = upcoming_events(articles, now)
    weekend_start, weekend_end = weekend_window(now)
    week_end = now.astimezone(LONDON) + timedelta(days=7)
    weekend = [(s, a) for s, a in events if weekend_start <= s < weekend_end or (s < weekend_start and (_when(a.get("event_end_at")) or s) >= weekend_start)]
    taken = {id(a) for _, a in weekend}
    week = [(s, a) for s, a in events if id(a) not in taken and s < week_end]
    taken |= {id(a) for _, a in week}
    later = [(s, a) for s, a in events if id(a) not in taken][:40]

    sat = weekend_start + timedelta(days=1)
    sun = weekend_start + timedelta(days=2)
    weekend_label = f"This weekend: {sat.strftime('%A %-d')} and {sun.strftime('%A %-d %B')}"
    description = (
        "What's on in Rochdale this weekend and coming up: gigs, shows, family events and "
        "community events across Rochdale, Heywood, Middleton, Littleborough and Milnrow."
    )

    def section(heading: str, rows: list[tuple[datetime, dict]], empty: str) -> str:
        body = ('<div class="rd-grid">' + "".join(event_card(s, a) for s, a in rows) + "</div>") if rows \
            else f'<p class="rd-lede">{esc(empty)}</p>'
        return f'<h2 class="rd-h2">{esc(heading)}</h2>' + body

    updated = now.astimezone(LONDON).strftime("%-d %B %Y, %-I:%M%p").replace("AM", "am").replace("PM", "pm")
    body = (
        '<p class="rd-kicker">What\'s on</p><h1>What\'s on in Rochdale</h1>'
        f'<p class="rd-lede">{esc(description)} Updated {esc(updated)}.</p>'
        '<p class="rd-links">Running an event in the borough? <a href="/contact.html">Tell us about it</a>.</p>'
        + section(weekend_label, weekend,
                  "Nothing is listed for this weekend yet. We add events as soon as they are confirmed, so check back.")
        + section("In the next seven days", week, "Nothing else is listed for the coming week yet.")
        + section("Coming up", later, "Nothing further is listed yet.")
    )
    head = chrome_head("What's on in Rochdale this weekend and coming up", description, CANONICAL,
                       load_css(), event_json_ld(weekend + week + later))
    return head + body + FOOT


def main() -> int:
    articles = read_json(Path("articles.json"), [])
    OUTPUT.write_text(render(articles if isinstance(articles, list) else []), encoding="utf-8")
    print(f"What's On page written: {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
