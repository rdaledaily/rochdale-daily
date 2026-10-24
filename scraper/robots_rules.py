"""Wildcard-aware robots.txt checks shared by every fetcher.

Python's urllib.robotparser before 3.13 matches Disallow paths by plain prefix
with no wildcard support, so `Disallow: /api/*` or `Disallow: /*.aspx$` is
ignored. CI and the publishing lanes run Python 3.11, so the main scraper and
the source-yield probe were fetching pages a served robots.txt disallows (only
gmp_watch compiled the wildcard rules itself). This module is that compiler,
used by all three, so the result does not depend on the Python version.
"""
from __future__ import annotations

import re
import urllib.robotparser
from urllib.parse import urlparse


def wildcard_disallows(robots_text: str) -> tuple[re.Pattern[str], ...]:
    """Compile the `user-agent: *` Disallow rules that use * or $."""
    patterns: list[re.Pattern[str]] = []
    in_star_group = False
    for raw in (robots_text or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, _, value = line.partition(":")
        field = field.strip().lower()
        value = value.strip()
        if field == "user-agent":
            in_star_group = value == "*"
            continue
        if not in_star_group or field != "disallow" or not value:
            continue
        if "*" not in value and not value.endswith("$"):
            continue  # a plain prefix rule; RobotFileParser handles it
        anchored = value.endswith("$")
        body = value[:-1] if anchored else value
        expression = "".join(".*" if part == "*" else re.escape(part) for part in re.split(r"(\*)", body))
        try:
            patterns.append(re.compile("^" + expression + ("$" if anchored else "")))
        except re.error:
            continue
    return tuple(patterns)


def parse(robots_text: str) -> urllib.robotparser.RobotFileParser:
    """A RobotFileParser that also carries the compiled wildcard rules."""
    robot = urllib.robotparser.RobotFileParser()
    robot.parse((robots_text or "").splitlines())
    robot._rd_wildcards = wildcard_disallows(robots_text or "")
    return robot


def can_fetch(robot: urllib.robotparser.RobotFileParser, user_agent: str, url: str) -> bool:
    parsed = urlparse(url)
    path = (parsed.path or "/") + (f"?{parsed.query}" if parsed.query else "")
    for pattern in getattr(robot, "_rd_wildcards", ()):
        if pattern.match(path):
            return False
    return robot.can_fetch(user_agent, url)
