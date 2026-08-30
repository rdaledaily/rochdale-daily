#!/usr/bin/env python3
"""Greater Manchester Police breaking-news watcher.

Why this exists
---------------
The newsroom pipeline notices a GMP post when the next fast-lane run happens to
come round. Measured over a week of real runs, that is a median 33-minute gap
between runs -- so a post lands, on average, 17 minutes before anything looks at
it, and one gap in ten is over an hour. Then the post waits behind whatever else
the run is doing.

This watcher does one job only: poll GMP, notice a Rochdale-borough post within
about a minute, and write it to ``breaking.json``. It publishes nothing itself
and holds no site-writer lock. The Cloudflare Pages Function reads
``breaking.json`` at request time, so the story is live as soon as Pages has
deployed the commit -- no site rebuild, no queue behind the scrape.

Editorial form
--------------
Breaking entries carry GMP's own words, quoted and attributed. There is no model
call in this path. That is the fastest form and the safest one: reporting an
attributed police statement is a different legal proposition from paraphrasing
it in seconds without anyone reading it first.

The legal gate
--------------
Anything carrying charge, court, coroner or sexual-offence language is held, not
published, and surfaced for the editor. That is where contempt of court and the
automatic lifetime anonymity of complainants in sexual offence cases actually
bite. Holding is the default on any doubt: an unrecognised phrase holds.

Politeness
----------
robots.txt is honoured -- the site publishes that promise, so this keeps it. A
discovered feed is preferred over the HTML listing. Every poll is conditional
(ETag / If-Modified-Since), so a quiet hour is 60 cheap 304s rather than 60 page
fetches. Failures back off. The identifying User-Agent matches the rest of the
pipeline.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
import unicodedata
import urllib.robotparser
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

log = logging.getLogger("gmp_watch")

USER_AGENT = (
    "RochdaleDaily/3.2 (+https://rochdaledaily.co.uk; "
    "contact: news@rochdaledaily.co.uk)"
)

BREAKING_FILE = Path(os.getenv("BREAKING_JSON", ROOT / "breaking.json"))
STATE_FILE = Path(
    os.getenv("GMP_WATCH_STATE", ROOT / "reports" / "gmp_watch_state.json")
)

# The two GMP listings worth watching. News carries statements and incident
# updates; Appeals carries witness and missing-person calls, which are the ones
# a local paper can genuinely help with.
GMP_LISTINGS = [
    "https://www.gmp.police.uk/news/news-search/?ct=News",
    "https://www.gmp.police.uk/news/news-search/?ct=Appeals",
]
GMP_HOME = "https://www.gmp.police.uk/"

# How long a breaking entry stays on the front page before it expires on its
# own. The pipeline normally supersedes it long before this; the timer exists so
# that a failure of the pipeline cannot pin a stale story indefinitely.
BREAKING_TTL_HOURS = int(os.getenv("BREAKING_TTL_HOURS", "18"))

# Never carry more than this many live breaking cards at once.
MAX_LIVE_BREAKING = int(os.getenv("MAX_LIVE_BREAKING", "3"))

# A post older than this when first seen is not breaking news; it belongs to the
# normal pipeline. Stops a first run, or a listing reshuffle, dumping a backlog
# of week-old appeals onto the front page.
MAX_POST_AGE_MINUTES = int(os.getenv("GMP_MAX_POST_AGE_MINUTES", "180"))


# --------------------------------------------------------------------------
# The legal gate
# --------------------------------------------------------------------------

# Active criminal proceedings, coronial proceedings, and offences carrying
# automatic complainant anonymity. A match holds the story for the editor.
HOLD_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bcharged\b|\bcharges?\b(?!\s+(?:for|of)\s+(?:entry|admission))", "charge"),
    (r"\bcourt\b|\bmagistrates?\b|\bcrown court\b", "court"),
    (r"\bappear(?:ed|ing|s)? (?:before|at|in)\b", "court appearance"),
    (r"\bsentenc(?:ed|ing|e)\b|\bjailed\b|\bimprison", "sentencing"),
    (r"\bplead(?:ed|s|ing)?\b|\bguilty\b|\bnot guilty\b", "plea"),
    (r"\bconvict(?:ed|ion)\b|\bacquitt", "conviction"),
    (r"\btrial\b|\bremand(?:ed)?\b|\bjury\b", "proceedings"),
    (r"\bcoroner\b|\binquest\b", "coronial proceedings"),
    # "sexually assaulted" and "sexual assault" are both common in GMP copy, so
    # the adverb form has to be matched too -- an early version of this pattern
    # caught only the noun and would have published the other.
    (r"\brap(?:e|ed|ing)\b"
     r"|\bsexual(?:ly)?\s+(?:offence|assault(?:ed|s)?|abuse[ds]?|activity|touch)"
     r"|\bindecent\b|\bgroom(?:ed|ing)\b|\bupskirt", "sexual offence"),
    (r"\bmurder charge\b|\bmanslaughter charge\b", "charge"),
    (r"\bcontempt of court\b|\breporting restriction", "reporting restriction"),
    (r"\bsuicide\b|\btook (?:his|her|their) own life\b", "sensitive death"),
)

# Safeguarding language about a child holds regardless of the rest. A bare
# mention of a child does not -- "a 12-year-old boy was hurt in the collision"
# is ordinary incident reporting.
CHILD_PATTERN = re.compile(
    r"\b(?:child|children|boy|girl|teenager|pupil|schoolgirl|schoolboy"
    r"|\d{1,2}[- ]year[- ]old)\b",
    re.IGNORECASE,
)
# Inflections matter here: "neglected" must match as surely as "neglect".
SAFEGUARDING_PATTERN = re.compile(
    r"\b(?:abus(?:e|ed|ing)|exploit(?:ed|ation|ing)?|neglect(?:ed|ing)?"
    r"|safeguard(?:ing)?|groom(?:ed|ing)?|indecent|child protection"
    r"|cruelty|trafficked|trafficking)\b",
    re.IGNORECASE,
)

_COMPILED_HOLDS = tuple(
    (re.compile(pattern, re.IGNORECASE), reason) for pattern, reason in HOLD_PATTERNS
)


def hold_reason(title: str, body: str = "") -> str:
    """Return why a post must be held, or '' if it may publish itself.

    Fails closed by design: an unfamiliar phrasing that trips any pattern holds.
    A held story is not lost -- it is written to breaking.json with status
    'held' and surfaced to the editor.
    """
    text = f"{title}\n{body}"
    for pattern, reason in _COMPILED_HOLDS:
        if pattern.search(text):
            return reason
    if CHILD_PATTERN.search(text) and SAFEGUARDING_PATTERN.search(text):
        return "child safeguarding"
    return ""


# --------------------------------------------------------------------------
# Text and time helpers
# --------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(value: str) -> str:
    text = _TAG_RE.sub(" ", str(value or ""))
    text = unescape(text)
    text = unicodedata.normalize("NFKC", text)
    return _WS_RE.sub(" ", text).strip()


def slugify(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return re.sub(r"-{2,}", "-", text)[:90] or "gmp-update"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            from email.utils import parsedate_to_datetime

            parsed = parsedate_to_datetime(text)
        except Exception:
            return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def canonical_url(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    path = (parsed.path or "/").rstrip("/") or "/"
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{parsed.scheme or 'https'}://{host}{path}{query}"


# --------------------------------------------------------------------------
# Locality
# --------------------------------------------------------------------------


def is_borough_story(title: str, body: str, source_url: str) -> tuple[bool, str]:
    """Return (is_local, area). GMP covers ten boroughs; most posts are not ours.

    Uses the pipeline's own locality rules so the watcher cannot drift from the
    rest of the paper -- including the false-friend guards that stop Middleton,
    Massachusetts and surnames like Heywood being read as places.
    """
    text = f"{title}\n{body}"
    try:
        from locality_rules import detect_area, has_disqualifying_evidence, is_local
    except Exception:  # pragma: no cover - only if the module is missing
        log.warning("locality_rules unavailable; holding everything as non-local")
        return False, ""
    if has_disqualifying_evidence(text):
        return False, ""
    if not is_local(text, "Greater Manchester Police", source_url):
        return False, ""
    area = detect_area(text, "", "Greater Manchester Police", source_url) or ""
    return bool(area), area


# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------


class Fetcher:
    """Conditional, robots-respecting HTTP with per-URL validators."""

    def __init__(self, session: Any = None) -> None:
        import requests

        self.session = session or requests.Session()
        self.session.headers.update(
            {"User-Agent": USER_AGENT, "Accept-Language": "en-GB,en;q=0.9"}
        )
        self.validators: dict[str, dict[str, str]] = {}
        self._robots: dict[str, Any] = {}

    def robots_allows(self, url: str) -> bool:
        if os.getenv("RESPECT_ROBOTS", "true").lower() in {"0", "false", "no", "off"}:
            return True
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        robot = self._robots.get(base)
        if robot is None:
            robot = urllib.robotparser.RobotFileParser()
            robot.set_url(urljoin(base, "/robots.txt"))
            try:
                robot.read()
            except Exception:
                log.warning("robots.txt unreadable for %s; allowing one plain request", base)
                self._robots[base] = False  # cache the "could not read" verdict
                return True
            self._robots[base] = robot
        if robot is False:
            return True
        try:
            return robot.can_fetch(USER_AGENT, url)
        except Exception:
            return True

    def get(self, url: str, timeout: int = 20) -> tuple[int, str]:
        """Return (status, text). 304 returns an empty body -- nothing changed."""
        if not self.robots_allows(url):
            log.info("robots.txt declines %s; skipping", url)
            return 999, ""
        headers: dict[str, str] = {}
        cached = self.validators.get(url) or {}
        if cached.get("etag"):
            headers["If-None-Match"] = cached["etag"]
        if cached.get("last_modified"):
            headers["If-Modified-Since"] = cached["last_modified"]
        response = self.session.get(url, headers=headers, timeout=timeout)
        status = int(getattr(response, "status_code", 0) or 0)
        if status == 304:
            return 304, ""
        if status >= 400:
            return status, ""
        new_validators = {}
        response_headers = getattr(response, "headers", {}) or {}
        if response_headers.get("ETag"):
            new_validators["etag"] = response_headers["ETag"]
        if response_headers.get("Last-Modified"):
            new_validators["last_modified"] = response_headers["Last-Modified"]
        if new_validators:
            self.validators[url] = new_validators
        return status, response.text or ""


# --------------------------------------------------------------------------
# Parsing: feed discovery first, HTML listing as the fallback
# --------------------------------------------------------------------------

_FEED_LINK_RE = re.compile(
    r"<link[^>]+(?:rel=[\"']alternate[\"'][^>]*type=[\"']application/(?:rss|atom)\+xml[\"']"
    r"|type=[\"']application/(?:rss|atom)\+xml[\"'][^>]*rel=[\"']alternate[\"'])[^>]*>",
    re.IGNORECASE,
)
_HREF_RE = re.compile(r"href=[\"']([^\"']+)[\"']", re.IGNORECASE)


def discover_feeds(html: str, base_url: str) -> list[str]:
    """Find declared RSS/Atom feeds. Never guesses a URL that isn't declared."""
    found: list[str] = []
    for tag in _FEED_LINK_RE.findall(html or ""):
        match = _HREF_RE.search(tag)
        if not match:
            continue
        url = urljoin(base_url, unescape(match.group(1)).strip())
        if url not in found:
            found.append(url)
    return found


