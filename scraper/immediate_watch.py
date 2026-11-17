"""Immediate-news monitor: Rochdale Times, Roch Valley Radio and the MEN.

Polls the three outlets every two minutes (scraper/immediate_news.py says
where and why), flags immediate news -- missing people, power and water cuts,
school closures, traffic incidents, public warnings and live incidents -- and
the moment one appears that Rochdale Daily has not yet covered, starts the
fast lane, which writes immediate stories ahead of everything else.

It never publishes anything itself and never copies the outlets' words: the
fast lane writes Rochdale Daily's own story from the source, through every
existing gate.

Every poll is measured. reports/immediate_watch.json (uploaded as the run's
artifact and written into the run summary) records, per outlet, whether the
feed answered, and per immediate story: when the outlet published it, when
the monitor saw it, when the fast lane was started, and when Rochdale Daily's
story appeared -- the lag the editor cares about, in minutes.

Run: python scraper/immediate_watch.py --minutes 20 --interval 120
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import feedparser
import requests

from immediate_news import MONITORED_SOURCES, clean_title, immediate_kind, plain
from locality_rules import is_local

UTC = timezone.utc
ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = Path(os.getenv("IMMEDIATE_WATCH_STATE", ROOT / ".immediate-watch" / "state.json"))
REPORT_PATH = Path(os.getenv("IMMEDIATE_WATCH_REPORT", ROOT / "reports" / "immediate_watch.json"))
REPO = os.getenv("GITHUB_REPOSITORY", "rdaledaily/rochdale-daily")
LIVE_ARTICLES = f"https://raw.githubusercontent.com/{REPO}/main/articles.json"
LIVE_LEDGER = f"https://raw.githubusercontent.com/{REPO}/main/rewrite_ledger.json"
FAST_LANE = "scrape-fast.yml"
USER_AGENT = "RochdaleDaily/3.2 (+https://rochdaledaily.co.uk; contact: news@rochdaledaily.co.uk)"

# Only news from the last few hours is "immediate"; older items are history
# by the time the monitor first sees them (a fresh state after a lost cache).
FRESH_HOURS = 6
# Never start the fast lane more often than this: a run takes 15-25 minutes.
KICK_GAP = timedelta(minutes=8)
# How long the state remembers an item.
KEEP_DAYS = 3
STOPWORDS = set("""a an and the of in on at to for from by with after over as is are was were be been
has have had it its this that new into out up off about than after near amid say says said""".split())


def now_utc() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime | None) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z") if value else ""


def parse_when(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        pass
    try:
        parsed = parsedate_to_datetime(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def url_key(url: str) -> str:
    """Comparable form: no scheme, www, query, fragment, trailing slash or .amp."""
    parsed = urlparse(str(url or "").strip())
    host = parsed.netloc.lower().removeprefix("www.")
    path = re.sub(r"(?:\.amp|/amp)$", "", parsed.path.rstrip("/"))
    return f"{host}{path}"


def title_words(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9']+", clean_title(title).lower())
    return {w.strip("'") for w in words if len(w) > 2 and w not in STOPWORDS}


def same_headline(a: str, b: str) -> bool:
    """Two headlines on one story: most of the shorter one's words recur."""
    wa, wb = title_words(a), title_words(b)
    if len(wa) < 3 or len(wb) < 3:
        return False
    return len(wa & wb) / min(len(wa), len(wb)) >= 0.6


# --- reading the outlets ------------------------------------------------------

