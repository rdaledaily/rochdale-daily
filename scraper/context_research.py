"""Bounded, attributed background research without merging separate events."""
from __future__ import annotations

import json
from pathlib import Path
import re
import time
from urllib.parse import quote_plus, urlparse

import feedparser
import requests

from editorial_contract import ward_decision, plain
from story_identity import same_story
from google_news_resolver import is_google_wrapper, _lightweight_resolve

CONTEXT_POLICY = (
    "Seek useful factual context from additional identifiable sources for every substantive story. "
    "Source records marked background describe OTHER events or general context: never merge their "
    "people, dates, outcomes or allegations into this incident. Give historical comparisons their "
    "own date, place and named publication. Multiple outlets repeating one release are not independent "
    "corroboration. Public posts on X are attributed leads or statements, never automatic proof of an incident or a measure of public opinion. Prefer primary public records and clearly attribute secondary reporting. "
    "Crime rates need a verified measure, period, geography and population denominator. Never turn "
    "a count, postal district, police neighbourhood or borough rate into a ward rate; missing data is "
    "not zero crime. GMP priorities must come from the actual local team's dated official page. "
    "For developers, distinguish the same company/legal entity, completed schemes, independently "
    "documented complaints or regulator/ombudsman findings and dated satisfaction surveys from "
    "marketing, anonymous reviews and unproved allegations. Do not declare an overall reputation "
    "from one complaint. For quoted speakers, state only relevant verified public roles, expertise, "
    "party affiliations or declared financial interests. Explain potential interests fairly, give "
    "the statement itself, and never infer motive or bias from ethnicity, religion or private life. "
    "For suicide coverage, do not infer suicide from an unexplained death or describe methods. "
    "Do not label or publicise a site as a hotspot without explicit reliable public-health evidence. "
    "Use verified prevention strategy and support information; do not invent contacts or medical advice. "
    "When evidence is unavailable, omit the unsupported addition and record the research gap. "
    "Do not pad an article simply to make it longer."
)

def get(item, key, default=''):
    return item.get(key, default) if isinstance(item, dict) else getattr(item, key, default)

def plan_for(item):
    title = str(get(item, 'source_title') or get(item, 'title'))
    text = plain(title + ' ' + str(get(item, 'source_summary') or get(item, 'excerpt')))
    area = str(get(item, 'area') or 'Rochdale').replace('-', ' ')
    plans = [{'role': 'same_incident', 'query': '"' + title.replace('"', '')[:180] + '"'}]
    company = re.search(r'\b(Bellway|Barratt|David Wilson|Persimmon|Taylor Wimpey|Redrow|Bloor|Keepmoat|Vistry|Lovell|Countryside)\b', text, re.I)
    if company and re.search(r'\b(?:homes|housing|development|build|building|developer)\b', text, re.I):
        plans += [{'role': 'company_track_record', 'query': '"' + company.group(1) + '" completed development Greater Manchester'},
                  {'role': 'company_track_record', 'query': '"' + company.group(1) + '" ombudsman quality satisfaction findings'}]
    elif re.search(r'\b(?:suicide|took (?:his|her|their) own life)\b', text, re.I):
        plans += [{'role': 'prevention_context', 'url': 'https://www.gov.uk/government/publications/suicide-prevention-strategy-for-england-2023-to-2028/suicide-prevention-in-england-5-year-cross-sector-strategy'}]
    elif str(get(item, 'category')).casefold() == 'crime':
        subject = next((w for w in ('burglary', 'robbery', 'stabbing', 'fraud', 'theft', 'assault', 'murder') if re.search(r'\b' + w + r'\b', text, re.I)), '')
        if subject:
            plans += [{'role': 'historical_comparison', 'query': '"' + area + '" ' + subject}]
    else:
        # Context search follows named subject terms, not an unrelated generic
        # borough search. It is evidence discovery, never a claim of corroboration.
        speakers = re.findall(r'\b(?:Councillor|Cllr|Mayor|MP|Dr|Professor)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})', text)
        named = speakers or re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}\b', text)
        if named:
            plans += [{'role': 'public_background', 'query': '"' + named[0] + '" ' + area + ' public role background'}]
    return plans[:3]