def parse_feed(text: str) -> list[dict[str, str]]:
    """Parse an RSS/Atom body into raw items."""
    try:
        import feedparser
    except Exception:  # pragma: no cover
        return []
    parsed = feedparser.parse(text)
    items: list[dict[str, str]] = []
    for entry in getattr(parsed, "entries", []) or []:
        link = str(getattr(entry, "link", "") or "").strip()
        title = strip_html(getattr(entry, "title", "") or "")
        if not link or not title:
            continue
        body = ""
        for key in ("summary", "description"):
            value = getattr(entry, key, "") or ""
            if value:
                body = strip_html(value)
                break
        if not body:
            content = getattr(entry, "content", None) or []
            if content:
                body = strip_html(getattr(content[0], "value", "") or "")
        published = (
            getattr(entry, "published", "")
            or getattr(entry, "updated", "")
            or ""
        )
        items.append(
            {
                "url": link,
                "title": title,
                "body": body,
                "published": str(published),
            }
        )
    return items


_LISTING_ITEM_RE = re.compile(
    r"<a[^>]+href=[\"'](?P<href>[^\"']*/news/[^\"']+)[\"'][^>]*>(?P<label>.*?)</a>",
    re.IGNORECASE | re.DOTALL,
)
_TIME_TAG_RE = re.compile(
    r"<time[^>]*datetime=[\"'](?P<when>[^\"']+)[\"']", re.IGNORECASE
)


