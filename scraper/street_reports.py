"""FixMyStreet street-report collector for Rochdale Daily.

Aggregate primary data: how many street-scene problems residents reported to
Rochdale Borough Council this period, broken down by ward and by topic. Read
from mySociety's public per-ward RSS feeds, which FixMyStreet publishes
explicitly for reuse by local sites.

WHY THIS AGGREGATES AND NEVER QUOTES A REPORT
---------------------------------------------
A FixMyStreet report is a free-text allegation written by a resident. The live
Rochdale feed contains titles such as "Residents flytipping again !!!!!" and
titles that are bare house numbers and street names. Republishing any of that
verbatim would be an unverified allegation about an identifiable household at
an identifiable address - a Defamation Act 2013 and IPSO clause 2 problem, and
the same class of risk claim_guard.py exists to block.

So this module deliberately:
  * emits COUNTS ONLY - ward totals and topic totals;
  * never carries a report title, description, house number, postcode,
    reporter name or per-report link into a Candidate or into prose;
  * links only to the public ward summary page, never to a single report;
  * states in every article that these are unverified resident reports, not
    council findings, and that a report is not proof a problem exists.

The topic grouping is derived here by keyword from the resident's own wording,
NOT taken from the council's own categorisation, and the prose says so. That
distinction matters: "reports describing fly-tipping" is defensible,
"fly-tipping reports recorded by the council" would not be.

No third-party dependencies. Network access is injected as a callable so the
tests never touch the internet. Mirrors food_hygiene.py throughout.
"""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable
from urllib.parse import quote_plus

RSS_BASE = "https://www.fixmystreet.com/rss/reports/Rochdale"
WARD_PAGE_BASE = "https://www.fixmystreet.com/reports/Rochdale"
COUNCIL_PAGE = WARD_PAGE_BASE
FEED_HEADERS = {
    "accept": "application/rss+xml, application/xml",
    # Identifying the publisher is the courteous thing to do against a
    # charity's free feed, and makes the traffic auditable from their side.
    "user-agent": "RochdaleDaily/1.0 (+https://rochdaledaily.co.uk)",
}

# Same fail-fast posture as the FSA collector: 20 ward feeds must never be able
# to stall a pipeline run whose whole budget is about 20 minutes.
PER_REQUEST_TIMEOUT = 8
OVERALL_DEADLINE_SECONDS = 60


class _FetchDeadlineReached(Exception):
    """Raised internally when the overall FixMyStreet fetch budget is spent."""


# The 20 wards of Rochdale Borough Council as FixMyStreet slugs them, mapped to
# the area vocabulary in scraper.AREA_KEYWORDS. Verified against the live
# council page rather than assumed - FixMyStreet writes "and" rather than "&"
# in ward paths, and the Wardle ward carries a comma.
#
# Middleton's four wards all map to 'middleton' rather than to sub-areas such
# as alkrington: a ward is not a neighbourhood, and claiming a count belongs to
# Alkrington when it belongs to East Middleton would be wrong at exactly the
# level of precision a reader would trust.
WARDS: dict[str, tuple[str, str]] = {
    "Balderstone and Kirkholt": ("Balderstone & Kirkholt", "balderstone"),
    "Bamford": ("Bamford", "bamford"),
    "Castleton": ("Castleton", "castleton"),
    "Central Rochdale": ("Central Rochdale", "rochdale"),
    "East Middleton": ("East Middleton", "middleton"),
    "Healey": ("Healey", "healey"),
    "Hopwood Hall": ("Hopwood Hall", "hopwood"),
    "Kingsway": ("Kingsway", "rochdale"),
    "Littleborough Lakeside": ("Littleborough Lakeside", "littleborough"),
    "Milkstone and Deeplish": ("Milkstone & Deeplish", "deeplish"),
    "Milnrow and Newhey": ("Milnrow & Newhey", "milnrow"),
    "Norden": ("Norden", "norden"),
    "North Heywood": ("North Heywood", "heywood"),
    "North Middleton": ("North Middleton", "middleton"),
    "Smallbridge and Firgrove": ("Smallbridge & Firgrove", "smallbridge"),
    "South Middleton": ("South Middleton", "middleton"),
    "Spotland and Falinge": ("Spotland & Falinge", "spotland"),
    "Wardle, Shore and West Littleborough": (
        "Wardle, Shore & West Littleborough", "wardle"),
    "West Heywood": ("West Heywood", "heywood"),
    "West Middleton": ("West Middleton", "middleton"),
}

