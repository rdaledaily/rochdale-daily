"""Deterministic reader structure, classification and evidenced ward decisions."""
from __future__ import annotations

import re
import json
from pathlib import Path
from typing import Any

from selection_policy import ROCHDALE_WARDS, AREA_TO_WARD

NATURAL_STORY_POLICY = (
    "For non-crime reporting, tell the story naturally in this order where the evidence allows: "
    "what happened; who it affected; which public services or organisations were involved; "
    "where it happened; the established outcome or next step; and why it matters to readers. "
    "These are reporting questions, not mandatory headings. Do not invent affected people, "
    "police or ambulance attendance, causes, outcomes or public reactions to fill a slot. "
    "End every article on its last verified fact, a quotation, background or what happens next. "
    "Never end with a question to readers, an invitation to comment or share thoughts, a moral, "
    "a line about what the story 'raises concerns about' or 'the importance of', or any lesson "
    "in Rochdale Daily's own voice. Never insinuate blame or turn an unproved inference into fact. "
    "The only closing notices allowed are right of reply, corrections and "
    "'Rochdale Daily has asked <body> for comment' when that request is recorded."
)
# 9 Nov 2026 (editor): the 22 Oct "takeaway and invitation to comment" ending
# is withdrawn (superseded 7 Nov). It opened HOUSE_STYLE_SYSTEM and so
# contradicted house_style's own ending rules inside the same prompt.

def plain(value: Any) -> str:
    from html import unescape
    return ' '.join(unescape(re.sub(r'<[^>]+>', ' ', str(value or ''))).split())


def category_for(article: dict) -> str:
    from story_integrity_audit import ALLOWED_CATEGORIES, headline_category
    proposed = headline_category(article)
    current = str(article.get('category') or '').casefold()
    return proposed or (current if current in ALLOWED_CATEGORIES else 'news')


ROOT = Path(__file__).resolve().parents[1]
POSTCODE_EVIDENCE_PATH = ROOT / 'ward_postcode_evidence.json'
WARD_AREAS_PATH = ROOT / 'ward_areas.json'
POSTCODE_RE = re.compile(r'\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b', re.I)
# A venue given in running copy: "at Heywood Library, LCpl Stephen Shaw MC Way,
# Heywood, OL10 1LW". The "at" matters: a postcode that follows "write to" or
# closes a contact line is where to send a letter, not where the story is.
VENUE_POSTCODE_RE = re.compile(r'\bat\s+[^.;:!?]{3,140}?(' + POSTCODE_RE.pattern[2:-2] + r')\b', re.I)
STREET_WORDS = r'(?:Road|Street|Lane|Avenue|Drive|Close|Way|Crescent|Grove|Terrace)'
# --- Streets (14 Nov 2026) -------------------------------------------------
# rochdale_streets.json lists every street in OL11, OL12 and OL16 with one
# postcode for each postcode sector it runs through. A street listed in one
# sector only is short enough to belong to one ward, provided it is not on a
# ward boundary; ward_postcode_evidence.py checks that by asking which wards
# the postcodes within STREET_CHECK_RADIUS_M of it lie in, and records the
# answer in ward_street_evidence.json. Roads listed in two or more sectors
# (Manchester Road, Halifax Road) run through several wards and are never used.
STREETS_PATH = Path(__file__).resolve().parent / 'rochdale_streets.json'
STREET_EVIDENCE_PATH = ROOT / 'ward_street_evidence.json'
STREET_CHECK_RADIUS_M = 250
STREET_NAME_RE = re.compile(
    r"\b((?:[A-Z][A-Za-z']+\s+){1,3}(?:Street|Road|Lane|Avenue|Drive|Close|Crescent|Way|Grove|Terrace|Place|Square|Walk|Gardens|Court|Fold|Brow|Row|Mews|View|Parade))\b")
# The street list does not cover Heywood (OL10), Middleton (M24) or
# Littleborough (OL15). A story from one of those towns naming "Church Street"
# means that town's Church Street, not the one in the list.
STREET_UNCOVERED_AREAS = frozenset({'heywood', 'darnhill', 'hopwood', 'middleton', 'alkrington', 'boarshaw', 'littleborough',
                                    'whitworth', 'bury', 'burnley', 'mytholmroyd', 'greater-manchester'})
# "Manchester Road" and "Bury Old Road" are streets, not mentions of the town.
STREET_UNCOVERED_TOWNS_RE = re.compile(
    r'\b(?:Heywood|Middleton|Littleborough|Whitworth|Bury|Oldham|Manchester|Bacup|Todmorden)\b'
    r'(?!\s+(?:(?:Old|New)\s+)?(?:Road|Street|Lane|Avenue|Drive|Close|Crescent|Way|Grove|Terrace|Place|Square|Walk|Gardens)\b)')
_FILE_CACHE: dict[str, tuple[float, Any]] = {}