def parse_listing(html: str, base_url: str) -> list[dict[str, str]]:
    """Fallback parser for the GMP news-search listing page.

    Deliberately conservative: it takes link text as the headline and leaves the
    body empty, so the watcher fetches the article page for the statement rather
    than guessing it from listing furniture.
    """
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in _LISTING_ITEM_RE.finditer(html or ""):
        href = unescape(match.group("href")).strip()
        label = strip_html(match.group("label"))
        if not label or len(label) < 12:
            continue
        url = urljoin(base_url, href)
        if "/news-search" in url or url.rstrip("/").endswith("/news"):
            continue
        key = canonical_url(url)
        if key in seen:
            continue
        seen.add(key)
        window = html[match.end() : match.end() + 400]
        time_match = _TIME_TAG_RE.search(window)
        items.append(
            {
                "url": url,
                "title": label,
                "body": "",
                "published": time_match.group("when") if time_match else "",
            }
        )
    return items


_ARTICLE_BODY_RE = re.compile(
    r"<(?:article|main)[^>]*>(?P<body>.*?)</(?:article|main)>",
    re.IGNORECASE | re.DOTALL,
)
_PARAGRAPH_RE = re.compile(r"<p[^>]*>(?P<text>.*?)</p>", re.IGNORECASE | re.DOTALL)
_META_TIME_RE = re.compile(
    r"<meta[^>]+(?:property|name)=[\"'](?:article:published_time|datePublished)[\"']"
    r"[^>]*content=[\"'](?P<when>[^\"']+)[\"']",
    re.IGNORECASE,
)


