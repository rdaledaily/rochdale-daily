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
WARD_PLACES_PATH = ROOT / 'ward_places.json'
POSTCODE_RE = re.compile(r'\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b', re.I)
# A venue given in running copy: "at Heywood Library, LCpl Stephen Shaw MC Way,
# Heywood, OL10 1LW". The "at" matters: a postcode that follows "write to" or
# closes a contact line is where to send a letter, not where the story is.
VENUE_POSTCODE_RE = re.compile(r'\bat\s+[^.;:!?]{3,140}?(' + POSTCODE_RE.pattern[2:-2] + r')\b', re.I)
STREET_WORDS = r'(?:Road|Street|Lane|Avenue|Drive|Close|Way|Crescent|Grove|Terrace)'
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


def _evidenced_ward(article: dict) -> dict:
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
    return {'wards': [], 'status': 'borough-or-location-unresolved', 'evidence': ''}


# Every story has a place on the ward hubs (editor, 14 Nov 2026: "All inbound
# stories must carry a ward or have a ward discoverable"). Measured that day:
# 504 of 613 live stories had no ward. The evidenced rules above stay first and
# unchanged; after them, in order:
#   body-ward / body-locality  a ward or a one-ward place named, with a place
#                              preposition, in the first two paragraphs;
#   place-verified             a club, college, hospital or venue in
#                              ward_places.json, its ward looked up from its
#                              own postcode (never typed by hand);
#   township                   Heywood, Middleton or Littleborough named:
#                              every ward of that town (editor's choice);
#   borough-wide               the rest: about Rochdale as a whole. These carry
#                              no ward and are listed under "Across the borough"
#                              on every ward hub, never claimed for one ward.
TOWNSHIP_RE = re.compile(r"\b(Heywood|Middleton|Littleborough)\b(?!\s+(?:Road|Street|Lane|Avenue|Way|Junction|Precinct))", re.I)
_TOWN_LEADS = {'In', 'At', 'From', 'Across', 'Around', 'Near', 'Of', 'To', 'For', 'The', 'And', 'South', 'North', 'East',
               'West', 'Central', 'Rochdale', 'Greater', 'Serving', 'Inside', 'Outside', 'Visit', 'Visits'}
_BANNER_RE = re.compile(r'^(?:ONGOING STORY|LIVE\b|DEVELOPING|BREAKING)', re.I)


def opening_paragraphs(article: dict, count: int = 2) -> str:
    found = []
    for raw in re.findall(r'<p\b[^>]*>(.*?)</p>', str(article.get('content_html') or ''), re.S | re.I):
        text = plain(raw)
        if text and not _BANNER_RE.match(text):
            found.append(text)
            if len(found) == count:
                break
    if not found:
        found = [plain(article.get('body') or article.get('summary') or '')]
    return ' '.join(found)


def township_wards() -> dict[str, list[str]]:
    """Town -> its wards, from ward_areas.json (the editor's file)."""
    wards = (_json_file(WARD_AREAS_PATH) or {}).get('wards') or {}
    towns: dict[str, list[str]] = {}
    for ward, config in wards.items():
        if ward not in ROCHDALE_WARDS or not isinstance(config, dict):
            continue
        for area in config.get('areas') or []:
            if str(area).casefold() in {'heywood', 'middleton', 'littleborough'}:
                towns.setdefault(str(area).casefold(), []).append(ward)
    return {town: sorted(found) for town, found in towns.items()}


def ward_places() -> dict[str, dict]:
    places = (_json_file(WARD_PLACES_PATH) or {}).get('places') or {}
    return {name: entry for name, entry in places.items() if isinstance(entry, dict) and entry.get('postcode')}


def place_postcodes() -> list[str]:
    return sorted({compact_postcode(entry['postcode']) for entry in ward_places().values()})