def discover(query):
    url = 'https://news.google.com/rss/search?q=' + quote_plus(query) + '&hl=en-GB&gl=GB&ceid=GB:en'
    response = requests.get(url, timeout=6, headers={'User-Agent':'RochdaleDailyContext/1.0 (news@rochdaledaily.co.uk)'})
    response.raise_for_status()
    results = []
    for entry in feedparser.parse(response.content).entries[:4]:
        link = str(entry.get('link') or '')
        if is_google_wrapper(link):
            link = _lightweight_resolve(link)
        if link and not is_google_wrapper(link):
            results.append(link)
    return results

def gather(item, existing, fetch_metadata, source_is_denied, root=None):
    """Return captured additional records and an honest research-status ledger."""
    root = root or Path(__file__).resolve().parents[1]
    records = list(existing)
    seen = {str(r.get('url') or '').rstrip('/') for r in records}
    ledger = []
    plans = plan_for(item)
    deadline = time.monotonic() + 18
    ward = ward_decision({'title': get(item, 'source_title') or get(item, 'title'),
                          'excerpt': get(item, 'source_summary') or get(item, 'excerpt'),
                          'area': get(item, 'area')})
    if str(get(item, 'category')).casefold() == 'crime':
        try:
            priorities = json.loads((root/'assets/data/gmp-ward-policing-priorities.json').read_text()).get('wards', {})
            for name in ward['wards']:
                if priorities.get(name, {}).get('url'):
                    plans.append({'role': 'policing_priorities', 'url': priorities[name]['url']})
        except (OSError, ValueError):
            pass
        # The repository's FOI extract is explicitly verification_pending.
        # Do not turn its ambiguous columns into a rate or another geography.
        ledger.append({'question': 'Current comparable crime rate for the actual area', 'status':'requires-verified-measure-period-geography-and-denominator'})
    for task in plans[:4]:
        if time.monotonic() > deadline:
            ledger.append({'question':task.get('query') or task.get('url'),'status':'research-budget-exhausted'})
            continue
        added = 0
        try:
            urls = [task['url']] if task.get('url') else discover(task['query'])
        except Exception as exc:
            ledger.append({'question': task.get('query') or task.get('url'), 'status':'discovery-unavailable', 'reason':type(exc).__name__})
            continue
        for url in urls[:2]:
            if time.monotonic() > deadline:
                break
            if len(records) >= len(existing) + 4:
                break
            if url.rstrip('/') in seen or source_is_denied('', url) or urlparse(url).hostname == 'rochdaledaily.co.uk':
                continue
            try:
                metadata = fetch_metadata(url)
            except Exception:
                continue
            body = plain(metadata.get('body_excerpt'))
            if len(body) < 160:
                continue  # A search snippet is discovery, not captured evidence.
            role = task['role']
            if role == 'same_incident':
                probe = {'title': metadata.get('title'), 'excerpt':metadata.get('description'), 'content_html':body,
                         'source_url':url,'area':get(item,'area'), 'category':get(item,'category'),
                         'published_at':metadata.get('published_at') or metadata.get('published')}
                if not same_story(item, probe):
                    continue
            records.append({'name':metadata.get('site_name') or urlparse(url).hostname, 'url':url,
                            'title':metadata.get('title'), 'summary':metadata.get('description'),
                            'body_excerpt':body[:5200], 'published_at':metadata.get('published_at') or metadata.get('published'),
                            'context_role':role, 'context_is_same_incident':role=='same_incident'})
            seen.add(url.rstrip('/')); added += 1
        ledger.append({'question':task.get('query') or task.get('url'), 'role':task['role'], 'status':'captured' if added else 'no-additional-verified-source', 'sources_added':added})
    return records, ledger