# Topic groups, in the order they are tested. First match wins, so the more
# specific patterns come first. Each group maps onto a council service the
# paper otherwise has no coverage of at all.
#
# Every phrase here is matched against the resident's own wording. Anything
# unmatched is counted in the total but never attributed to a topic - silently
# guessing would inflate a number the article then states as fact.
TOPIC_RULES: list[tuple[str, str, tuple[str, ...]]] = [
    ("needles", "discarded needles or syringes",
     ("needle", "syringe", "drug litter", "drug paraphernalia")),
    ("dog_fouling", "dog fouling",
     ("dog foul", "dog mess", "dog poo", "dog dirt", "dog waste")),
    ("dead_animals", "dead animals",
     ("dead animal", "dead cat", "dead dog", "dead fox", "dead bird",
      "carcass")),
    ("graffiti", "graffiti", ("graffiti", "tagging", "flyposting",
                              "fly posting", "fly-posting")),
    ("flytipping", "fly-tipping and dumped waste",
     ("fly tip", "flytip", "fly-tip", "dumped", "dumping", "dumper",
      "tipped", "mattress", "sofa dumped", "rubbish dumped")),
    ("vegetation", "overgrown vegetation, weeds and grass",
     ("overgrown", "weed", "bramble", "nettle", "hedge", "shrub", "bush",
      "grass", "knotweed", "verge")),
    ("lighting", "street lighting",
     ("street light", "streetlight", "lamp post", "lamppost", "lighting column",
      "light out")),
    ("trees", "trees",
     ("tree", "branch", "overhanging", "fallen tree")),
    ("rights_of_way", "blocked footpaths and rights of way",
     ("right of way", "row blocked", "blocked footpath", "footpath blocked",
      "public footpath", "bridleway", "blocked path", "locked gate")),
    ("litter", "litter, bins and street cleaning",
     ("litter", "bin full", "overflowing", "abandoned bin", "wheelie bin",
      "bin bags", "rubbish", "street clean")),
    ("parking", "obstructive and pavement parking",
     ("parking", "parked", "pavement park", "school run", "double park",
      "abandoned vehicle", "abandoned car", "untaxed", "uninsured")),
    ("highways", "road surfaces, potholes and drainage",
     ("pothole", "pot hole", "road surface", "carriageway", "drain",
      "gully", "manhole", "grid", "puddle", "flooded road")),
]

TOPIC_LABELS = {key: label for key, label, _ in TOPIC_RULES}

# Phrases are matched on a leading word boundary, NOT as bare substrings.
# Substring matching filed "Street light out making area at night very dark and
# unsafe" under trees, because "tree" sits inside "street". There is no trailing
# boundary, so a phrase still matches its plural and its compounds: "tree"
# matches "trees", "weed" matches "weeds", "bush" matches "bushes".
_TOPIC_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (key, re.compile("|".join(r"\b" + re.escape(p) for p in phrases)))
    for key, _label, phrases in TOPIC_RULES
]


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _ward_feed_url(ward_slug: str) -> str:
    return f"{RSS_BASE}/{quote_plus(ward_slug)}"


def ward_page_url(ward_slug: str) -> str:
    """The public ward summary page - the only FixMyStreet link ever published.

    Individual report URLs are deliberately never emitted: a link to
    /report/<id> is a link to an identifiable address and an unverified
    allegation about whoever lives there.
    """
    return f"{WARD_PAGE_BASE}/{quote_plus(ward_slug)}"


def classify_topic(text: str) -> str | None:
    """Group one report by the resident's own wording. None when unmatched.

    Returning None rather than a catch-all is deliberate. An unmatched report
    still counts towards the ward total, but is never attributed to a service
    topic the article then reports a number for.
    """
    haystack = _clean(text).lower()
    if not haystack:
        return None
    for key, pattern in _TOPIC_PATTERNS:
        if pattern.search(haystack):
            return key
    return None


