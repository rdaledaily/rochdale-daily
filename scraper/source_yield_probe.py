"""Measure what each candidate new source would actually contribute, before any of it is wired in.

The borough currently collects about 24 candidate leads a day across every
existing source. A 60-story daily newspaper cannot be configured out of that
number, so the gap has to be closed with new source classes. This probe is
read-only: it visits each candidate source once, respects robots.txt, counts
how many items it carries and how many are recent, and reports an items-per-day
estimate. Nothing is published, nothing is written to the site, and no source
is added on the strength of a guess -- the collectors are written afterwards,
for the sources whose measured yield justifies them.

Run it from the source-yield-probe workflow (workflow_dispatch) and read the
job summary.
"""
from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "source_yield_report.json"

USER_AGENT = os.getenv(
    "PROBE_USER_AGENT",
    "RochdaleDailyBot/1.0 (+https://rochdaledaily.co.uk/about.html; news@rochdaledaily.co.uk)",
)
TIMEOUT = int(os.getenv("PROBE_TIMEOUT", "20"))
RECENT_DAYS = int(os.getenv("PROBE_RECENT_DAYS", "14"))

_ROBOTS_CACHE: dict[str, urllib.robotparser.RobotFileParser | None] = {}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def robots_allows(url: str) -> bool:
    """Never fetch a page the publisher's robots.txt declines. Unreadable robots.txt is treated as a refusal."""
    parts = urllib.parse.urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    if origin not in _ROBOTS_CACHE:
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(f"{origin}/robots.txt")
        try:
            parser.read()
        except (urllib.error.URLError, socket.timeout, ValueError, OSError):
            _ROBOTS_CACHE[origin] = None
        else:
            _ROBOTS_CACHE[origin] = parser
    parser = _ROBOTS_CACHE[origin]
    if parser is None:
        return False
    try:
        return parser.can_fetch(USER_AGENT, url)
    except Exception:  # noqa: BLE001 - a malformed robots file must not crash the probe
        return False


def fetch(url: str) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
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


def feed_dates(body: str) -> list[datetime | None]:
    try:
        import feedparser  # imported lazily so the probe still runs without it
    except ImportError:
        return []
    parsed = feedparser.parse(body)
    dates: list[datetime | None] = []
    for entry in parsed.entries:
        stamp = entry.get("published") or entry.get("updated") or entry.get("created")
        value = parse_dt(stamp)
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
            if item.get(key):
                stamp = item.get(key)
                break
        dates.append(parse_dt(stamp))
    return dates


Probe = Callable[[], dict[str, Any]]


def http_probe(
    url: str,
    *,
    kind: str,
    list_path: list[str] | None = None,
    date_keys: list[str] | None = None,
) -> dict[str, Any]:
    if not robots_allows(url):
        return {"status": "robots-denied", "items": 0, "recent_items": 0, "per_day": 0.0}
    code, body = fetch(url)
    if code != 200 or not body:
        return {"status": f"http-{code}", "items": 0, "recent_items": 0, "per_day": 0.0}
    if kind == "feed":
        dates = feed_dates(body)
    elif kind == "json":
        dates = json_dates(body, list_path=list_path or [], date_keys=date_keys or [])
    else:  # reachability only -- volume must be counted by the collector itself
        return {
            "status": "reachable",
            "items": 0,
            "recent_items": 0,
            "per_day": 0.0,
            "bytes": len(body),
        }
    reference = now_utc()
    recent = count_recent(dates, days=RECENT_DAYS, reference=reference)
    return {
        "status": "ok" if dates else "empty",
        "items": len(dates),
        "recent_items": recent,
        "per_day": per_day(recent, RECENT_DAYS),
    }


def key_gated(name: str, env_var: str, note: str) -> dict[str, Any]:
    present = bool(os.getenv(env_var))
    return {
        "status": "key-present" if present else "needs-free-key",
        "items": 0,
        "recent_items": 0,
        "per_day": 0.0,
        "note": note if not present else f"{env_var} is set; wire the collector and re-probe",
    }