def parse_article(html: str) -> dict[str, str]:
    """Pull the statement paragraphs and publication time from a GMP page."""
    scope = html or ""
    body_match = _ARTICLE_BODY_RE.search(scope)
    if body_match:
        scope = body_match.group("body")
    paragraphs = [strip_html(p) for p in _PARAGRAPH_RE.findall(scope)]
    paragraphs = [p for p in paragraphs if len(p) > 40]
    time_match = _META_TIME_RE.search(html or "")
    if not time_match:
        time_match = _TIME_TAG_RE.search(html or "")
    return {
        "body": "\n\n".join(paragraphs[:6]),
        "published": time_match.group("when") if time_match else "",
    }


# --------------------------------------------------------------------------
# Building a breaking entry
# --------------------------------------------------------------------------


def normalise_headline(title: str) -> str:
    """House-style the headline without changing what it says.

    GMP writes headlines in sentence case with a location prefix
    ("Rochdale | Appeal for witnesses after..."). Strip the prefix furniture and
    leave the wording alone -- this is not a rewrite.
    """
    text = strip_html(title)
    text = re.sub(r"^\s*[A-Za-z ]{3,20}\s*[|:–-]\s*", "", text, count=1)
    text = text.strip(" –-—|:")
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    return text


def build_entry(item: dict[str, str], now: datetime | None = None) -> dict[str, Any]:
    """Turn a raw GMP item into a breaking record. No model call, ever."""
    now = now or utc_now()
    title = normalise_headline(item.get("title", ""))
    body = strip_html(item.get("body", ""))
    url = str(item.get("url", "")).strip()
    published = parse_time(item.get("published")) or now
    reason = hold_reason(title, body)
    local, area = is_borough_story(title, body, url)
    entry: dict[str, Any] = {
        "slug": slugify(title),
        "title": title,
        "quote": body,
        "source_name": "Greater Manchester Police",
        "source_url": url,
        "source_published_at": iso_utc(published),
        "detected_at": iso_utc(now),
        "published_at": iso_utc(now),
        "expires_at": iso_utc(now + timedelta(hours=BREAKING_TTL_HOURS)),
        "area": area or "rochdale",
        "category": "crime",
        "image_url": "assets/img/cards/police.jpg",
        "byline": "Rochdale Daily",
        "attribution": "Greater Manchester Police said:",
        "developing": True,
        "status": "live",
    }
    if not local:
        entry["status"] = "ignored"
        entry["hold_reason"] = "outside the Rochdale borough"
    elif reason:
        entry["status"] = "held"
        entry["hold_reason"] = reason
    return entry