def fetch_feed(source: dict[str, Any], get: Callable[..., Any] = requests.get) -> dict[str, Any]:
    """One outlet's feed. A refusal is recorded as what it is, never hidden."""
    result: dict[str, Any] = {"key": source["key"], "name": source["name"], "route": source["route"],
                              "url": source["url"], "ok": False, "http_status": None, "items": [], "error": ""}
    try:
        response = get(source["url"], timeout=20, headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.1",
        })
    except requests.RequestException as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"[:300]
        return result
    result["http_status"] = response.status_code
    if response.status_code != 200:
        result["error"] = f"http {response.status_code}"
        return result
    parsed = feedparser.parse(response.content)
    if parsed.bozo and not parsed.entries:
        result["error"] = f"not a feed: {getattr(parsed, 'bozo_exception', '')}"[:300]
        return result
    for entry in parsed.entries:
        title = clean_title(entry.get("title"))
        link = str(entry.get("link") or "").strip()
        if not title or not link:
            continue
        published = None
        for key in ("published_parsed", "updated_parsed"):
            value = entry.get(key)
            if value:
                published = datetime(*value[:6], tzinfo=UTC)
                break
        result["items"].append({
            "id": url_key(entry.get("id") or link) if not link.startswith("https://news.google.com") else url_key(link),
            "title": title,
            "link": link,
            "summary": plain(entry.get("summary"))[:600],
            "published_at": iso(published),
        })
    result["ok"] = True
    return result


def about_borough(source: dict[str, Any], item: dict[str, Any]) -> bool:
    if source.get("borough_only"):
        return True
    return is_local(f"{item['title']}. {item['summary']}", source["name"], item["link"])


# --- what Rochdale Daily has already published ------------------------------

