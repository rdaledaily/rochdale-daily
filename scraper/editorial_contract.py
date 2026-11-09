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
    # prefix such as OL11. Multiple sites remain multiple wards.
    cache_path = Path(__file__).resolve().parents[1] / 'ward_postcode_evidence.json'
    try:
        cache = json.loads(cache_path.read_text())
    except (OSError, ValueError):
        cache = {}
    location = plain(article.get('event_location'))
    lead = plain(article.get('content_html')).split('. ', 2)[0]
    candidates = re.findall(r'\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b', location or lead, re.I)
    verified = [cache.get(re.sub(r'\s+', '', pc).upper()) for pc in candidates]
    verified = [v for v in verified if v and v.get('district') == 'Rochdale' and v.get('ward') in ROCHDALE_WARDS]
    if verified:
        return {'wards': sorted({v['ward'] for v in verified}), 'status': 'postcode-verified', 'evidence': verified}
    area = str(article.get('area') or '').casefold()
    local = []
    for locality,ward in AREA_TO_WARD.items():
        pattern = r'\b(?:in|at|across|around)\s+' + re.escape(locality) + r'(?!\s+(?:Road|Street|Lane))\b'
        starts = r'^' + re.escape(locality) + r'\s+(?:road|roadworks|residents|community|park|school|village|estate)\b'
        if re.search(pattern,subject,re.I) or (area==locality and re.search(starts,title,re.I)):
            local.append(ward)
    if local:
        return {'wards':sorted(set(local)), 'status':'named-locality', 'evidence':subject}
    return {'wards': [], 'status': 'borough-or-location-unresolved', 'evidence': ''}


def reader_ending(article: dict) -> str:
    """Withdrawn 9 Nov 2026: stories end on their last fact, never on a
    comment invitation or a question to readers. Always returns ''; kept so
    existing imports keep working."""
    return ''