def is_fresh(entry: dict[str, Any], now: datetime | None = None) -> bool:
    """A post already hours old when first seen is not breaking news."""
    now = now or utc_now()
    published = parse_time(entry.get("source_published_at"))
    if published is None:
        return True
    age_minutes = (now - published).total_seconds() / 60
    return age_minutes <= MAX_POST_AGE_MINUTES


# --------------------------------------------------------------------------
# State and file writing
# --------------------------------------------------------------------------


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temp.replace(path)


def prune(items: Iterable[dict[str, Any]], now: datetime | None = None) -> list[dict[str, Any]]:
    """Drop expired and superseded entries; cap the live ones."""
    now = now or utc_now()
    kept: list[dict[str, Any]] = []
    for entry in items:
        if entry.get("status") == "superseded":
            continue
        expires = parse_time(entry.get("expires_at"))
        if expires and expires <= now:
            continue
        kept.append(entry)
    kept.sort(key=lambda e: str(e.get("published_at", "")), reverse=True)
    live = [e for e in kept if e.get("status") == "live"][:MAX_LIVE_BREAKING]
    held = [e for e in kept if e.get("status") == "held"]
    return live + held


def merge_breaking(existing: list[dict[str, Any]], fresh: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_url = {canonical_url(e.get("source_url", "")): e for e in existing}
    for entry in fresh:
        key = canonical_url(entry.get("source_url", ""))
        if key in by_url:
            continue
        by_url[key] = entry
    return prune(by_url.values())


# --------------------------------------------------------------------------
# Committing
# --------------------------------------------------------------------------


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(ROOT), capture_output=True, text=True, timeout=120
    )


def commit_and_push(message: str) -> bool:
    """Commit breaking.json and the watch state. Rebase-retries on a busy main."""
    git("config", "user.name", "Rochdale Daily Bot")
    git("config", "user.email", "bot@rochdaledaily.co.uk")
    git("add", str(BREAKING_FILE.relative_to(ROOT)), str(STATE_FILE.relative_to(ROOT)))
    if git("diff", "--cached", "--quiet").returncode == 0:
        return False
    git("commit", "-m", message)
    for attempt in range(1, 6):
        pull = git("pull", "--rebase", "--autostash", "origin", "main")
        if pull.returncode == 0 and git("push", "origin", "HEAD:main").returncode == 0:
            return True
        time.sleep(attempt * 3)
    log.error("breaking commit could not be pushed after five attempts")
    return False


# --------------------------------------------------------------------------
# One poll cycle
# --------------------------------------------------------------------------


