"""Measure what each candidate new source would actually contribute, before any of it is wired in.

The borough currently collects about 24 candidate leads a day across every
existing source. A 60-story daily newspaper cannot be configured out of that
number, so the gap has to be closed with new source classes. This probe is
read-only: it visits each candidate source once, honours robots.txt, counts how
many items it carries and how many are recent, and reports an items-per-day
estimate. Nothing is published and no source is added on the strength of a
guess -- the collectors are written afterwards, for the sources whose measured
yield justifies them.

Version 2. The first version measured its own defects rather than the sources:
it treated an unreadable robots.txt as a refusal (so open government APIs came
back "robots-denied"), and it hard-coded feed paths that turned out not to
exist (so live newsrooms came back "http-404"). Both are fixed here. Robots
verdicts are now reported precisely -- an explicit Disallow is a refusal, a site
with no robots.txt at all is not -- and feed URLs are discovered from the page
rather than guessed.
"""
from __future__ import annotations

import json
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "source_yield_report.json"

USER_AGENT = os.getenv(
    "PROBE_USER_AGENT",
    "RochdaleDailyBot/1.0 (+https://rochdaledaily.co.uk/about.html; news@rochdaledaily.co.uk)",
)
TIMEOUT = int(os.getenv("PROBE_TIMEOUT", "20"))
RECENT_DAYS = int(os.getenv("PROBE_RECENT_DAYS", "14"))

ALLOWED = "allowed"
DISALLOWED = "disallowed"
NO_ROBOTS = "no-robots-file"
ROBOTS_UNREACHABLE = "robots-unreachable"

