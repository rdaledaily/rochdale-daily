"""Rochdale Daily — the 9am Morning Briefing and the 6pm Evening Wrap-Up.

Appointment publishing. The point is not the prose, it is that the borough can
set its watch by it: the same thing, in the same place, at the same time, every
single day. That is how a local paper becomes a habit rather than something you
land on from a search result.

Two deliberate design decisions:

1. NO MODEL CALL. The briefing is assembled from stories Rochdale Daily has
   already published, so there is nothing to rewrite and nothing to fact-check
   -- the paper is quoting itself. It also means the briefing can never be late
   or missing because a free-tier rate limit was in the way, which for an
   appointment product matters more than any turn of phrase.

2. IT TELLS THE TRUTH ON A QUIET DAY. If nothing has been published in the
   window it says so plainly and points at what is still live, rather than
   padding to look busy. A briefing that cries wolf every morning is worth
   less than one that occasionally says "quiet night".

Output is a pending_manual_*.json, which the existing publish-pending-manual
workflow merges exactly like any other editor-written article.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:                                        # Python 3.9+
    from zoneinfo import ZoneInfo
    LONDON = ZoneInfo("Europe/London")
except Exception:                           # pragma: no cover
    LONDON = timezone.utc

ROOT = Path(__file__).resolve().parent.parent
ARTICLES = ROOT / "articles.json"
MANUAL = ROOT / "manual_articles.json"
FRONTPAGE = ROOT / "articles" / "frontpage.json"
WEATHER = ROOT / "weather.json"

SLOTS = {
    # slot: (local hour it must run at, title, window start hour)
    "morning": (9, "Morning Briefing", 18),   # since 6pm yesterday
    "evening": (18, "Evening Wrap-Up", 9),    # since 9am today
}

CARD_CANDIDATES = [
    "assets/img/cards/rochdale-town-hall.jpg",
    "assets/img/cards/rochdale.jpg",
    "assets/img/cards/news.jpg",
]


def load(path, default):
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return default


def as_list(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("articles") or data.get("items") or []
    return []


def parse_iso(value):
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def esc(value):
    return (
        str(value or "")
        .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def slugify(value):
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return re.sub(r"-{2,}", "-", text)[:80]


def window_start(slot: str, now_local: datetime) -> datetime:
    """The start of the period this briefing covers."""
    start_hour = SLOTS[slot][2]
    if slot == "morning":
        base = (now_local - timedelta(days=1)).replace(
            hour=start_hour, minute=0, second=0, microsecond=0
        )
    else:
        base = now_local.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    return base


def area_label(value):
    text = str(value or "").replace("-", " ").strip()
    return text.title() if text else ""


def pick_card():
    for candidate in CARD_CANDIDATES:
        if (ROOT / candidate).exists():
            return candidate
    found = sorted((ROOT / "assets" / "img" / "cards").glob("*.jpg"))
    return f"assets/img/cards/{found[0].name}" if found else ""


def weather_line(now_local):
    data = load(WEATHER, {})
    today = now_local.strftime("%Y-%m-%d")
    for day in data.get("days") or []:
        if str(day.get("date")) == today:
            temp = str(day.get("temperature_c") or "").strip()
            cond = str(day.get("condition") or "").strip()
            if not (temp or cond):
                return ""
            bits = " ".join(part for part in (cond, f"{temp}°C" if temp else "") if part)
            return f"<p><strong>Weather:</strong> {esc(bits)} in Rochdale today.</p>"
    return ""


def events_section(now_local, slot):
    """What is on today (morning) or tomorrow (evening)."""
    data = load(FRONTPAGE, {})
    target = now_local.date() if slot == "morning" else (now_local + timedelta(days=1)).date()
    hits = []
    for event in data.get("events") or []:
        start = parse_iso(event.get("event_start_at"))
        if not start:
            continue
        if start.astimezone(LONDON).date() != target:
            continue
        hits.append(event)
    if not hits:
        return ""
    label = "On today" if slot == "morning" else "On tomorrow"
    items = "".join(
        '<li><a href="/articles/{slug}.html">{title}</a>{place}</li>'.format(
            slug=esc(event.get("slug")),
            title=esc(event.get("title")),
            place=(" &mdash; " + esc(event.get("event_location"))) if event.get("event_location") else "",
        )
        for event in hits[:5]
    )
    return f"<h2>{label}</h2><ul>{items}</ul>"


def story_items(stories):
    rows = []
    for story in stories:
        area = area_label(story.get("area"))
        summary = str(story.get("excerpt") or story.get("summary") or "").strip()
        if len(summary) > 180:
            summary = summary[:177].rsplit(" ", 1)[0] + "…"
        rows.append(
            '<li><a href="/articles/{slug}.html"><strong>{title}</strong></a>'
            '{area}{summary}</li>'.format(
                slug=esc(story.get("slug")),
                title=esc(story.get("title")),
                area=f' <span class="brief-area">{esc(area)}</span>' if area else "",
                summary=f"<br>{esc(summary)}" if summary else "",
            )
        )
    return "".join(rows)


def build(slot: str, now_local: datetime):
    _, title_word, _ = SLOTS[slot]
    start = window_start(slot, now_local)

    published = [
        story for story in as_list(load(ARTICLES, []))
        if str(story.get("status") or "published") == "published"
        and not str(story.get("id") or "").startswith("briefing-")
    ]
    fresh = []
    for story in published:
        moment = parse_iso(story.get("first_published_at") or story.get("published_at"))
        if moment and start <= moment.astimezone(LONDON) <= now_local:
            fresh.append(story)
    fresh.sort(
        key=lambda s: parse_iso(s.get("first_published_at") or s.get("published_at")) or start,
        reverse=True,
    )

    date_text = now_local.strftime("%A %-d %B %Y") if hasattr(now_local, "strftime") else ""
    title = f"{title_word}: {date_text}"
    since = "since yesterday evening" if slot == "morning" else "today"

    if fresh:
        count = len(fresh)
        lead = (
            f"{count} new {'story' if count == 1 else 'stories'} in the Rochdale borough {since}."
        )
        body = f"<p>{esc(lead)}</p><h2>The stories</h2><ul>{story_items(fresh[:12])}</ul>"
    else:
        # The honest quiet-day version. No padding, no invented urgency.
        lead = f"A quiet {'night' if slot == 'morning' else 'day'} in the borough &mdash; nothing new published {since}."
        live = published[:5]
        body = f"<p>{lead}</p>"
        if live:
            body += "<h2>Still worth reading</h2><ul>" + story_items(live) + "</ul>"

    body += weather_line(now_local)
    body += events_section(now_local, slot)
    body += (
        '<p class="brief-foot">The '
        + esc(title_word)
        + " is published every day at "
        + ("9am" if slot == "morning" else "6pm")
        + '. Got a story? <a href="/contact.html">Tell the newsdesk</a>.</p>'
    )

    slug = slugify(f"{title_word}-{now_local.strftime('%-d-%B-%Y')}")
    stamp = now_local.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    excerpt = lead.replace("&mdash;", "—")

    return {
        "id": f"briefing-{slug}",
        "slug": slug,
        "title": title,
        "excerpt": excerpt,
        "summary": excerpt,
        "content_html": body,
        "body": re.sub(r"<[^>]+>", " ", body),
        "category": "news",
        "area": "rochdale",
        "types": ["news"],
        "image_url": pick_card(),
        "img": pick_card(),
        "image_credit": "Rochdale Daily",
        "image_status": "editorial-photo",
        "published_at": stamp,
        "first_published_at": stamp,
        "last_updated_at": stamp,
        "scraped_at": stamp,
        "source_name": "Rochdale Daily",
        "source_names": ["Rochdale Daily"],
        "byline": "Rochdale Daily",
        "status": "published",
        "manual_article": True,
        "editorial_lock": True,
        "rewrite_quality_checked": True,
        "briefing_slot": slot,
        "publication_route": "daily-briefing",
        "right_to_reply": (
            "Anyone named in a linked story can reply by emailing "
            "news@rochdaledaily.co.uk and we will publish or append their response."
        ),
    }


def already_published(slug: str) -> bool:
    for path in (ARTICLES, MANUAL):
        for story in as_list(load(path, [])):
            if story.get("slug") == slug:
                return True
    return bool(list(ROOT.glob(f"pending_manual_briefing_{slug}.json")))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--slot", choices=sorted(SLOTS) + ["auto"], required=True,
        help="morning, evening, or auto (the most recent slot by the London clock; "
             "for manual runs, so pressing the button always produces a briefing).",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Build even if it is not the scheduled local hour (for testing).",
    )
    args = parser.parse_args()

    now_local = datetime.now(timezone.utc).astimezone(LONDON)
    if args.slot == "auto":
        # The briefing a reader would expect to find right now: the evening
        # edition from 6pm onwards, otherwise the morning edition from 9am,
        # otherwise (small hours) last night's evening edition.
        args.slot = "evening" if now_local.hour >= 18 or now_local.hour < 9 else "morning"
        if now_local.hour < 9:
            now_local = now_local - timedelta(days=1)
            now_local = now_local.replace(hour=18, minute=0, second=0, microsecond=0)
        args.force = True
        print(f"auto: building the {args.slot} briefing for {now_local:%A %d %B}")
    wanted_hour = SLOTS[args.slot][0]

    # GitHub cron only speaks UTC, so the workflow fires on both candidate hours
    # and this gate keeps the briefing at 9am/6pm LOCAL through BST and GMT
    # alike. An appointment that moves by an hour in October is not one.
    if not args.force and now_local.hour != wanted_hour:
        print(
            f"Not the {args.slot} slot in Europe/London "
            f"(local hour {now_local.hour}, want {wanted_hour}); nothing to do."
        )
        return

    article = build(args.slot, now_local)
    if already_published(article["slug"]):
        print(f"{article['title']} already exists; not duplicating.")
        return

    out = ROOT / f"pending_manual_briefing_{article['slug']}.json"
    with out.open("w", encoding="utf-8") as handle:
        json.dump([article], handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(f"Wrote {out.name}: {article['title']}")


if __name__ == "__main__":
    main()