def _body_ward(article: dict, text: str) -> dict | None:
    probe = {'title': text, 'excerpt': '', 'area': '', 'content_html': '', 'event_location': ''}
    found = _evidenced_ward(probe)
    if found['wards'] and found['status'] in {'explicit-ward', 'named-locality'}:
        status = 'body-ward' if found['status'] == 'explicit-ward' else 'body-locality'
        return {'wards': found['wards'], 'status': status, 'evidence': text[:300]}
    return None


def _place_ward(text: str) -> dict | None:
    cache = _json_file(POSTCODE_EVIDENCE_PATH) or {}
    low = text.casefold().replace('\u2019', "'")
    wards, evidence = set(), []
    for name, entry in ward_places().items():
        names = [str(n).casefold().replace('\u2019', "'") for n in entry.get('names') or [name]]
        if any(re.search(r'(?<!\w)' + re.escape(n) + r'(?!\w)', low) for n in names):
            looked_up = cache.get(compact_postcode(entry['postcode']))
            if isinstance(looked_up, dict) and looked_up.get('district') == 'Rochdale' and looked_up.get('ward') in ROCHDALE_WARDS:
                wards.add(looked_up['ward'])
                evidence.append({'place': name, 'postcode': entry['postcode'], 'ward': looked_up['ward']})
    if wards:
        return {'wards': sorted(wards), 'status': 'place-verified', 'evidence': evidence}
    return None


def ward_decision(article: dict) -> dict:
    """Where a story belongs on the ward hubs. Always answers."""
    decision = _evidenced_ward(article)
    if decision['wards']:
        return decision
    if _is_roundup(article):
        return {'wards': [], 'status': 'borough-wide', 'scope': 'borough', 'evidence': 'round-up of the day'}
    subject = plain(article.get('title')) + ' ' + plain(article.get('excerpt'))
    opening = opening_paragraphs(article)
    found = _body_ward(article, opening)
    if found:
        return found
    # Places count in the headline, standfirst and FIRST paragraph only: a
    # second paragraph is where "send objections to Number One Riverside"
    # lives, which is an address, not where the story is.
    found = _place_ward(subject + ' ' + opening_paragraphs(article, 1))
    if found:
        return found
    towns = township_wards()
    text = subject + ' ' + opening
    named = set()
    for m in TOWNSHIP_RE.finditer(text):
        # "Glenn Middleton" is a footballer, not the town: a capitalised word
        # straight before the name that is not a place word means a person.
        before = re.search(r"([A-Z][a-z]+)\s+$", text[max(0, m.start() - 20):m.start()])
        if before and before.group(1) not in _TOWN_LEADS:
            continue
        named.add(m.group(1).casefold())
    area = str(article.get('area') or '').casefold()
    if area in towns and re.search(r'\b' + re.escape(area) + r'\b', opening, re.I):
        named.add(area)
    named &= set(towns)
    # A list naming every town ("Rochdale, Heywood, Middleton, Littleborough")
    # is a borough round-up, not a town story.
    if named and named == set(towns):
        return {'wards': [], 'status': 'borough-wide', 'scope': 'borough', 'evidence': 'names every town'}
    if named:
        wards = sorted({w for town in named for w in towns[town]})
        return {'wards': wards, 'status': 'township', 'township': ', '.join(t.title() for t in sorted(named)),
                'evidence': subject[:300]}
    return {'wards': [], 'status': 'borough-wide', 'scope': 'borough', 'evidence': ''}


def ward_hub_scope(article: dict) -> str:
    """'ward' (one or more wards), 'township', or 'borough' (every hub)."""
    decision = ward_decision(article)
    if decision['status'] == 'borough-wide':
        return 'borough'
    return 'township' if decision['status'] == 'township' else 'ward'


def reader_ending(article: dict) -> str:
    """Withdrawn 9 Nov 2026: stories end on their last fact, never on a
    comment invitation or a question to readers. Always returns ''; kept so
    existing imports keep working."""
    return ''
