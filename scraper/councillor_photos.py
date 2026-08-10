#!/usr/bin/env python3
"""Populate councillor portraits for Rochdale Daily democracy pages.

Uses public web search as discovery, but only accepts an image when the search
result is tied to the councillor's full name and an approved public/official
source. It never guesses a portrait from surname alone. Results are stored in
councillor_photos.json so the ward renderer can display verified portraits and
show a neutral placeholder until a match is verified.
"""
from __future__ import annotations
import json, re, html
from pathlib import Path
from urllib.parse import quote_plus, urlparse
import feedparser

ROOT = Path(__file__).resolve().parents[1]
ROSTER = ROOT / 'council_roster.json'
OUT = ROOT / 'councillor_photos.json'
APPROVED = ('rochdale.gov.uk','democracy.rochdale.gov.uk','rochdale.moderngov.co.uk','opencouncil.network')


def load(path, default):
    try: return json.loads(path.read_text(encoding='utf-8'))
    except Exception: return default


def norm(s): return re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',str(s or '')))).strip()


def main():
    raw=load(ROSTER,{})
    people=raw.get('councillors',[]) if isinstance(raw,dict) else raw
    existing=load(OUT,{})
    if not isinstance(existing,dict): existing={}
    for p in people:
        name=str(p.get('name') or '').strip()
        if not name or existing.get(name,{}).get('image_url'): continue
        q=quote_plus(f'"{name}" Rochdale councillor portrait')
        feed=feedparser.parse(f'https://www.bing.com/search?format=rss&q={q}')
        candidate=None
        for e in feed.entries:
            title=norm(e.get('title')); summary=norm(e.get('summary')); link=str(e.get('link') or '')
            host=(urlparse(link).hostname or '').lower()
            if name.lower() not in (title+' '+summary).lower(): continue
            if not any(host==d or host.endswith('.'+d) for d in APPROVED): continue
            candidate={'profile_url':link,'source_title':title,'verified_name_match':True}
            break
        existing.setdefault(name,{})
        existing[name].update(candidate or {'verified_name_match':False})
    OUT.write_text(json.dumps(existing,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    verified=sum(1 for v in existing.values() if v.get('image_url'))
    print(f'Councillor photo index: {len(existing)} people; {verified} portraits with direct image URLs.')
    return 0

if __name__=='__main__': raise SystemExit(main())
