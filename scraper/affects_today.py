"""Stories that affect readers TODAY (editor, 17 Nov 2026).

"Stories that affect TODAY such as traffic incidents, power cuts, school
closures, nursery closures, college closures, missing persons should be posted
to Facebook immediately and not wait for a slot."

Measured 17 Nov 2026 before this rule existed: of 17 such stories published
since 10 Oct, Facebook carried them a median of about three hours late (worst
28 hours, the missing 22-year-old Sean appeal) and four were never posted at
all (the missing 16-year-old girl in Norden, the St Cuthbert's bomb-threat
closure, the Piccadilly bus station closure, and the 17 Nov Heywood power cut,
which sat waiting for a photo).

Against the 1,979-story archive the rule matches 44 headlines (about 2%):
27 traffic incidents, 8 missing-person appeals, 4 utility outages, 4 public
warnings and 1 school closure. Missing pets, planned roadworks, court and
inquest reports about past crashes, and permanent or proposed closures do NOT
match: they are not things a reader has to act on today.

Judged on the headline, like feature_policy.is_public_warning, so the same
story gets the same answer in every lane.
"""
from __future__ import annotations

import html
import re
from typing import Any

from feature_policy import is_public_warning

# Aftermath and court reporting is about something that has already happened.
_AFTERMATH = re.compile(
    r"\b(?:court|jailed|sentenced|convicted|guilty|charged|trial|inquest|jury|pleads?|admits|"
    r"arrest\w*|banned from driving|appeals? against|years? ago|anniversary|funeral|named as)\b",
    re.I,
)
# Planned, proposed or permanent: news, but not something happening today.
_NOT_TODAY = re.compile(
    r"\b(?:road\s*works?|resurfacing|scheduled|plans?|proposals?|proposed|consultation|"
    r"permanent(?:ly)?|for good|next (?:week|month|year)|in 20\d\d|from \d{1,2} \w+|"
    r"to close (?:in|at the end)|will close|set to close|could close|faces closure|"
    r"threat of closure|closure threat|merger|meeting|discuss\w*|petition|campaign)\b",
    re.I,
)

_MISSING = re.compile(r"\b(?:missing|have you seen|found safe)\b", re.I)
_PERSON = re.compile(
    r"\b(?:man|woman|men|women|boy|girl|teen\w*|child|children|son|daughter|pensioner|"
    r"\d{1,2}[- ]year[- ]old|aged \d+|schoolboy|schoolgirl|mum|dad|grandad|grandmother|"
    r"person|people|he|she|his|her)\b",
    re.I,
)
_MISSING_NOT = re.compile(r"\bmissing (?:out|link|piece|payments?|bins?|collections?|funds?|money|data)\b", re.I)

_UTILITY = re.compile(
    r"\b(?:power cuts?|blackouts?|power outages?|without power|no power|water off|no water|"
    r"without water|burst (?:water )?main|low water pressure|gas (?:leak|outage|supply)|without gas)\b",
    re.I,
)

_EDUCATION_CLOSED = re.compile(
    r"\b(?:schools?|nurser(?:y|ies)|colleges?|academ(?:y|ies)|primary|high school|pre-?school|"
    r"playgroups?|sixth form|campus)\b.{0,60}\b(?:closed|closes|closing|shut|shuts|closure|closures|"
    r"sent home|evacuated|lockdown|locked down|no heating|no water|burst pipe|power cut)\b|"
    r"\b(?:closed|shut)\b.{0,40}\b(?:schools?|nurser(?:y|ies)|colleges?)\b",
    re.I,
)

_CRASH = re.compile(
    r"\b(?:crash(?:es|ed)?|collisions?|collided|overturned|lorry fire|car fire|vehicle fire|"
    r"jack-?knifed|hit by (?:a )?(?:car|van|lorry|bus|vehicle|train|tram))\b",
    re.I,
)
_DISRUPTION = re.compile(
    r"\b(?:broken[- ]down|breakdown|spillage|police incident|serious incident|delays?|tailbacks?|"
    r"queues?|gridlock|closed|closure|shut|blocked|diversions?|suspended)\b",
    re.I,
)
_ROAD = re.compile(
    r"\b(?:transport|roads?|streets?|lanes?|avenue|motorway|M62|M60|M66|A\d{2,4}|junction|J\d+|"
    r"bypass|roundabout|carriageway|bridge|tram|metrolink|trains?|rail|line|bus(?:es)?|traffic)\b",
    re.I,
)
# A business named "Caliber Collision" is not a collision (incident_rule.py).
_NOT_A_CRASH = re.compile(r"\bcaliber collision\b", re.I)


def _plain(value: Any) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return " ".join(html.unescape(text).split())


def today_kind(article: Any) -> str:
    """'missing-person', 'utility-outage', 'school-closure', 'traffic-incident'
    or 'public-warning' when the story affects readers today, else ''."""
    if not isinstance(article, dict):
        return ""
    title = _plain(article.get("title"))
    if not title or _AFTERMATH.search(title):
        return ""
    if _MISSING.search(title) and _PERSON.search(title) and not _MISSING_NOT.search(title):
        return "missing-person"
    if _UTILITY.search(title):
        return "utility-outage"
    not_today = bool(_NOT_TODAY.search(title))
    if _EDUCATION_CLOSED.search(title) and not not_today:
        return "school-closure"
    if not not_today and not _NOT_A_CRASH.search(title):
        if _CRASH.search(title):
            return "traffic-incident"
        if _DISRUPTION.search(title) and _ROAD.search(title):
            return "traffic-incident"
    if is_public_warning(article):
        return "public-warning"
    return ""


def affects_today(article: Any) -> bool:
    return bool(today_kind(article))