def _json_file(path: Path) -> Any:
    """Read a small JSON data file once per change. ward_decision runs for
    every story on every ward page, so it must not re-read the disk each time."""
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return {}
    cached = _FILE_CACHE.get(str(path))
    if cached and cached[0] == stamp:
        return cached[1]
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        data = {}
    _FILE_CACHE[str(path)] = (stamp, data)
    return data


def canonical_ward(name: Any) -> str:
    """The site's spelling of a ward, or ''. The statutory names use an
    ampersand ("Balderstone & Kirkholt"); this site writes "and"."""
    key = re.sub(r'[^a-z]+', ' ', str(name or '').casefold().replace('&', ' and ')).strip()
    for ward in ROCHDALE_WARDS:
        if re.sub(r'[^a-z]+', ' ', ward.casefold()).strip() == key:
            return ward
    return ''


def compact_postcode(value: str) -> str:
    return re.sub(r'\s+', '', str(value or '')).upper()


def _is_roundup(article: dict) -> bool:
    slug = str(article.get('slug') or '')
    return bool(article.get('briefing_slot')) or slug.startswith(('morning-briefing-', 'evening-wrap'))


def story_postcodes(article: dict) -> list[str]:
    """Full postcodes that say where the story is, most specific first:
    the event location; else the opening sentence; else a venue named in the
    copy ("at <venue>, <postcode>"), when the whole story has one or two
    postcodes. A story listing three or more places is a round-up and a
    briefing is every story at once: neither belongs to one ward."""
    found = POSTCODE_RE.findall(plain(article.get('event_location')))
    if not found:
        body = plain(article.get('content_html'))
        found = POSTCODE_RE.findall(body.split('. ', 2)[0])
        if not found and not _is_roundup(article):
            everywhere = {compact_postcode(pc) for pc in POSTCODE_RE.findall(body)}
            if 1 <= len(everywhere) <= 2:
                found = VENUE_POSTCODE_RE.findall(body)
    return sorted({compact_postcode(pc) for pc in found})


def story_streets(article: dict) -> list[dict[str, str]]:
    """Every street named in the headline, standfirst or event location:
    [{'street', 'postcode'}]. Never the body: a street mentioned in passing is
    not where the story is.

    A street the list places in a single postcode sector carries that
    postcode and can be checked. A road listed in several sectors, or a street
    the list does not know, is still returned, with an empty postcode: it
    can never be settled, and ward_decision tags a story only when every
    street it names is settled. Dropping such a road here would let "Joy
    Street and Halifax Road roadworks" be placed by Joy Street alone."""
    if str(article.get('area') or '').casefold() in STREET_UNCOVERED_AREAS or _is_roundup(article):
        return []
    subject = '. '.join(plain(article.get(key)) for key in ('title', 'excerpt', 'event_location')).replace('\u2019', "'")
    if STREET_UNCOVERED_TOWNS_RE.search(subject):
        return []
    listed = (_json_file(STREETS_PATH) or {}).get('streets') or {}
    found: dict[str, dict[str, str]] = {}
    for match in STREET_NAME_RE.findall(subject):
        words = match.split()
        # "Police On Trafalgar Street" -> "Trafalgar Street": longest listed name wins.
        for start in range(len(words) - 1):
            key = ' '.join(words[start:]).casefold()
            record = listed.get(key)
            if record:
                postcodes = record.get('postcodes') or []
                found[key] = {'street': str(record.get('name') or key),
                              'postcode': compact_postcode(postcodes[0]) if len(postcodes) == 1 else ''}
                break
        else:
            # Not in the list at all: the last two words are the street name.
            found[' '.join(words[-2:]).casefold()] = {'street': ' '.join(words[-2:]), 'postcode': ''}
    return [found[key] for key in sorted(found)]


def locality_wards() -> dict[str, str]:
    """Place name -> the one ward it lies in. The built-in list plus every
    area the editor's ward_areas.json files under exactly one ward, so a place
    can be added there without touching code. Places split between wards
    (Middleton, Heywood, Littleborough) are deliberately absent."""
    mapping = dict(AREA_TO_WARD)
    wards = (_json_file(WARD_AREAS_PATH) or {}).get('wards') or {}
    owners: dict[str, set[str]] = {}
    for ward, config in wards.items():
        if ward not in ROCHDALE_WARDS or not isinstance(config, dict):
            continue
        for area in config.get('areas') or []:
            owners.setdefault(str(area).casefold().strip(), set()).add(ward)
    for area, found in owners.items():
        if len(found) == 1 and re.fullmatch(r"[a-z][a-z' ]+", area):
            mapping.setdefault(area, next(iter(found)))
    for area, found in owners.items():
        if len(found) > 1:
            mapping.pop(area, None)
    return mapping