def collect(fetcher: Fetcher, state: dict[str, Any]) -> list[dict[str, str]]:
    """Poll GMP once. Prefers a declared feed; falls back to the listing HTML."""
    feeds: list[str] = list(state.get("feeds") or [])
    if not feeds and not state.get("feed_discovery_done"):
        status, html = fetcher.get(GMP_HOME)
        if status == 200:
            feeds = discover_feeds(html, GMP_HOME)
            state["feeds"] = feeds
        state["feed_discovery_done"] = True
        if feeds:
            log.info("discovered GMP feeds: %s", ", ".join(feeds))
        else:
            log.info("GMP declares no feed; polling the news listing instead")

    raw: list[dict[str, str]] = []
    targets = feeds or GMP_LISTINGS
    for url in targets:
        try:
            status, text = fetcher.get(url)
        except Exception as error:
            log.warning("poll failed for %s: %s", url, error)
            continue
        if status == 304 or not text:
            continue
        if status != 200:
            log.warning("poll returned %s for %s", status, url)
            continue
        items = parse_feed(text) if feeds else parse_listing(text, url)
        raw.extend(items)
    return raw


def poll_once(fetcher: Fetcher, state: dict[str, Any], now: datetime | None = None) -> list[dict[str, Any]]:
    """Return newly-detected breaking entries and update state in place."""
    now = now or utc_now()
    seen: set[str] = set(state.get("seen") or [])
    raw = collect(fetcher, state)
    new_entries: list[dict[str, Any]] = []

    for item in raw:
        key = canonical_url(item.get("url", ""))
        if not key or key in seen:
            continue
        seen.add(key)
        # The listing gives a headline but no statement -- fetch the page for
        # GMP's own words, which is what we are going to quote.
        if not item.get("body"):
            try:
                status, html = fetcher.get(item["url"])
                if status == 200:
                    detail = parse_article(html)
                    item["body"] = detail["body"]
                    item["published"] = item.get("published") or detail["published"]
            except Exception as error:
                log.warning("could not read %s: %s", item.get("url"), error)
        entry = build_entry(item, now=now)
        if entry["status"] == "ignored":
            # GMP covers ten boroughs, so most rejections are correct. But some
            # are not: Rochdale has a Bury Road, an Oldham Road and a Bolton
            # Road, and a post that names the street without naming the town
            # reads as another borough's story to the locality rules. Rather
            # than guess at a fix, keep the last few rejections so the filter
            # can be judged on real GMP copy.
            rejected = list(state.get("rejected_recent") or [])
            rejected.insert(
                0,
                {
                    "title": entry["title"],
                    "url": entry["source_url"],
                    "at": iso_utc(now),
                },
            )
            state["rejected_recent"] = rejected[:40]
            continue
        if not is_fresh(entry, now=now):
            log.info("skipping (older than the breaking window): %s", entry["title"])
            continue
        if not entry["quote"]:
            log.info("skipping (no statement text to quote): %s", entry["title"])
            continue
        new_entries.append(entry)

    state["seen"] = sorted(seen)[-800:]
    state["last_poll_at"] = iso_utc(now)
    state["validators"] = fetcher.validators
    return new_entries


def retire_superseded(items: list[dict[str, Any]]) -> int:
    """Stand a breaking stub down once the pipeline has published the real thing.

    Running this on every poll rather than inside the publishing workflows keeps
    the change out of scrape-fast.yml and publish.yml -- the two workflows that
    must not break -- and still retires a stub within a minute of the canonical
    article appearing.
    """
    try:
        from retire_breaking import published_index
    except Exception:
        return 0
    try:
        index = published_index()
    except Exception as error:
        log.warning("could not read published articles: %s", error)
        return 0
    if not index:
        return 0
    retired = 0
    for entry in items:
        if entry.get("status") not in {"live", "held"}:
            continue
        slug = index.get(canonical_url(str(entry.get("source_url") or "")))
        if not slug:
            continue
        entry["status"] = "superseded"
        entry["superseded_by"] = slug
        entry["superseded_at"] = iso_utc(utc_now())
        retired += 1
        log.info("superseded by the pipeline: %s -> articles/%s.html", entry.get("slug"), slug)
    return retired


