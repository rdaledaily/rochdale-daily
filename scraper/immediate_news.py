"""What counts as immediate news, and where the monitor looks for it.

Editor, 17 Nov 2026: "A monitor on Rochdale Times and Roch Valley Radio as
well as Manchester Evening News concerning immediate news."

Measured the same morning, before this existed:
  * Rochdale Times "Dozens of properties left without power" went out at
    07:27 GMT. The pipeline first saw it at 08:36 (69 minutes later) and the
    story reached the site at 09:44 -- 2 h 17 min end to end.
  * Rochdale Times "Campaigners hit out at 'absurd' College Bank demolition
    decision" (08:54) was still not a candidate at 10:06.
  * Roch Valley Radio "Decision on future of the Seven Sisters" (15:09 on
    16 Nov) reached the site at 17:40.
The fast lane commits every 15-30 minutes, so cadence was not the cause:
the Rochdale Times was only read by HTML homepage discovery, never by its own
RSS feed, and nothing pushed an urgent story ahead of the rest.

One classifier is shared by the monitor (scraper/immediate_watch.py) and the
scrape lanes (scraper.py), so a story the monitor flags is the story the lane
writes first.
"""
from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import quote_plus

from affects_today import today_kind

# The MEN answers GitHub Actions with a bot challenge (HTTP 403 on its own
# RSS, measured in every run's scraper_status.json) and the editor decided on
# 4 Nov 2026 not to route around it. Google News indexes MEN articles within
# minutes and is reachable from Actions, so the MEN is read through that.
MEN_BOROUGH_QUERY = (
    "site:manchestereveningnews.co.uk (Rochdale OR Heywood OR Middleton OR "
    "Littleborough OR Milnrow OR Norden OR Wardle OR Castleton OR Smallbridge) when:1d"
)
MEN_BOROUGH_FEED = (
    "https://news.google.com/rss/search?q=" + quote_plus(MEN_BOROUGH_QUERY)
    + "&hl=en-GB&gl=GB&ceid=GB:en"
)

MONITORED_SOURCES: list[dict[str, Any]] = [
    {
        "key": "rochdale-times",
        "name": "Rochdale Times",
        "url": "https://www.rochdaletimes.co.uk/feed/",
        "route": "own RSS feed",
        # A Rochdale-only paper: every item is about the borough.
        "borough_only": True,
    },
    {
        "key": "roch-valley-radio",
        "name": "Roch Valley Radio",
        "url": "https://www.rochvalleyradio.com/rss",
        "route": "own RSS feed",
        # Also covers Bury and Oldham, so each item must name the borough.
        "borough_only": False,
    },
    {
        "key": "men",
        "name": "Manchester Evening News",
        "url": MEN_BOROUGH_FEED,
        "route": "Google News (the MEN's own feed refuses GitHub Actions)",
        "borough_only": False,
    },
]

# Something happening now that is not covered by affects_today: live crime and
# emergency incidents. Court, inquest and "named" follow-ups are aftermath and
# are excluded by affects_today's own aftermath test before this runs.
_LIVE_INCIDENT = re.compile(
    r"\b(?:stabb(?:ed|ing)s?|shot (?:dead|in|at|outside|near)|shootings?|gunshots?|firearms? incident|armed police|"
    r"cordons?|cordoned off|police (?:incident|presence|swoop)|major incident|"
    r"serious(?:ly)? (?:injured|assault|incident)|critical condition|life-?threatening|"
    r"murder investigation|man dies|woman dies|boy dies|girl dies|died at the scene|"
    r"blaze|fire crews?|firefighters|house fire|flat fire|mill fire|fire breaks out|"
    r"explosion|police helicopter|air ambulance|emergency services)\b",
    re.I,
)
_AFTERMATH = re.compile(
    r"\b(?:court|jailed|sentenced|convicted|guilty|charged|trial|inquest|jury|pleads?|admits|"
    r"years? ago|anniversary|funeral|named|tributes?|remembered|memorial|appeal for witnesses to)\b",
    re.I,
)

_PUBLISHER_SUFFIX = re.compile(r"\s+[-|–—]\s+(?:Manchester Evening News|Rochdale Times|Roch Valley Radio)\s*$", re.I)


def plain(value: Any) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return " ".join(html.unescape(text).split())


def clean_title(title: Any) -> str:
    """Google News appends ' - Manchester Evening News' to every headline."""
    return _PUBLISHER_SUFFIX.sub("", plain(title)).strip()


def immediate_kind(title: Any) -> str:
    """The kind of immediate news a headline reports, or '' when it is not.

    'missing-person', 'utility-outage', 'school-closure', 'traffic-incident'
    and 'public-warning' come from affects_today (the editor's 17 Nov list);
    'live-incident' adds crime and emergency incidents still unfolding.
    """
    headline = clean_title(title)
    if not headline:
        return ""
    kind = today_kind({"title": headline})
    if kind:
        return kind
    if _AFTERMATH.search(headline):
        return ""
    if _LIVE_INCIDENT.search(headline):
        return "live-incident"
    return ""