def _parse_pubdate(raw: str) -> datetime | None:
    raw = _clean(raw)
    if not raw:
        return None
    try:
        value = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        try:
            value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_feed(xml_text: str) -> list[dict[str, Any]]:
    """Return {'text', 'published_at'} per RSS item.

    Only the wording and the timestamp are lifted out. The link, guid,
    description HTML and any georss point are read past and discarded so that
    no per-report identifier can reach a Candidate by accident later.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    items: list[dict[str, Any]] = []
    for item in root.iter("item"):
        title = _clean(item.findtext("title"))
        if not title:
            continue
        published = _parse_pubdate(item.findtext("pubDate") or "")
        items.append({"text": title, "published_at": published})
    return items


def fetch_ward_counts(
    get: Callable[..., Any],
    *,
    days: int = 7,
    now: datetime | None = None,
    overall_timeout: float | None = OVERALL_DEADLINE_SECONDS,
) -> dict[str, Any]:
    """Counts of reports raised in the window, by ward and by topic.

    Returns:
        {
          'window_days': int,
          'as_at': datetime,
          'total': int,
          'wards': {ward_slug: {'label','area','count',
                                'topics': Counter}},
          'topics': Counter,
          'wards_unavailable': [ward_slug, ...],
        }

    A ward whose feed fails is recorded in wards_unavailable and excluded from
    every total. It is NOT counted as zero: a network failure and a quiet week
    are different facts, and publishing the first as the second would put a
    wrong number in an article. The caller refuses to publish when any ward is
    missing - see collect_street_report_candidates in scraper.py.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    deadline = (time.monotonic() + overall_timeout) if overall_timeout else None

    wards: dict[str, Any] = {}
    unavailable: list[str] = []
    topic_totals: Counter = Counter()
    total = 0

    for ward_slug, (label, area) in WARDS.items():
        if deadline is not None and time.monotonic() >= deadline:
            unavailable.append(ward_slug)
            continue
        try:
            response = get(
                _ward_feed_url(ward_slug),
                headers=FEED_HEADERS,
                timeout=PER_REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            items = parse_feed(response.text)
        except Exception:
            unavailable.append(ward_slug)
            continue

        ward_topics: Counter = Counter()
        ward_count = 0
        for entry in items:
            published = entry["published_at"]
            # An item with no parseable date cannot be placed in the window, so
            # it is skipped rather than assumed recent.
            if published is None or published < cutoff or published > now:
                continue
            ward_count += 1
            topic = classify_topic(entry["text"])
            if topic:
                ward_topics[topic] += 1
                topic_totals[topic] += 1

        wards[ward_slug] = {
            "label": label,
            "area": area,
            "count": ward_count,
            "topics": ward_topics,
        }
        total += ward_count

    return {
        "window_days": days,
        "as_at": now,
        "total": total,
        "wards": wards,
        "topics": topic_totals,
        "wards_unavailable": unavailable,
    }


# The standing legal and provenance note. Every article built here carries it
# verbatim. It is the whole reason this collector is publishable.
LEGAL_NOTE = (
    "These figures count reports submitted by members of the public to "
    "Rochdale Borough Council through the independent website FixMyStreet. "
    "They are reports, not findings: a report records that someone said there "
    "was a problem, not that the council has inspected, confirmed or upheld "
    "it. Some reports are duplicates of the same problem, some are later found "
    "to be the responsibility of another body, and some are resolved within "
    "days. Rochdale Daily does not name the locations or the people involved "
    "in individual reports, and no allegation about any identifiable person, "
    "household or business should be inferred from these totals."
)

RIGHT_TO_REPLY = (
    "If you believe a figure here is wrong, or you are affected by how a "
    "report has been handled, email news@rochdaledaily.co.uk and we will "
    "publish a correction or a reply."
)

_NUMBER_WORDS = {
    1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six",
    7: "Seven", 8: "Eight", 9: "Nine", 10: "Ten",
}

# Below this, the borough-wide total is noise rather than a story and no
# article is offered at all.
MIN_TOTAL_TO_PUBLISH = 12
# Wards quieter than this are summarised as a group rather than listed, so the
# article does not read as a list of ones and twos.
MIN_WARD_TO_LIST = 2


def roundup_paragraphs(
    counts: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """A complete deterministic roundup, ready to publish without a rewrite.

    Every sentence restates a count this module computed from a public feed.
    Nothing is inferred, no cause is suggested, no trend is claimed - a single
    window cannot support a trend and asserting one would be the easiest way
    to make this article wrong.
    """
    now = now or counts.get("as_at") or datetime.now(timezone.utc)
    as_at = now.strftime("%-d %B %Y")
    days = int(counts.get("window_days", 7))
    total = int(counts.get("total", 0))
    wards = counts.get("wards", {})
    topics: Counter = counts.get("topics", Counter())

    period = "week" if days == 7 else f"{days} days"

    title = (
        f"{total} street problems reported to the council across the borough "
        f"in the past {period}"
    )
    summary = (
        f"Residents submitted {total} reports about street and neighbourhood "
        f"problems to Rochdale Borough Council through FixMyStreet in the "
        f"{days} days to {as_at}. They are unverified reports, not confirmed "
        f"council findings."
    )

    paragraphs: list[str] = [
        f"Residents across the Rochdale borough submitted {total} reports "
        f"about street and neighbourhood problems to the council in the "
        f"{days} days to {as_at}, according to reports published on the "
        f"independent site FixMyStreet."
    ]

    ranked_topics = [
        (TOPIC_LABELS[key], value)
        for key, value in topics.most_common()
        if value
    ]
    if ranked_topics:
        listed = "; ".join(
            f"{label}, {value} report{'s' if value != 1 else ''}"
            for label, value in ranked_topics
        )
        paragraphs.append(
            "Grouped by what residents described in their own words, the "
            f"reports covered: {listed}."
        )
        paragraphs.append(
            "That grouping is made by Rochdale Daily from the wording of each "
            "report, not from the council's own categories, so a report may "
            "describe more than one problem and some reports fall into no "
            "group at all."
        )

    ward_rows = sorted(
        ((data["label"], data["count"]) for data in wards.values()),
        key=lambda row: (-row[1], row[0]),
    )
    listed_wards = [row for row in ward_rows if row[1] >= MIN_WARD_TO_LIST]
    if listed_wards:
        ward_text = "; ".join(
            f"{label}, {value}" for label, value in listed_wards
        )
        paragraphs.append(f"By ward, the report counts were: {ward_text}.")
    quiet = [label for label, value in ward_rows if value < MIN_WARD_TO_LIST]
    if quiet:
        paragraphs.append(
            f"{len(quiet)} further ward{'s' if len(quiet) != 1 else ''} "
            f"recorded fewer than {MIN_WARD_TO_LIST} reports in the period: "
            + ", ".join(sorted(quiet)) + "."
        )

    paragraphs.append(
        "Ward totals reflect where a problem was reported, not where the "
        "person reporting it lives, and a ward with more reports is not "
        "necessarily a ward with more problems - it may simply be one where "
        "more people use the service."
    )
    paragraphs.append(
        "Anyone can report a street problem to the council at "
        "fixmystreet.com or through the council's own website. Reports about "
        "an immediate danger to people or traffic should go to the council "
        "directly rather than through a website."
    )
    paragraphs.append(LEGAL_NOTE)

    return {
        "title": title,
        "summary": summary,
        "paragraphs": paragraphs,
        "legal_disclaimer": LEGAL_NOTE,
        "right_to_reply": RIGHT_TO_REPLY,
    }


def ward_paragraphs(
    counts: dict[str, Any],
    ward_slug: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """A single-ward roundup, or None when the ward is too quiet to carry one.

    Used to give the outlying towns their own coverage rather than only ever
    appearing as a line in a borough table.
    """
    data = (counts.get("wards") or {}).get(ward_slug)
    if not data or data["count"] < MIN_TOTAL_TO_PUBLISH:
        return None

    now = now or counts.get("as_at") or datetime.now(timezone.utc)
    as_at = now.strftime("%-d %B %Y")
    days = int(counts.get("window_days", 7))
    label = data["label"]
    count = data["count"]

    ranked = [
        (TOPIC_LABELS[key], value)
        for key, value in data["topics"].most_common()
        if value
    ]

    title = f"{count} street problems reported in {label} in the past week"
    summary = (
        f"Residents submitted {count} reports about street and neighbourhood "
        f"problems in the {label} ward to Rochdale Borough Council in the "
        f"{days} days to {as_at}."
    )
    paragraphs = [
        f"Residents in the {label} ward submitted {count} reports about "
        f"street and neighbourhood problems to Rochdale Borough Council in "
        f"the {days} days to {as_at}, according to reports published on the "
        f"independent site FixMyStreet."
    ]
    if ranked:
        paragraphs.append(
            "Grouped by what residents described, the reports covered: "
            + "; ".join(
                f"{tlabel}, {value} report{'s' if value != 1 else ''}"
                for tlabel, value in ranked
            )
            + ". That grouping is made from the wording of each report rather "
            "than the council's own categories."
        )
    paragraphs.append(
        f"Open reports for the ward can be viewed at {ward_page_url(ward_slug)}."
    )
    paragraphs.append(LEGAL_NOTE)

    return {
        "title": title,
        "summary": summary,
        "paragraphs": paragraphs,
        "legal_disclaimer": LEGAL_NOTE,
        "right_to_reply": RIGHT_TO_REPLY,
        "area": data["area"],
    }


if __name__ == "__main__":  # pragma: no cover
    # Measure before wiring anything in. Run this once, on its own, and read
    # the real numbers before deciding the window length, MIN_TOTAL_TO_PUBLISH
    # or whether the per-ward article is worth having at all.
    #
    #     python scraper/street_reports.py
    #
    import json
    import sys

    try:
        import requests
    except ImportError:
        sys.exit("requests not installed; run inside the pipeline environment")

    session = requests.Session()
    for window in (7, 14, 28):
        result = fetch_ward_counts(session.get, days=window)
        print(f"\n=== window: {window} days ===")
        print("total:", result["total"])
        if result["wards_unavailable"]:
            print("UNAVAILABLE WARDS:", result["wards_unavailable"])
        print("topics:", json.dumps(dict(result["topics"]), indent=2))
        print("wards:", json.dumps(
            {d["label"]: d["count"] for d in result["wards"].values()},
            indent=2, sort_keys=True))