def load_published(get: Callable[..., Any] = requests.get) -> list[dict[str, Any]]:
    """Live articles.json from main (the monitor's checkout goes stale in a loop)."""
    try:
        response = get(LIVE_ARTICLES, timeout=30, headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"})
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        local = ROOT / "articles.json"
        data = json.loads(local.read_text(encoding="utf-8")) if local.exists() else []
    rows = data if isinstance(data, list) else data.get("articles", [])
    return [row for row in rows if isinstance(row, dict)]


def covering_article(item: dict[str, Any], published: list[dict[str, Any]]) -> dict[str, Any] | None:
    key = item["id"]
    link_key = url_key(item["link"])
    source_time = parse_when(item.get("published_at"))
    for article in published:
        urls = [article.get("source_url")] + list(article.get("source_urls") or [])
        keys = {url_key(u) for u in urls if u}
        if key in keys or link_key in keys:
            return article
    for article in published:
        when = parse_when(article.get("first_published_at") or article.get("published_at"))
        if source_time and when and abs(when - source_time) > timedelta(hours=48):
            continue
        if same_headline(item["title"], str(article.get("title") or "")):
            return article
    return None


# --- starting the fast lane -------------------------------------------------

def fast_lane_waiting(token: str, get: Callable[..., Any] = requests.get) -> bool:
    """True when a fast-lane run is already queued: it will collect the story."""
    try:
        response = get(f"https://api.github.com/repos/{REPO}/actions/workflows/{FAST_LANE}/runs",
                       params={"status": "queued", "per_page": 5}, timeout=20,
                       headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
        return response.status_code == 200 and bool(response.json().get("total_count"))
    except (requests.RequestException, ValueError):
        return False


def start_fast_lane(token: str, post: Callable[..., Any] = requests.post) -> tuple[bool, str]:
    try:
        response = post(f"https://api.github.com/repos/{REPO}/actions/workflows/{FAST_LANE}/dispatches",
                        json={"ref": "main", "inputs": {"chain": "0"}}, timeout=20,
                        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    except requests.RequestException as exc:
        return False, f"{type(exc).__name__}: {exc}"[:200]
    return response.status_code == 204, f"http {response.status_code}"


# --- one poll ---------------------------------------------------------------

def load_state() -> dict[str, Any]:
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if isinstance(state, dict) and isinstance(state.get("items"), dict):
            return state
    except (OSError, ValueError):
        pass
    return {"items": {}, "last_kick_at": "", "kicks": []}


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def poll(state: dict[str, Any], *, now: datetime, token: str = "",
         get: Callable[..., Any] = requests.get, post: Callable[..., Any] = requests.post,
         published: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Read all three outlets once, update state, start the fast lane if needed."""
    items: dict[str, Any] = state.setdefault("items", {})
    baseline = not items  # first poll after a lost cache: record, don't kick
    feeds = [fetch_feed(source, get) for source in MONITORED_SOURCES]
    published = load_published(get) if published is None else published
    uncovered_new: list[dict[str, Any]] = []

    for source, feed in zip(MONITORED_SOURCES, feeds):
        feed["immediate_seen"] = 0
        for item in feed["items"]:
            kind = immediate_kind(item["title"])
            if not kind or not about_borough(source, item):
                continue
            feed["immediate_seen"] += 1
            record = items.get(item["id"])
            if record is None:
                record = items[item["id"]] = {
                    "source": source["name"], "kind": kind, "title": item["title"], "link": item["link"],
                    "published_at": item["published_at"], "first_seen_at": iso(now),
                    "seen_in_baseline": baseline, "fast_lane_started_at": "",
                    "covered_at": "", "covered_by": "",
                }
            if not record.get("covered_at"):
                article = covering_article(item, published)
                if article is not None:
                    record["covered_at"] = str(article.get("first_published_at") or article.get("published_at") or iso(now))
                    record["covered_by"] = f"/articles/{article.get('slug')}"
            source_time = parse_when(record.get("published_at")) or parse_when(record["first_seen_at"])
            fresh = source_time is not None and now - source_time <= timedelta(hours=FRESH_HOURS)
            if not record.get("covered_at") and fresh and not record.get("fast_lane_started_at") and not baseline:
                uncovered_new.append(record)

    kick = {"wanted": bool(uncovered_new), "started": False, "detail": ""}
    if uncovered_new:
        last = parse_when(state.get("last_kick_at"))
        if last and now - last < KICK_GAP:
            kick["detail"] = f"fast lane started {int((now - last).total_seconds() // 60)} min ago; it will collect these"
        elif not token:
            kick["detail"] = "no GITHUB_TOKEN: cannot start the fast lane (dry run)"
        elif fast_lane_waiting(token, get):
            kick["detail"] = "a fast-lane run is already queued; it will collect these"
            for record in uncovered_new:
                record["fast_lane_started_at"] = iso(now)
        else:
            ok, detail = start_fast_lane(token, post)
            kick.update(started=ok, detail=detail)
            if ok:
                state["last_kick_at"] = iso(now)
                state.setdefault("kicks", []).append({"at": iso(now), "for": [r["title"] for r in uncovered_new]})
                for record in uncovered_new:
                    record["fast_lane_started_at"] = iso(now)

    cutoff = now - timedelta(days=KEEP_DAYS)
    for key in [k for k, r in items.items() if (parse_when(r.get("first_seen_at")) or now) < cutoff]:
        del items[key]
    state["kicks"] = [k for k in state.get("kicks", []) if (parse_when(k.get("at")) or now) >= cutoff]
    state["last_poll_at"] = iso(now)
    state["feeds"] = [{k: v for k, v in feed.items() if k != "items"} | {"items": len(feed["items"])} for feed in feeds]
    return {"feeds": state["feeds"], "kick": kick, "new_uncovered": [r["title"] for r in uncovered_new]}


# --- the report -------------------------------------------------------------

def minutes_between(a: Any, b: Any) -> int | None:
    start, end = parse_when(a), parse_when(b)
    if not start or not end:
        return None
    return round((end - start).total_seconds() / 60)


def build_report(state: dict[str, Any], now: datetime) -> dict[str, Any]:
    stories = []
    for record in state.get("items", {}).values():
        stories.append(record | {
            "seen_after_min": minutes_between(record.get("published_at"), record.get("first_seen_at")),
            "covered_after_min": minutes_between(record.get("published_at"), record.get("covered_at")),
            "waiting_min": None if record.get("covered_at") else minutes_between(record.get("published_at") or record.get("first_seen_at"), iso(now)),
        })
    stories.sort(key=lambda r: r.get("published_at") or r.get("first_seen_at") or "", reverse=True)
    covered = [s["covered_after_min"] for s in stories if s["covered_after_min"] is not None and not s.get("seen_in_baseline")]
    covered.sort()
    return {
        "generated_at": iso(now),
        "rule": "Immediate news from the Rochdale Times, Roch Valley Radio and the MEN starts the fast lane at once (editor, 17 Nov 2026).",
        "feeds": state.get("feeds", []),
        "stories": stories,
        "summary": {
            "immediate_stories": len(stories),
            "covered": sum(1 for s in stories if s.get("covered_at")),
            "waiting": sum(1 for s in stories if not s.get("covered_at")),
            "median_source_to_site_min": covered[len(covered) // 2] if covered else None,
            "fast_lane_starts": len(state.get("kicks", [])),
        },
    }


def markdown(report: dict[str, Any]) -> str:
    lines = ["## Immediate-news monitor", ""]
    lines.append("| Outlet | Route | Feed | Items | Immediate |")
    lines.append("|---|---|---|---|---|")
    for feed in report["feeds"]:
        status = "OK" if feed.get("ok") else f"FAILED ({feed.get('error') or feed.get('http_status')})"
        lines.append(f"| {feed['name']} | {feed['route']} | {status} | {feed.get('items', 0)} | {feed.get('immediate_seen', 0)} |")
    s = report["summary"]
    lines += ["", f"Immediate stories (last {KEEP_DAYS} days): {s['immediate_stories']} - covered {s['covered']}, "
              f"waiting {s['waiting']}; median outlet-to-site {s['median_source_to_site_min']} min; "
              f"fast-lane starts {s['fast_lane_starts']}.", ""]
    lines.append("| Outlet | Kind | Headline | Published | Seen after | On site after | Rochdale Daily |")
    lines.append("|---|---|---|---|---|---|---|")
    for story in report["stories"][:40]:
        on_site = f"{story['covered_after_min']} min" if story.get("covered_at") else f"WAITING {story.get('waiting_min')} min"
        lines.append(f"| {story['source']} | {story['kind']} | {story['title'][:90]} | {story.get('published_at') or '?'} | "
                     f"{story.get('seen_after_min')} min | {on_site} | {story.get('covered_by') or ''} |")
    return "\n".join(lines) + "\n"


def write_report(state: dict[str, Any], now: datetime) -> dict[str, Any]:
    report = build_report(state, now)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        Path(summary).write_text(markdown(report), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minutes", type=float, default=20, help="how long to keep polling")
    parser.add_argument("--interval", type=float, default=120, help="seconds between polls")
    args = parser.parse_args(argv)
    token = os.getenv("GITHUB_TOKEN", "")
    state = load_state()
    deadline = time.monotonic() + args.minutes * 60
    answered: dict[str, int] = {source["name"]: 0 for source in MONITORED_SOURCES}
    while True:
        now = now_utc()
        outcome = poll(state, now=now, token=token)
        save_state(state)
        write_report(state, now)
        ok = [f["name"] for f in outcome["feeds"] if f.get("ok")]
        bad = [f"{f['name']} ({f.get('error')})" for f in outcome["feeds"] if not f.get("ok")]
        print(f"{iso(now)} feeds ok={ok} failed={bad} new_uncovered={outcome['new_uncovered']} kick={outcome['kick']}", flush=True)
        for name in ok:
            answered[name] += 1
        if time.monotonic() + args.interval > deadline:
            break
        time.sleep(args.interval)
    # A feed that never answered during the whole run fails it, so a dead
    # source is fixed rather than lived with (editor's rule: nothing fails
    # "as expected"). One refused poll among ten is noise, not an outage.
    dead = [name for name, count in answered.items() if count == 0]
    if dead:
        print(f"::error::Monitor could not read: {', '.join(dead)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
