#!/usr/bin/env python3
"""robots.txt must be obeyed when served, and not invented when it isn't.

Run: PYTHONPATH=scraper python scraper/test_robots_policy.py

Background, 30 August 2026. The pipeline was recording 19 hosts as "robots
denied", including gmp.police.uk, news.tfgm.com, northernrailway.co.uk,
unitedutilities.com and nationalhighways.co.uk. None of them disallow news
crawling. The cause was in the standard library: RobotFileParser.read() turns a
401 or 403 on /robots.txt into disallow_all = True and does not raise, so the
surrounding try/except never saw it. Sites that answer 403 to datacentre IPs --
which is most CDN-fronted public-sector sites, seen from a GitHub Actions
runner -- were being treated as having banned us outright.

The rule these tests pin: a refusal is only a refusal when robots.txt was
actually served with a 200. Anything else states no policy.
"""

from __future__ import annotations

import sys
import urllib.robotparser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

FAILURES: list[str] = []


def check(condition: bool, label: str) -> None:
    if condition:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}")
        FAILURES.append(label)


def section(title: str) -> None:
    print(f"\n{title}")


class FakeResponse:
    def __init__(self, status: int, text: str = "") -> None:
        self.status_code = status
        self.text = text


class FakeSession:
    """Stands in for requests.Session, serving one canned robots.txt."""

    def __init__(self, status: int, text: str = "", raise_error: bool = False) -> None:
        self.status = status
        self.text = text
        self.raise_error = raise_error
        self.headers = {"User-Agent": "RochdaleDaily/3.2 (+https://rochdaledaily.co.uk)"}
        self.requested: list[str] = []

    def get(self, url: str, **kwargs):
        self.requested.append(url)
        if self.raise_error:
            raise ConnectionError("connection reset")
        return FakeResponse(self.status, self.text)


# GMP's real robots.txt, fetched 30 August 2026.
GMP_ROBOTS = "\r\n".join([
    "user-agent: *",
    "Disallow: /*/mediacentre",
    "Disallow: /*/?u=media",
    "Disallow: /*/GetPdf/?",
    "Disallow: /*/GetPaginatedResults/?",
    "Disallow: /*.aspx$",
    "Disallow: /500.html",
    "Disallow: /api/*",
    "Sitemap: /sitemap.xml",
])

UA = "RochdaleDaily/3.2 (+https://rochdaledaily.co.uk)"

# --------------------------------------------------------------------------
section("The standard library's behaviour, pinned so the bug cannot return")
# --------------------------------------------------------------------------

crippled = urllib.robotparser.RobotFileParser()
crippled.disallow_all = True  # precisely what read() sets on a 401/403
check(
    not crippled.can_fetch(UA, "https://www.gmp.police.uk/news/news-search/?ct=News"),
    "a 403 on robots.txt makes RobotFileParser refuse every URL",
)
check(
    not crippled.can_fetch(UA, "https://www.gmp.police.uk/anything/at/all"),
    "...including URLs no real robots.txt mentions",
)

# --------------------------------------------------------------------------
section("A served robots.txt is obeyed")
# --------------------------------------------------------------------------

served = urllib.robotparser.RobotFileParser()
served.parse(GMP_ROBOTS.splitlines())

ALLOWED = [
    "https://www.gmp.police.uk/",
    "https://www.gmp.police.uk/news/news-search/?ct=News",
    "https://www.gmp.police.uk/news/news-search/?ct=Appeals",
    "https://www.gmp.police.uk/news/news-search/?ct=News&fdte=&page=1&tdte=",
    "https://www.gmp.police.uk/news/greater-manchester/news/news/2026/august/a-story/",
]
for url in ALLOWED:
    check(served.can_fetch(UA, url), f"allowed by GMP's real policy: {url[-52:]}")

# Python's own parser matches rule paths by plain PREFIX -- it has no wildcard
# support -- so every wildcard rule in a real robots.txt is silently ignored by
# it. Pinned here because it is the reason the watcher compiles its own.
WILDCARD_RULES = [
    "https://www.gmp.police.uk/api/something",
    "https://www.gmp.police.uk/news/mediacentre",
    "https://www.gmp.police.uk/page.aspx",
]
for url in WILDCARD_RULES:
    check(
        served.can_fetch(UA, url),
        f"stdlib ignores the wildcard rule covering: {url[-46:]}",
    )

# --------------------------------------------------------------------------
section("The watcher: a refusal needs a 200")
# --------------------------------------------------------------------------

import gmp_watch as gw

NEWS = "https://www.gmp.police.uk/news/news-search/?ct=News"

f = gw.Fetcher(session=FakeSession(200, GMP_ROBOTS))
check(f.robots_allows(NEWS), "200 + permissive rules -> allowed")
check(
    f.robots_allows("https://www.gmp.police.uk/news/greater-manchester/news/a-story/"),
    "200 -> an ordinary article page is allowed",
)

# The watcher compiles the wildcard rules the stdlib drops, so these DO block.
for url, label in [
    ("https://www.gmp.police.uk/api/something", "Disallow: /api/*"),
    ("https://www.gmp.police.uk/news/mediacentre", "Disallow: /*/mediacentre"),
    ("https://www.gmp.police.uk/page.aspx", "Disallow: /*.aspx$"),
    ("https://www.gmp.police.uk/news/GetPaginatedResults/?x=1", "Disallow: /*/GetPaginatedResults/?"),
]:
    check(not f.robots_allows(url), f"watcher honours {label}")

# ...and does not over-block: .aspx$ is anchored, so this is fine.
check(
    f.robots_allows("https://www.gmp.police.uk/news/page.aspx.html"),
    "an anchored $ rule does not over-block",
)

check(
    gw.wildcard_disallows("user-agent: googlebot\r\nDisallow: /*\r\n") == (),
    "rules for another named agent are ignored",
)

for status in (401, 403, 404, 500, 503):
    f = gw.Fetcher(session=FakeSession(status))
    check(
        f.robots_allows(NEWS),
        f"robots.txt returned {status} -> states no policy, proceed",
    )

f = gw.Fetcher(session=FakeSession(0, raise_error=True))
check(f.robots_allows(NEWS), "robots.txt unreachable -> proceed")

blanket = "user-agent: *\r\nDisallow: /\r\n"
f = gw.Fetcher(session=FakeSession(200, blanket))
check(
    not f.robots_allows(NEWS),
    "a served blanket Disallow: / IS honoured -- this is the case that must still block",
)

# robots.txt is fetched once per host, not per URL.
session = FakeSession(200, GMP_ROBOTS)
f = gw.Fetcher(session=session)
for _ in range(5):
    f.robots_allows(NEWS)
check(
    len([u for u in session.requested if u.endswith("/robots.txt")]) == 1,
    "robots.txt is fetched once per host and cached",
)

# The opt-out still works.
import os

os.environ["RESPECT_ROBOTS"] = "false"
f = gw.Fetcher(session=FakeSession(200, blanket))
check(f.robots_allows(NEWS), "RESPECT_ROBOTS=false bypasses the check entirely")
os.environ["RESPECT_ROBOTS"] = "true"

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED:")
    for name in FAILURES:
        print(f"  - {name}")
    raise SystemExit(1)
print("all robots policy tests passed")
