#!/usr/bin/env python3
"""
Rochdale Daily - weather forecast feed.

Fetches the Met Office DataHub site-specific daily forecast and writes
weather.json for the homepage forecast panel to render.

WHY BUILD TIME, NOT A PAGES FUNCTION
------------------------------------
The traffic panel runs as a Function because road closures go stale in
minutes. A daily forecast does not: the model refreshes a handful of times
a day, so a request-time call buys no freshness at all.

It also cannot safely run at request time on the free plan. Cloudflare's
edge cache is per data centre, so a 60-second cacheTtl like traffic.js uses
allows up to 1,440 upstream calls per colo per day against a Met Office cap
of 360. Running here instead pins usage to the workflow schedule: at one run
an hour that is 24 calls a day, and the reader can never trigger a 429.

The key stays in GitHub Actions. It is never sent to Cloudflare, never
embedded in the page, and never placed in a URL or a log line.

NO FALLBACKS
------------
If a day is missing its daytime fields, it is dropped and reported. The
script does not substitute night values, interpolate, or reach for a second
provider to pad the panel out to a round number of days. A short forecast is
accurate; a padded one is not.

Usage:
    python scraper/weather_forecast.py
    python scraper/weather_forecast.py --dry-run    # print, write nothing
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = REPO_ROOT / "weather.json"

ENDPOINT = "https://data.hub.api.metoffice.gov.uk/sitespecific/v0/point/daily"

# Matches the masthead widget's coordinates so the panel and the widget can
# never disagree about which Rochdale they are describing.
LATITUDE = 53.6177
LONGITUDE = -2.1552

UK = ZoneInfo("Europe/London")

REQUEST_TIMEOUT = 20

# Nothing beyond a week is worth showing even if the API returns it.
MAX_DAYS = 7

# Met Office significant weather codes. Odd/even pairs are night/day variants
# of one condition; this panel only ever reads the daytime code, so the pairs
# collapse to the same wording.
WEATHER_CODES = {
    -1: "Not available",
    0: "Clear",
    1: "Sunny",
    2: "Partly cloudy",
    3: "Partly cloudy",
    5: "Mist",
    6: "Fog",
    7: "Cloudy",
    8: "Overcast",
    9: "Light rain shower",
    10: "Light rain shower",
    11: "Drizzle",
    12: "Light rain",
    13: "Heavy rain shower",
    14: "Heavy rain shower",
    15: "Heavy rain",
    16: "Sleet shower",
    17: "Sleet shower",
    18: "Sleet",
    19: "Hail shower",
    20: "Hail shower",
    21: "Hail",
    22: "Light snow shower",
    23: "Light snow shower",
    24: "Light snow",
    25: "Heavy snow shower",
    26: "Heavy snow shower",
    27: "Heavy snow",
    28: "Thunder shower",
    29: "Thunder shower",
    30: "Thunder",
}

# Symbols already used by the masthead widget, reused so the panel and the
# widget speak the same visual language.
WEATHER_ICONS = {
    "Clear": "☀",
    "Sunny": "☀",
    "Partly cloudy": "◐",
    "Mist": "≋",
    "Fog": "≋",
    "Cloudy": "☁",
    "Overcast": "☁",
    "Drizzle": "☂",
    "Light rain": "☂",
    "Light rain shower": "☂",
    "Heavy rain": "☂",
    "Heavy rain shower": "☂",
    "Sleet": "❄",
    "Sleet shower": "❄",
    "Hail": "❄",
    "Hail shower": "❄",
    "Light snow": "❄",
    "Light snow shower": "❄",
    "Heavy snow": "❄",
    "Heavy snow shower": "❄",
    "Thunder": "ϟ",
    "Thunder shower": "ϟ",
}


def fetch_payload(key: str) -> dict:
    """Call the API. The key goes in a header, never in the query string."""
    response = requests.get(
        ENDPOINT,
        params={"latitude": LATITUDE, "longitude": LONGITUDE},
        headers={"apikey": key, "accept": "application/json"},
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code == 429:
        raise RuntimeError(
            "HTTP 429 - the daily call limit is spent. The free site-specific "
            "plan allows 360 calls a day, resetting at 00:00 UTC. Check "
            "nothing else is calling this key."
        )
    response.raise_for_status()
    return response.json()


def extract_time_series(payload: dict) -> tuple[list[dict], str]:
    """Pull the timeSeries and model run date out of the GeoJSON envelope."""
    features = payload.get("features")
    if not isinstance(features, list) or not features:
        raise RuntimeError("Payload has no features array.")

    properties = features[0].get("properties") or {}
    series = properties.get("timeSeries")
    if not isinstance(series, list) or not series:
        raise RuntimeError("Payload has no timeSeries entries.")

    return series, str(properties.get("modelRunDate") or "")


def parse_entry(entry: dict) -> tuple[date | None, bool, dict | None]:
    """
    Turn one timeSeries entry into a panel day.

    Returns (entry date, whether it is complete, the day record or None).
    An entry is complete only if it carries both a daytime weather code and a
    daytime maximum temperature. The first entry of a response is routinely
    night-only because the model run straddles midnight, and the last can be
    truncated the same way.
    """
    raw_time = entry.get("time") or ""
    try:
        entry_date = datetime.strptime(raw_time[:10], "%Y-%m-%d").date()
    except ValueError:
        return None, False, None

    code = entry.get("daySignificantWeatherCode")
    temperature = entry.get("dayMaxScreenTemperature")

    if code is None or temperature is None:
        return entry_date, False, None

    condition = WEATHER_CODES.get(int(code), "Not available")

    return entry_date, True, {
        "date": entry_date.isoformat(),
        "weekday": entry_date.strftime("%a"),
        "temperature_c": round(float(temperature)),
        "condition": condition,
        "icon": WEATHER_ICONS.get(condition, "◌"),
    }


def build_feed(payload: dict) -> tuple[dict, list[str]]:
    """Build the weather.json structure and a human-readable coverage report."""
    series, model_run = extract_time_series(payload)
    today = datetime.now(UK).date()

    report: list[str] = [f"timeSeries entries returned: {len(series)}"]
    days: list[dict] = []
    skipped_past = 0

    for entry in series:
        entry_date, complete, record = parse_entry(entry)

        if entry_date is None:
            report.append("  (unparseable time value - skipped)")
            continue

        if entry_date < today:
            skipped_past += 1
            continue

        if not complete:
            report.append(
                f"  {entry_date}  INCOMPLETE - no daytime fields, dropped"
            )
            continue

        days.append(record)
        report.append(
            f"  {entry_date}  {record['temperature_c']:>3}C  {record['condition']}"
        )

    if skipped_past:
        report.insert(1, f"entries dated before today, skipped: {skipped_past}")

    days = days[:MAX_DAYS]

    if not days:
        raise RuntimeError(
            "No usable forecast days. Every entry was either in the past or "
            "missing its daytime fields."
        )

    feed = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model_run": model_run,
        "source": "Met Office",
        "location": "Rochdale",
        "days": days,
    }

    report.append(f"usable forecast days: {len(days)}")
    return feed, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch the Rochdale forecast.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the feed and coverage report without writing weather.json.",
    )
    args = parser.parse_args()

    key = os.environ.get("METOFFICE_API_KEY", "").strip()
    if not key:
        print(
            "WEATHER FAILED: METOFFICE_API_KEY is not set. weather.json left "
            "untouched.",
            file=sys.stderr,
        )
        return 0

    try:
        payload = fetch_payload(key)
        feed, report = build_feed(payload)
    except Exception as exc:
        # Never fail the run. A weather blip must not stop the news pipeline
        # from publishing, and the existing weather.json stays in place with
        # its own generated_at so the page can judge its age.
        print(f"WEATHER FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("weather.json left untouched.", file=sys.stderr)
        return 0

    print(f"Model run: {feed['model_run']}")
    for line in report:
        print(line)

    if args.dry_run:
        print("\n--- weather.json (not written) ---")
        print(json.dumps(feed, indent=2))
        return 0

    OUTPUT_PATH.write_text(json.dumps(feed, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {OUTPUT_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