# Every source below is free to use and covered by an open licence or the
# publisher's own feed. Nothing here scrapes a platform that forbids it.
SOURCES: list[dict[str, Any]] = [
    {
        "name": "Police street-level crime (data.police.uk)",
        "class": "primary record",
        "licence": "Open Government Licence",
        "probe": lambda: http_probe(
            "https://data.police.uk/api/crimes-street/all-crime?lat=53.6136&lng=-2.1610&date="
            + (now_utc() - timedelta(days=60)).strftime("%Y-%m"),
            kind="json",
            list_path=[],
            date_keys=["month"],
        ),
        "story_shape": "ward crime counts, month-on-month movement, hotspot streets",
    },
    {
        "name": "The Gazette official public record",
        "class": "primary record",
        "licence": "Open Government Licence",
        "probe": lambda: http_probe(
            "https://www.thegazette.co.uk/all-notices/notice/data.feed?location-postcode=OL16&location-distance-1=10",
            kind="feed",
        ),
        "story_shape": "insolvencies, company strike-offs, statutory and planning notices",
    },
    {
        "name": "UK Parliament petitions (constituency)",
        "class": "civic",
        "licence": "Open Parliament Licence",
        "probe": lambda: http_probe(
            "https://petition.parliament.uk/petitions.json?state=open",
            kind="json",
            list_path=["data"],
            date_keys=["created_at"],
        ),
        "story_shape": "petitions signed locally, with constituency signature counts",
    },
    {
        "name": "UK Parliament written questions and votes",
        "class": "civic",
        "licence": "Open Parliament Licence",
        "probe": lambda: http_probe(
            "https://questions-statements.api.parliament.uk/api/writtenquestions/questions?take=50",
            kind="json",
            list_path=["results"],
            date_keys=["dateTabled"],
        ),
        "story_shape": "what the borough's MPs asked, said and voted for this week",
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
        "name": "Rochdale planning public access",
        "class": "primary record",
        "licence": "council portal (robots-governed)",
        "probe": lambda: http_probe(
            "https://publicaccess.rochdale.gov.uk/online-applications/search.do?action=weeklyList",
            kind="reachability",
        ),
        "story_shape": "applications lodged and decided, weekly, with addresses",
    },
    {
        "name": "Rochdale council democracy (ModernGov)",
        "class": "civic",
        "licence": "council portal (robots-governed)",
        "probe": lambda: http_probe(
            "https://democracy.rochdale.gov.uk/mgListCommittees.aspx?bcr=1",
            kind="reachability",
        ),
        "story_shape": "committee decisions, attendance, voting records by ward",
    },
    {
        "name": "Greater Manchester Fire and Rescue incidents",
        "class": "public safety",
        "licence": "publisher feed",
        "probe": lambda: http_probe(
            "https://www.manchesterfire.gov.uk/news/feed/",
            kind="feed",
        ),
        "story_shape": "incidents and safety appeals in the borough",
    },
    {
        "name": "Northern Care Alliance NHS news",
        "class": "public services",
        "licence": "publisher feed",
        "probe": lambda: http_probe(
            "https://www.northerncarealliance.nhs.uk/feed",
            kind="feed",
        ),
        "story_shape": "Rochdale Infirmary services, waits, recruitment, closures",
    },
    {
        "name": "Reddit r/rochdale",
        "class": "social listening",
        "licence": "public JSON endpoint, rate-limited",
        "probe": lambda: http_probe(
            "https://www.reddit.com/r/rochdale/new.json?limit=100",
            kind="json",
            list_path=["data", "children"],
            date_keys=["created_utc"],
        ),
        "story_shape": "resident-reported incidents and complaints, as leads only",
    },
    {
        "name": "Bluesky local post search",
        "class": "social listening",
        "licence": "public API, app password",
        "probe": lambda: key_gated(
            "Bluesky",
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
            "Companies House",
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
            "Charity Commission",
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
            "National Highways",
            "NATIONAL_HIGHWAYS_API_KEY",
            "free: register at api.data.nationalhighways.co.uk",
        ),
        "story_shape": "M62/M60 closures and incidents affecting borough journeys",
    },
]


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

    measured = sum(item["per_day"] for item in results)
    payload = {
        "probed_at": started.isoformat().replace("+00:00", "Z"),
        "recent_window_days": RECENT_DAYS,
        "sources_probed": len(results),
        "measured_items_per_day": round(measured, 2),
        "note": (
            "measured_items_per_day counts only sources this probe could read and date. "
            "Sources marked needs-free-key or reachability contribute nothing to that number "
            "and must be measured by their own collector once built."
        ),
        "results": sorted(results, key=lambda item: item["per_day"], reverse=True),
    }
    REPORT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        lines = [
            "## Candidate source yield",
            "",
            f"Window: last {RECENT_DAYS} days. Measured total: **{payload['measured_items_per_day']}/day**",
            "",
            "| Source | Class | Status | Items | Recent | Per day |",
            "| --- | --- | --- | ---: | ---: | ---: |",
        ]
        for item in payload["results"]:
            lines.append(
                f"| {item['name']} | {item['class']} | {item['status']} | "
                f"{item['items']} | {item['recent_items']} | {item['per_day']} |"
            )
        try:
            with open(summary_path, "a", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")
        except OSError:
            pass


if __name__ == "__main__":
    main()
