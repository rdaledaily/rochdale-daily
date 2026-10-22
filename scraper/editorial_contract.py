"""Deterministic reader structure, classification and evidenced ward decisions."""
from __future__ import annotations

import re
import json
from pathlib import Path
from typing import Any

from selection_policy import ROCHDALE_WARDS, AREA_TO_WARD
from story_integrity_audit import ALLOWED_CATEGORIES, headline_category

NATURAL_STORY_POLICY = (
    "For non-crime reporting, tell the story naturally in this order where the evidence allows: "
    "what happened; who it affected; which public services or organisations were involved; "
    "where it happened; the established outcome or next step; and why it matters to readers. "
    "These are reporting questions, not mandatory headings. Do not invent affected people, "
    "police or ambulance attendance, causes, outcomes or public reactions to fill a slot. "
    "End non-crime articles with a specific reader-relevant takeaway and an invitation to "
    "comment on that story. Safety, green belt, school security or another lesson must follow "
    "from the actual reporting, never insinuate blame or turn an unproved inference into fact. "
    "Exclude crime and court reporting from this engagement structure and all comment invitations."
)

def plain(value: Any) -> str:
    from html import unescape
    return ' '.join(unescape(re.sub(r'<[^>]+>', ' ', str(value or ''))).split())


def category_for(article: dict) -> str:
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
    """Topic-specific invitation, with no invented event facts or advice."""
    if category_for(article) == 'crime' or article.get('sponsored'):
        return ''
    title = plain(article.get('title')).casefold()
    category = category_for(article)
    if re.search(r'\bmissing\b', title):
        return 'How can local communities support families during a missing person appeal? Share your thoughts in the comments. Any information about this appeal should go directly to the police using the contact details above.'
    if re.search(r'\bgreen belt\b', title):
        return 'What should decision makers weigh most carefully when considering development on green belt land? Tell us how the proposal would affect you in the comments.'
    if re.search(r'\b(?:school|college)\b.*\b(?:threat|evacuat|security)|\b(?:threat|evacuat|security)\w*\b.*\b(?:school|college)\b', title):
        return 'What information or reassurance would help pupils and families? Share your thoughts on school safety in the comments, without identifying children or sharing unverified claims.'
    if category == 'traffic':
        return 'How does this affect your journeys, and what would make local roads work better for you? Share your experience in the comments.'
    if re.search(r'\b(?:housing|homes|development|planning|flats)\b', title):
        return 'What does this mean for your neighbourhood, and what would you want decision makers to consider? Share your thoughts in the comments.'
    if category == 'education':
        return 'What does this mean for pupils and families in your area? Share your thoughts in the comments, without identifying children.'
    if category == 'health':
        return 'What would make local services work better for you and your family? Share your thoughts in the comments, keeping personal medical details private.'
    if category == 'transport':
        return 'How does this affect your travel, and what changes would help you? Tell us in the comments.'
    if category == 'environment':
        return 'How does this affect your local surroundings, and what would you like to happen next? Share your thoughts in the comments.'
    if category == 'events':
        return 'Is this the kind of event you would like to see more of locally? Tell us what matters to you in the comments.'
    if category == 'sport':
        return 'What is your view of this development, and what would you like to see next? Share your thoughts with other local supporters in the comments.'
    if category == 'business':
        return 'What does this mean for local customers, workers or businesses? Share your thoughts in the comments.'
    if category == 'politics':
        return 'How does this affect you, and what would you want your representatives to do next? Share your thoughts in the comments.'
    return 'How does this affect you or your neighbourhood, and what would you like to happen next? Share your thoughts in the comments.'
