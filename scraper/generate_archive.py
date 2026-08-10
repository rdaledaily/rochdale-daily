#!/usr/bin/env python3
"""Generate a permanent searchable public archive from retained article HTML pages."""
from __future__ import annotations
import html,json,re
from pathlib import Path
PAGES_DIR=Path('articles'); INDEX_PATH=Path('archive-index.json'); ARCHIVE_PATH=Path('archive.html'); SEARCH_PATH=Path('search.html')
def _meta(source,prop):
    for pattern in [rf'<meta[^>]+property=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']*)',rf'<meta[^>]+name=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']*)']:
        m=re.search(pattern,source,re.I)
        if m:return html.unescape(m.group(1)).strip()
    return ''
def _text(source,pattern):
    m=re.search(pattern,source,re.I|re.S)
    if not m:return ''
    return re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',m.group(1)))).strip()
def read_article(path):
    source=path.read_text(encoding='utf-8',errors='ignore')
    title=_meta(source,'og:title') or _text(source,r'<h1[^>]*>(.*?)</h1>') or _text(source,r'<title>(.*?)</title>')
    title=re.sub(r'\s*[|–-]\s*Rochdale Daily\s*$','',title,flags=re.I).strip()
    if not title:return None
    return {'title':title,'url':f'/articles/{path.name}','slug':path.stem,'published_at':_meta(source,'article:published_time') or _meta(source,'date'),'category':_meta(source,'article:section') or _text(source,r'<span[^>]+class=["\'][^"\']*story-kicker[^"\']*["\'][^>]*>(.*?)</span>'),'description':_meta(source,'description') or _meta(source,'og:description')}
def build_index():
    records=[]
    if PAGES_DIR.exists():
        for path in PAGES_DIR.glob('*.html'):
            item=read_article(path)
            if item:records.append(item)
    records.sort(key=lambda x:x.get('published_at',''),reverse=True)
    return records
def render(records):
    count=len(records)
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>All Stories | Rochdale Daily</title><meta name="description" content="Browse and search every retained Rochdale Daily story."><link rel="stylesheet" href="/assets/css/site.css"><style>.archive-wrap{{max-width:1050px;margin:0 auto;padding:24px 18px 60px}}.archive-search{{width:100%;box-sizing:border-box;font:inherit;font-size:18px;padding:14px 16px;border:2px solid #111;background:#fff}}.archive-meta{{margin:10px 0 24px;color:#555}}.archive-results{{display:grid;gap:12px}}.archive-item{{border-top:1px solid #ddd;padding:16px 0}}.archive-item a{{font-size:20px;font-weight:800;color:#111;text-decoration:none}}.archive-item .meta{{font-size:13px;text-transform:uppercase;margin:5px 0;color:#666}}.load-more{{margin:28px auto 0;display:block;border:2px solid #111;background:#111;color:#fff;font-weight:900;padding:12px 22px}}.load-more[hidden]{{display:none}}</style></head><body><header class="site-header"><div class="archive-wrap" style="padding-top:12px;padding-bottom:12px"><a class="brand" href="/"><img class="brand-logo" src="/assets/img/logo.png" alt="Rochdale Daily"></a></div></header><main class="archive-wrap"><h1>All Stories</h1><p>Every retained Rochdale Daily article, newest first. Stories may leave the homepage as they age, but remain here unless formally removed.</p><label for="archive-search"><strong>Search every published story</strong></label><input id="archive-search" class="archive-search" type="search" placeholder="Search a person, place, business, road, club or headline…" autocomplete="off"><div class="archive-meta"><span id="archive-count">{count:,}</span> stories</div><div id="archive-results" class="archive-results"></div><button id="load-more" class="load-more" type="button">Load more stories</button></main><script>const DATA={json.dumps(records,ensure_ascii=False)};const PAGE=100;let shown=PAGE;const input=document.getElementById('archive-search'),results=document.getElementById('archive-results'),count=document.getElementById('archive-count'),more=document.getElementById('load-more');function esc(s){{return String(s||'').replace(/[&<>\"]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}}[c]));}}function dateLabel(v){{if(!v)return '';const d=new Date(v);return isNaN(d)?v:d.toLocaleDateString('en-GB',{{day:'numeric',month:'long',year:'numeric'}});}}function filtered(){{const words=input.value.trim().toLowerCase().split(/\s+/).filter(Boolean);return DATA.filter(x=>!words.length||words.every(w=>(x.title+' '+x.description+' '+x.category+' '+x.slug).toLowerCase().includes(w)));}}function render(reset=false){{if(reset)shown=PAGE;const found=filtered();count.textContent=found.length.toLocaleString('en-GB');results.innerHTML=found.slice(0,shown).map(x=>`<article class="archive-item"><a href="${{x.url}}">${{esc(x.title)}}</a><div class="meta">${{esc(x.category||'News')}}${{x.published_at?' · '+esc(dateLabel(x.published_at)):''}}</div>${{x.description?'<p>'+esc(x.description)+'</p>':''}}</article>`).join('')||'<p>No archived stories match that search.</p>';more.hidden=shown>=found.length;}}input.addEventListener('input',()=>render(true));more.addEventListener('click',()=>{{shown+=PAGE;render();}});render();</script></body></html>'''
def main():
    records=build_index(); INDEX_PATH.write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); page=render(records); ARCHIVE_PATH.write_text(page,encoding='utf-8'); SEARCH_PATH.write_text(page,encoding='utf-8'); print(f'Archive indexed {len(records)} retained article pages.'); return 0
if __name__=='__main__':raise SystemExit(main())
