#!/usr/bin/env python3
"""Tell Bing and the other IndexNow search engines about new and updated pages as soon as they publish.

Google finds new stories through the news sitemap and its own crawl. Bing, and
everything that searches with Bing's index (DuckDuckGo, Yahoo, Ecosia, ChatGPT
search) or shares IndexNow submissions (Yandex, Seznam, Naver), can instead be
told the moment a page changes. For a news site that is the difference between
a story being findable in minutes and in days.

How it works
------------
The key file /<key>.txt sits at the site root, which proves to the engines
that this site is submitting its own pages. The key is public by design; it is
not a secret.

Each run reads sitemap.xml and news-sitemap.xml and submits every page whose
lastmod (or news publication date) is newer than the previous successful run
of this workflow (SINCE, an ISO time). With no SINCE it uses the last three
hours. With --all it submits every page in the sitemap (a one-off, after the
key is first published). Nothing is submitted until the key file is live.

Read-only on the site: it changes no files.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = "https://rochdaledaily.co.uk"
HOST = "rochdaledaily.co.uk"
ENDPOINT = "https://api.indexnow.org/indexnow"
KEY_RE = re.compile(r"^[0-9a-f]{32}$")
MAX_URLS = 10_000
_URL_RE = re.compile(r"<url>(.*?)</url>", re.S)
_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
_DATE_RE = re.compile(r"<(?:lastmod|news:publication_date)>\s*([^<\s]+)\s*<")


def find_key(root: Path = ROOT) -> str | None:
    for path in sorted(root.glob("*.txt")):
        if KEY_RE.match(path.stem) and path.read_text(encoding="utf-8").strip() == path.stem:
            return path.stem
    return None


def parse_time(value: str) -> datetime | None:
    value = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        value += "T00:00:00+00:00"
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def changed_urls(texts: list[str], since: datetime | None) -> list[str]:
    """Pages (not images) listed in the sitemaps, changed after `since` (all if None), newest first."""
    found: dict[str, datetime] = {}
    for text in texts:
        for block in _URL_RE.findall(text):
            loc = _LOC_RE.search(block)
            if not loc or not loc.group(1).startswith(SITE):
                continue
            url = loc.group(1)
            if re.search(r"\.(?:jpe?g|png|webp|gif|svg)$", url, re.I):
                continue
            stamps = [t for t in (parse_time(d) for d in _DATE_RE.findall(block)) if t]
            moment = max(stamps) if stamps else None
            if since is not None and (moment is None or moment <= since):
                continue
            epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
            found[url] = max(found.get(url, epoch), moment or epoch)
    return sorted(found, key=lambda u: found[u], reverse=True)[:MAX_URLS]


def http(url: str, data: bytes | None = None) -> int:
    headers = {"User-Agent": "RochdaleDaily-IndexNow/1.0"}
    if data is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except Exception:
        return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="submit every page in the sitemap")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    key = find_key()
    if not key:
        print("IndexNow: no key file at the site root; nothing submitted")
        return 1
    since = None
    if not args.all:
        since = parse_time(os.environ.get("SINCE", "")) or datetime.now(timezone.utc) - timedelta(hours=3)
        since -= timedelta(minutes=10)   # overlap, so nothing falls between runs
    texts = [(ROOT / name).read_text(encoding="utf-8") for name in ("sitemap.xml", "news-sitemap.xml")
             if (ROOT / name).is_file()]
    urls = changed_urls(texts, since)
    window = "all pages" if since is None else f"changed since {since.isoformat(timespec='minutes')}"
    if not urls:
        print(f"IndexNow: no pages {window}; nothing submitted")
        return 0
    if args.dry_run:
        print(f"IndexNow dry run: would submit {len(urls)} pages ({window}), e.g. {urls[0]}")
        return 0
    live = http(f"{SITE}/{key}.txt")
    if live != 200:
        print(f"IndexNow: key file not live yet (HTTP {live}); nothing submitted")
        return 0
    payload = json.dumps({"host": HOST, "key": key, "keyLocation": f"{SITE}/{key}.txt", "urlList": urls}).encode()
    status = http(ENDPOINT, payload)
    print(f"IndexNow: submitted {len(urls)} pages ({window}): HTTP {status}")
    # 200 and 202 are accepted; 422/403 mean the key or URLs were refused.
    return 0 if status in (200, 202) else 1


if __name__ == "__main__":
    sys.exit(main())