def run_once(fetcher: Fetcher, state: dict[str, Any], *, push: bool = True) -> int:
    now = utc_now()

    # Seed the seen-set from breaking.json itself, including superseded and
    # expired entries. The watch state is only committed when breaking.json
    # changes -- committing it every run would add roughly 700 commits a month,
    # and every commit to main is a Cloudflare deployment. Seeding from the file
    # that IS committed means a fresh run cannot re-raise a story it has already
    # covered, even having lost its own memory of it.
    known = load_json(BREAKING_FILE, {"items": []})
    seen = set(state.get("seen") or [])
    for entry in known.get("items") or []:
        key = canonical_url(str(entry.get("source_url") or ""))
        if key:
            seen.add(key)

    # Also seed from what the pipeline has ALREADY published. Without this the
    # watcher re-raises a GMP post the newsroom covered minutes earlier, and the
    # front page carries the story twice -- a breaking stub sitting above the
    # paper's own fuller article. Found against real data: the Section 60
    # authority in Rochdale town centre on 30 August was already published from
    # the GMP source URL before the watcher ever ran. Retiring it a poll later
    # is not good enough; it must never be raised.
    try:
        from retire_breaking import published_index

        for key in published_index():
            if key:
                seen.add(key)
    except Exception as error:
        log.warning("could not read published articles when seeding: %s", error)

    state["seen"] = sorted(seen)

    new_entries = poll_once(fetcher, state, now=now)
    breaking = load_json(BREAKING_FILE, {"items": []})
    items = list(breaking.get("items") or [])
    before = json.dumps(items, sort_keys=True)
    retire_superseded(items)
    merged = merge_breaking(items, new_entries)
    changed = json.dumps(merged, sort_keys=True) != before

    if changed or new_entries:
        write_json_atomic(
            BREAKING_FILE,
            {
                "generated_at": iso_utc(now),
                "note": (
                    "Breaking entries carry Greater Manchester Police's own words, "
                    "quoted and attributed. Written by scraper/gmp_watch.py; read "
                    "at request time by the Cloudflare Pages Functions."
                ),
                "items": merged,
            },
        )
    write_json_atomic(STATE_FILE, state)

    live = [e for e in new_entries if e["status"] == "live"]
    held = [e for e in new_entries if e["status"] == "held"]
    for entry in live:
        log.info("BREAKING: %s", entry["title"])
    for entry in held:
        log.info("HELD (%s): %s", entry.get("hold_reason"), entry["title"])

    if (changed or new_entries) and push:
        parts = []
        if live:
            parts.append(f"{len(live)} breaking")
        if held:
            parts.append(f"{len(held)} held for review")
        commit_and_push(
            "Record GMP breaking update" + (f" ({', '.join(parts)})" if parts else "")
        )
    return len(live)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=int, default=60, help="seconds between polls")
    parser.add_argument("--duration", type=int, default=0, help="total seconds to run")
    parser.add_argument("--no-push", action="store_true", help="write files, do not commit")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

    state = load_json(STATE_FILE, {})
    fetcher = Fetcher()
    fetcher.validators = dict(state.get("validators") or {})

    deadline = time.monotonic() + args.duration if args.duration else None
    polls = 0
    found = 0
    backoff = 0

    while True:
        try:
            found += run_once(fetcher, state, push=not args.no_push)
            backoff = 0
        except Exception as error:  # never let one bad poll end the watch
            backoff = min(backoff * 2 or args.interval, 600)
            log.warning("poll cycle failed (%s); backing off %ss", error, backoff)
        polls += 1
        if deadline is None or time.monotonic() >= deadline:
            break
        time.sleep(max(5, backoff or args.interval))

    log.info("watch finished: %d polls, %d breaking stories published", polls, found)
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(
                f"## GMP watch\n\n- polls: {polls}\n- breaking published: {found}\n"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