def ward_decision(article: dict) -> dict:
    """No first-place-in-body vote, surname matching, or township-to-ward guess."""
    title = plain(article.get('title'))
    excerpt = plain(article.get('excerpt'))
    # A ward must describe the subject, not a source, councillor's portfolio,
    # address in the footer, or another incident in a rolling timeline.
    subject = title + ' ' + excerpt
    explicit = []
    for ward in ROCHDALE_WARDS:
        pattern = r'(?<!\w)' + re.escape(ward) + r'(?!\w)'
        if ward == 'Hopwood Hall' and re.search(r'Hopwood Hall (?:College|campus)', subject, re.I):
            continue
        # One-word ward names are also surnames and street names. Require
        # explicit ward language or a geographic preposition.
        if len(ward.split()) == 1:
            pattern = r'\b(?:in|across|around|from|at)\s+' + re.escape(ward) + r'(?!\s+(?:Road|Street|Lane))\b|' + re.escape(ward) + r'\s+ward\b'
        if re.search(pattern, subject, re.I):
            explicit.append(ward)
    if explicit:
        return {'wards': explicit, 'status': 'explicit-ward', 'evidence': subject}
    # Full postcodes have an independently fetched ward, never a district
    # prefix such as OL11. Multiple sites remain multiple wards. The lookups
    # are made by ward_postcode_evidence.py and kept in the repository; a
    # postcode not looked up yet decides nothing.
    cache = _json_file(POSTCODE_EVIDENCE_PATH) or {}
    verified = [cache.get(pc) for pc in story_postcodes(article)]
    verified = [v for v in verified if isinstance(v, dict) and v.get('district') == 'Rochdale' and v.get('ward') in ROCHDALE_WARDS]
    if verified:
        return {'wards': sorted({v['ward'] for v in verified}), 'status': 'postcode-verified', 'evidence': verified}
    area = str(article.get('area') or '').casefold()
    localities = locality_wards()
    local = []
    for locality,ward in localities.items():
        pattern = r'\b(?:in|at|across|around)\s+' + re.escape(locality) + r'(?!\s+(?:Road|Street|Lane))\b'
        # "Milnrow road closure" is about Milnrow; "Milnrow Road" is a street
        # that runs through other wards, so a capitalised Road does not count.
        starts = r'^(?i:' + re.escape(locality) + r')\s+(?:(?i:roadworks|residents|community|park|school|village|estate)|road)\b'
        if re.search(pattern,subject,re.I) or (area==locality and re.search(starts,title)):
            local.append(ward)
    if local:
        return {'wards':sorted(set(local)), 'status':'named-locality', 'evidence':subject}
    # Two independent signals agreeing: the story is filed under a place that
    # lies in one ward, and the headline or standfirst names that place. The
    # area tag alone is not enough (a borough-wide story can be filed under the
    # place its source sits in), and neither is the name alone (Healey and
    # Castleton are also surnames and street names).
    if area in localities:
        named = r'\b' + re.escape(area) + r"(?:['\u2019]s)?\b(?!\s+" + STREET_WORDS + r'\b)'
        college = area == 'hopwood' and re.search(r'Hopwood Hall (?:College|campus)', subject, re.I)
        if re.search(named, subject, re.I) and not college:
            found = {localities[area]}
            # "Bamford and Norden's 450-home allocation": a second place
            # joined to the first in the headline is part of the subject too.
            for other, ward in localities.items():
                pair = r'\b(?:' + re.escape(other) + r'\s+and\s+' + re.escape(area) + '|' + re.escape(area) + r'\s+and\s+' + re.escape(other) + r')\b'
                if other != area and re.search(pair, title, re.I):
                    found.add(ward)
            return {'wards': sorted(found), 'status': 'area-and-headline', 'evidence': subject}
    # A short street named in the headline, checked to lie in one ward. Last,
    # so it only fills gaps and never overrides a place or postcode above.
    named_streets = story_streets(article)
    if named_streets:
        on_file = _json_file(STREET_EVIDENCE_PATH) or {}
        checked = [on_file.get(item['street'].casefold()) if item['postcode'] else None for item in named_streets]
        good = [v for v in checked if isinstance(v, dict) and v.get('single_ward') is True
                and v.get('district') == 'Rochdale' and v.get('ward') in ROCHDALE_WARDS]
        # Every street named must be settled: one long road, unlisted street,
        # unchecked street or boundary street leaves the story untagged rather
        # than half-placed.
        if good and len(good) == len(named_streets):
            return {'wards': sorted({v['ward'] for v in good}), 'status': 'street-verified', 'evidence': good}
    return {'wards': [], 'status': 'borough-or-location-unresolved', 'evidence': ''}


def reader_ending(article: dict) -> str:
    """Withdrawn 9 Nov 2026: stories end on their last fact, never on a
    comment invitation or a question to readers. Always returns ''; kept so
    existing imports keep working."""
    return ''