_ROBOTS_CACHE: dict[str, tuple[str, urllib.robotparser.RobotFileParser | None]] = {}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def robots_verdict(url: str) -> tuple[str, bool]:
    """Return (verdict, may_fetch).

    robots.txt governs crawlers, and its absence is not a refusal: a site that
    serves no robots.txt has declined nothing. Only an explicit Disallow is
    treated as a refusal. A robots.txt we cannot reach at all is reported as
    unreachable and not fetched, so a network fault is never recorded as a
    publisher saying no.
    """
    parts = urllib.parse.urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    if origin not in _ROBOTS_CACHE:
        request = urllib.request.Request(
            f"{origin}/robots.txt", headers={"User-Agent": USER_AGENT}
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                body = response.read(500_000).decode("utf-8", errors="replace")
            parser = urllib.robotparser.RobotFileParser()
            parser.parse(body.splitlines())
            _ROBOTS_CACHE[origin] = (ALLOWED, parser)
        except urllib.error.HTTPError as error:
            # 404/410 mean there is no robots.txt; anything else is a fault.
            if error.code in (404, 410):
                _ROBOTS_CACHE[origin] = (NO_ROBOTS, None)
            else:
                _ROBOTS_CACHE[origin] = (ROBOTS_UNREACHABLE, None)
        except (urllib.error.URLError, socket.timeout, OSError, ValueError):
            _ROBOTS_CACHE[origin] = (ROBOTS_UNREACHABLE, None)

    verdict, parser = _ROBOTS_CACHE[origin]
    if verdict == NO_ROBOTS:
        return NO_ROBOTS, True
    if verdict == ROBOTS_UNREACHABLE:
        return ROBOTS_UNREACHABLE, False
    try:
        permitted = parser.can_fetch(USER_AGENT, url) if parser else False
    except Exception:  # noqa: BLE001 - a malformed robots file must not crash the probe
        return ROBOTS_UNREACHABLE, False
    return (ALLOWED, True) if permitted else (DISALLOWED, False)


def fetch(url: str) -> tuple[int, str]:
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read(4_000_000)
            return response.status, body.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        return error.code, ""
    except (urllib.error.URLError, socket.timeout, OSError, ValueError):
        return 0, ""


def parse_dt(value: Any) -> datetime | None:
    """Accept the shapes open registers actually publish: ISO stamps, bare dates,
    year-months (police data is monthly) and POSIX seconds (Reddit)."""
    if value in (None, "", []):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip().replace("Z", "+00:00")
    if text.replace(".", "", 1).isdigit() and len(text.split(".")[0]) >= 9:
        try:
            return datetime.fromtimestamp(float(text), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if len(text) == 7 and text[4] == "-":  # YYYY-MM, e.g. police monthly extracts
        text = f"{text}-01"
    for candidate in (text, text[:19], text[:10]):
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def count_recent(dates: list[datetime | None], *, days: int, reference: datetime) -> int:
    cutoff = reference - timedelta(days=days)
    return sum(1 for value in dates if value is not None and value >= cutoff)


def per_day(recent: int, days: int) -> float:
    return round(recent / days, 2) if days else 0.0


FEED_LINK = re.compile(
    r"""<link[^>]+(?:type=["']application/(?:rss|atom)\+xml["'][^>]*href=["']([^"']+)["']"""
    r"""|href=["']([^"']+)["'][^>]*type=["']application/(?:rss|atom)\+xml["'])""",
    re.IGNORECASE,
)
FEED_GUESS = re.compile(r"""href=["']([^"']*(?:/feed/?|\.rss|/rss(?:\.xml)?)(?:\?[^"']*)?)["']""", re.I)


def discover_feeds(html: str, base_url: str) -> list[str]:
    """Find a site's own declared feeds rather than guessing a path."""
    found: list[str] = []
    for match in FEED_LINK.finditer(html):
        href = match.group(1) or match.group(2)
        if href:
            found.append(urllib.parse.urljoin(base_url, href))
    if not found:
        for match in FEED_GUESS.finditer(html):
            found.append(urllib.parse.urljoin(base_url, match.group(1)))
    seen: set[str] = set()
    ordered: list[str] = []
    for url in found:
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered[:5]


def feed_dates(body: str) -> list[datetime | None]:
    try:
        import feedparser
    except ImportError:
        return []
    parsed = feedparser.parse(body)
    dates: list[datetime | None] = []
    for entry in parsed.entries:
        value = parse_dt(
            entry.get("published") or entry.get("updated") or entry.get("created")
        )
        if value is None and getattr(entry, "published_parsed", None):
            try:
                value = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                value = None
        dates.append(value)
    return dates


def json_dates(body: str, *, list_path: list[str], date_keys: list[str]) -> list[datetime | None]:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return []
    node: Any = payload
    for key in list_path:
        if isinstance(node, dict):
            node = node.get(key)
        else:
            node = None
            break
    if not isinstance(node, list):
        node = payload if isinstance(payload, list) else []
    dates: list[datetime | None] = []
    for item in node:
        if not isinstance(item, dict):
            continue
        stamp = None
        for key in date_keys:
            nested = item
            for part in key.split("."):
                nested = nested.get(part) if isinstance(nested, dict) else None
            if nested:
                stamp = nested
                break
        dates.append(parse_dt(stamp))
    return dates


def measured(dates: list[datetime | None], *, status: str = "ok", **extra: Any) -> dict[str, Any]:
    recent = count_recent(dates, days=RECENT_DAYS, reference=now_utc())
    return {
        "status": status if dates else "empty",
        "items": len(dates),
        "recent_items": recent,
        "per_day": per_day(recent, RECENT_DAYS),
        **extra,
    }


def blocked(verdict: str, url: str) -> dict[str, Any]:
    return {
        "status": "robots-denied" if verdict == DISALLOWED else verdict,
        "items": 0,
        "recent_items": 0,
        "per_day": 0.0,
        "robots": verdict,
        "note": f"{verdict} for {url}",
    }


def http_probe(
    url: str,
    *,
    kind: str,
    list_path: list[str] | None = None,
    date_keys: list[str] | None = None,
) -> dict[str, Any]:
    verdict, may_fetch = robots_verdict(url)
    if not may_fetch:
        return blocked(verdict, url)
    code, body = fetch(url)
    if code != 200 or not body:
        return {
            "status": f"http-{code}",
            "items": 0,
            "recent_items": 0,
            "per_day": 0.0,
            "robots": verdict,
            "url": url,
        }
    dates = feed_dates(body) if kind == "feed" else json_dates(
        body, list_path=list_path or [], date_keys=date_keys or []
    )
    return measured(dates, robots=verdict, url=url)


def discovered_feed_probe(page_url: str) -> dict[str, Any]:
    """Read a newsroom's own declared feed instead of guessing its address."""
    verdict, may_fetch = robots_verdict(page_url)
    if not may_fetch:
        return blocked(verdict, page_url)
    code, body = fetch(page_url)
    if code != 200 or not body:
        return {
            "status": f"http-{code}",
            "items": 0,
            "recent_items": 0,
            "per_day": 0.0,
            "robots": verdict,
            "url": page_url,
        }
    feeds = discover_feeds(body, page_url)
    if not feeds:
        return {
            "status": "no-feed-declared",
            "items": 0,
            "recent_items": 0,
            "per_day": 0.0,
            "robots": verdict,
            "url": page_url,
            "note": "page reachable but declares no RSS/Atom feed; needs an HTML collector",
        }
    for feed_url in feeds:
        feed_verdict, feed_ok = robots_verdict(feed_url)
        if not feed_ok:
            continue
        feed_code, feed_body = fetch(feed_url)
        if feed_code != 200 or not feed_body:
            continue
        dates = feed_dates(feed_body)
        if dates:
            return measured(dates, robots=feed_verdict, url=feed_url, feeds_found=len(feeds))
    return {
        "status": "feed-unreadable",
        "items": 0,
        "recent_items": 0,
        "per_day": 0.0,
        "robots": verdict,
        "url": feeds[0],
        "feeds_found": len(feeds),
    }


def police_probe() -> dict[str, Any]:
    """Ask the API which month it has before asking for that month's crimes.

    Version 1 asked for a fixed month two months back and got an empty list;
    the publication lag is not fixed, so the month has to be read first.
    """
    verdict, may_fetch = robots_verdict("https://data.police.uk/api/crime-last-updated")
    if not may_fetch:
        return blocked(verdict, "https://data.police.uk/")
    code, body = fetch("https://data.police.uk/api/crime-last-updated")
    month = ""
    if code == 200:
        try:
            month = str(json.loads(body).get("date") or "")
        except (json.JSONDecodeError, AttributeError):
            month = ""
    if not month:
        return {
            "status": f"http-{code}",
            "items": 0,
            "recent_items": 0,
            "per_day": 0.0,
            "robots": verdict,
            "note": "could not read the latest available crime month",
        }
    url = (
        "https://data.police.uk/api/crimes-street/all-crime"
        f"?lat=53.6136&lng=-2.1610&date={month}"
    )
    code, body = fetch(url)
    if code != 200 or not body:
        return {
            "status": f"http-{code}",
            "items": 0,
            "recent_items": 0,
            "per_day": 0.0,
            "robots": verdict,
            "url": url,
        }
    try:
        records = json.loads(body)
    except json.JSONDecodeError:
        records = []
    count = len(records) if isinstance(records, list) else 0
    # Monthly bulk data: the rate that matters is records per month, not per day
    # of publication, so it is reported as its own figure and left out of the
    # daily total rather than being annualised into a misleading number.
    return {
        "status": "ok" if count else "empty",
        "items": count,
        "recent_items": count,
        "per_day": 0.0,
        "robots": verdict,
        "url": url,
        "note": f"{count} crimes in {month} within one mile of Rochdale centre; monthly bulk, not a daily feed",
    }


def gazette_probe() -> dict[str, Any]:
    """The Gazette's feed needs indexed location parameters (location-postcode-1)."""
    url = (
        "https://www.thegazette.co.uk/all-notices/notice/data.json"
        "?location-local-authority-1=Rochdale&results-page-size=100"
    )
    return http_probe(
        url,
        kind="json",
        list_path=["entry"],
        date_keys=["updated", "published", "f:notice-publication-date"],
    )


SOURCES: list[dict[str, Any]] = [
    {
        "name": "The Gazette official public record",
        "class": "primary record",
        "licence": "Open Government Licence",
        "probe": gazette_probe,
        "story_shape": "insolvencies, company strike-offs, statutory and planning notices",
    },
    {
        "name": "Police street-level crime (data.police.uk)",
        "class": "primary record",
        "licence": "Open Government Licence",
        "probe": police_probe,
        "story_shape": "ward crime counts, month-on-month movement, hotspot streets",
    },
    {
        "name": "UK Parliament written questions",
        "class": "civic",
        "licence": "Open Parliament Licence",
        "probe": lambda: http_probe(
            "https://questions-statements.api.parliament.uk/api/writtenquestions/questions"
            "?take=100&expandMember=true",
            kind="json",
            list_path=["results"],
            date_keys=["value.dateTabled", "dateTabled"],
        ),
        "story_shape": "what the borough's MPs asked, said and voted for this week",
    },
    {
        "name": "UK Parliament petitions",
        "class": "civic",
        "licence": "Open Parliament Licence",
        "probe": lambda: http_probe(
            "https://petition.parliament.uk/petitions.json?state=open",
            kind="json",
            list_path=["data"],
            date_keys=["attributes.created_at", "created_at"],
        ),
        "story_shape": "petitions signed locally, with constituency signature counts",
    },
    {
        "name": "Environment Agency flood warnings",
        "class": "public safety",
        "licence": "Open Government Licence",
        "probe": lambda: http_probe(
            "https://environment.data.gov.uk/flood-monitoring/id/floods",
            kind="json",
            list_path=["items"],
            date_keys=["timeRaised"],
        ),
        "story_shape": "live flood alerts on the Roch, Beal and Irk",
    },
    {
        "name": "Greater Manchester Fire and Rescue",
        "class": "public safety",
        "licence": "publisher feed",
        "probe": lambda: discovered_feed_probe("https://manchesterfire.gov.uk/news/"),
        "story_shape": "incidents and safety appeals in the borough",
    },
    {
        "name": "Northern Care Alliance NHS",
        "class": "public services",
        "licence": "publisher feed",
        "probe": lambda: discovered_feed_probe("https://www.northerncarealliance.nhs.uk/news"),
        "story_shape": "Rochdale Infirmary services, waits, recruitment, closures",
    },
    {
        "name": "Rochdale council news",
        "class": "civic",
        "licence": "publisher feed",
        "probe": lambda: discovered_feed_probe("https://www.rochdale.gov.uk/news"),
        "story_shape": "already collected; probed here as the yield baseline",
    },
    {
        "name": "Rochdale planning public access",
        "class": "primary record",
        "licence": "council portal (robots-governed)",
        "probe": lambda: http_probe(
            "https://publicaccess.rochdale.gov.uk/online-applications/search.do?action=weeklyList",
            kind="feed",
        ),
        "story_shape": "applications lodged and decided, weekly, with addresses",
    },
    {
        "name": "Rochdale council democracy (ModernGov)",
        "class": "civic",
        "licence": "council portal (robots-governed)",
        "probe": lambda: http_probe(
            "https://democracy.rochdale.gov.uk/mgListCommittees.aspx?bcr=1",
            kind="feed",
        ),
        "story_shape": "committee decisions, attendance, voting records by ward",
    },
    {
        "name": "Reddit r/rochdale",
        "class": "social listening",
        "licence": "public JSON endpoint",
        "probe": lambda: http_probe(
            "https://www.reddit.com/r/rochdale/new.json?limit=100",
            kind="json",
            list_path=["data", "children"],
            date_keys=["data.created_utc"],
        ),
        "story_shape": "resident-reported incidents and complaints, as leads only",
    },
    {
        "name": "Bluesky local post search",
        "class": "social listening",
        "licence": "public API, app password",
        "probe": lambda: key_gated(
            "BLUESKY_APP_PASSWORD",
            "free: create an app password on bsky.app and store it as a repository secret",
        ),
        "story_shape": "local accounts and keyword sweeps, as leads only",
    },
    {
        "name": "Companies House register",
        "class": "primary record",
        "licence": "free API key",
        "probe": lambda: key_gated(
            "COMPANIES_HOUSE_API_KEY",
            "free: register at developer.company-information.service.gov.uk",
        ),
        "story_shape": "new businesses, insolvencies and dissolutions by postcode",
    },
    {
        "name": "Charity Commission register",
        "class": "primary record",
        "licence": "free API key",
        "probe": lambda: key_gated(
            "CHARITY_COMMISSION_API_KEY",
            "free: register at api-portal.charitycommission.gov.uk",
        ),
        "story_shape": "local charity accounts, new registrations, closures",
    },
    {
        "name": "National Highways network updates",
        "class": "transport",
        "licence": "free API key (DATEX II)",
        "probe": lambda: key_gated(
            "NATIONAL_HIGHWAYS_API_KEY",
            "free: register at api.data.nationalhighways.co.uk",
        ),
        "story_shape": "M62/M60 closures and incidents affecting borough journeys",
    },
]


def key_gated(env_var: str, note: str) -> dict[str, Any]:
    present = bool(os.getenv(env_var))
    return {
        "status": "key-present" if present else "needs-free-key",
        "items": 0,
        "recent_items": 0,
        "per_day": 0.0,
        "note": note if not present else f"{env_var} is set; wire the collector and re-probe",
    }


def main() -> None:
    started = now_utc()
    results: list[dict[str, Any]] = []
    for source in SOURCES:
        try:
            outcome = source["probe"]()
        except Exception as error:  # noqa: BLE001 - one bad source must not end the probe
            outcome = {
                "status": "probe-error",
                "items": 0,
                "recent_items": 0,
                "per_day": 0.0,
                "note": f"{type(error).__name__}: {error}",
            }
        results.append(
            {
                "name": source["name"],
                "class": source["class"],
                "licence": source["licence"],
                "story_shape": source["story_shape"],
                **outcome,
            }
        )

    measured_total = sum(item["per_day"] for item in results)
    payload = {
        "probed_at": started.isoformat().replace("+00:00", "Z"),
        "probe_version": 2,
        "recent_window_days": RECENT_DAYS,
        "sources_probed": len(results),
        "measured_items_per_day": round(measured_total, 2),
        "note": (
            "measured_items_per_day counts only sources this probe could read and date. "
            "Monthly bulk registers report their record count under items and contribute "
            "0.0 to the daily rate rather than being annualised into a flattering number. "
            "Sources marked needs-free-key must be measured again once the key exists."
        ),
        "results": sorted(results, key=lambda item: (item["per_day"], item["items"]), reverse=True),
    }
    REPORT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        lines = [
            "## Candidate source yield (probe v2)",
            "",
            f"Window: last {RECENT_DAYS} days. Measured daily total: "
            f"**{payload['measured_items_per_day']}/day**",
            "",
            "| Source | Class | Status | Robots | Items | Recent | Per day |",
            "| --- | --- | --- | --- | ---: | ---: | ---: |",
        ]
        for item in payload["results"]:
            lines.append(
                f"| {item['name']} | {item['class']} | {item['status']} | "
                f"{item.get('robots', '-')} | {item['items']} | "
                f"{item['recent_items']} | {item['per_day']} |"
            )
        notes = [item for item in payload["results"] if item.get("note")]
        if notes:
            lines += ["", "**Notes**", ""]
            lines += [f"- **{item['name']}**: {item['note']}" for item in notes]
        try:
            with open(summary_path, "a", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")
        except OSError:
            pass


if __name__ == "__main__":
    main()
