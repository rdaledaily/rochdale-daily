#!/usr/bin/env python3
"""Generate Rochdale Daily ward pages: councillors, verified portraits, recorded votes and ward news."""
from __future__ import annotations
import html,json,re,unicodedata
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; WARD_MAP_PATH=ROOT/'ward_areas.json'; ARTICLES_PATH=ROOT/'articles.json'; VOTES_PATH=ROOT/'council_votes.json'; PHOTOS_PATH=ROOT/'councillor_photos.json'; CSS_PATH=ROOT/'assets/css/site.css'; OUTPUT_DIR=ROOT/'wards'; SITE='https://rochdaledaily.co.uk'; MAX_STORIES=12
SIDE_LABEL={'for':'Voted for','against':'Voted against','abstain':'Abstained'}; SIDE_CLASS={'for':'dem-vote-for','against':'dem-vote-against','abstain':'dem-vote-abstain'}
def esc(v): return html.escape(str(v or ''),quote=True)
def slugify(v): return re.sub(r'-{2,}','-',re.sub(r'[^a-zA-Z0-9]+','-',unicodedata.normalize('NFKD',str(v)).encode('ascii','ignore').decode()).strip('-').lower())
def read(p,d):
 try:return json.loads(p.read_text(encoding='utf-8'))
 except Exception:return d
def load_css():
 try:return CSS_PATH.read_text(encoding='utf-8')
 except OSError:return ''
def chrome_head(t,d,c,css): return f'''<!DOCTYPE html><html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="index,follow"><title>{esc(t)} | Rochdale Daily</title><meta name="description" content="{esc(d)}"><link rel="canonical" href="{esc(c)}"><style>{css}\n.ward-wrap{{max-width:1000px;margin:0 auto;padding:28px 20px 60px}}.ward-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}}.ward-card{{border:1px solid #ddd;padding:15px;background:#fff}}.ward-card h3{{font-size:18px;margin:10px 0 6px}}.ward-meta{{font-size:12px;color:#667;text-transform:uppercase}}.ward-h2{{border-top:3px solid #111;padding-top:8px;margin-top:34px}}.cllr-photo{{width:100%;aspect-ratio:4/3;object-fit:cover;background:#eceff1;display:block}}.cllr-placeholder{{width:100%;aspect-ratio:4/3;background:#eceff1;display:grid;place-items:center;font-size:46px;font-weight:800;color:#89939d}}.dem-vote-side{{font-weight:800}}.dem-vote-for{{color:#18733a}}.dem-vote-against{{color:#a51d25}}.dem-vote-abstain{{color:#695b00}}</style></head><body><header class="masthead"><div class="wrap masthead-row"><a class="brand" href="/index.html">ROCHDALE DAILY</a> <a href="/wards/">All wards</a></div></header><main class="ward-wrap">'''
FOOT='</main><footer style="background:#111;color:#ccc;padding:26px 20px"><strong>Rochdale Daily</strong> — independent local news for the Rochdale borough.</footer></body></html>'
def story_card(a): return f'<article class="ward-card"><div class="ward-meta">{esc(str(a.get("area") or "").title())}</div><h3><a href="/articles/{esc(a.get("slug"))}.html">{esc(a.get("title"))}</a></h3><p>{esc((a.get("excerpt") or "")[:150])}</p></article>'
def councillor_card(p,photos):
 photo=photos.get(str(p.get('name') or ''),{}) if isinstance(photos,dict) else {}; image=photo.get('image_url'); profile=photo.get('profile_url'); initials=''.join(x[0] for x in str(p.get('name') or '').split()[:2]).upper(); portrait=f'<img class="cllr-photo" src="{esc(image)}" alt="{esc(p.get("name"))}">' if image else f'<div class="cllr-placeholder" title="Portrait awaiting verification">{esc(initials)}</div>'; portrait=f'<a href="{esc(profile)}" target="_blank" rel="noopener">{portrait}</a>' if profile and image else portrait
 votes=''
 for v in p.get('votes') or []:
  side=v.get('side') if v.get('side') in SIDE_LABEL else 'abstain'; title=esc(v.get('title')); link=f'<a href="{esc(v.get("url"))}" target="_blank" rel="noopener">{title}</a>' if v.get('url') else title; votes+=f'<li style="padding:6px 0;border-top:1px solid #eee"><span class="dem-vote-side {SIDE_CLASS[side]}">{SIDE_LABEL[side]}</span> {link}</li>'
 body=f'<p><b>Recorded votes</b></p><ul style="list-style:none;padding:0">{votes}</ul>' if votes else '<p>No recorded vote has named this councillor yet.</p>'
 return f'<article class="ward-card">{portrait}<h3>{esc(p.get("name"))}</h3><div class="ward-meta">{esc(p.get("party"))}</div>{body}</article>'
def main():
 wards=read(WARD_MAP_PATH,{}).get('wards',{}); raw=read(ARTICLES_PATH,[]); articles=raw if isinstance(raw,list) else raw.get('articles',[]); votes=read(VOTES_PATH,{}); photos=read(PHOTOS_PATH,{}); css=load_css(); OUTPUT_DIR.mkdir(parents=True,exist_ok=True)
 for ward,cfg in wards.items():
  areas={a.lower() for a in cfg.get('areas',[])}; stories=[a for a in articles if str(a.get('area') or '').lower() in areas][:MAX_STORIES]; people=(votes.get('wards') or {}).get(ward,[]); note=f'<p>{esc(cfg.get("note"))}</p>' if cfg.get('note') else ''; page=chrome_head(f'{ward} news and councillors',f'News from {ward} and what its councillors have voted on.',f'{SITE}/wards/{slugify(ward)}.html',css)+f'<span>WARD</span><h1>{esc(ward)}</h1>{note}<h2 class="ward-h2">Your councillors</h2><div class="ward-grid">{"".join(councillor_card(p,photos) for p in people)}</div><p>Only votes taken by name are listed. Rochdale Daily never infers an individual vote where the minutes do not name the councillor.</p><h2 class="ward-h2">Ward news</h2><div class="ward-grid">{"".join(story_card(a) for a in stories) or "<p>No stories filed for this ward yet.</p>"}</div>'+FOOT; (OUTPUT_DIR/f'{slugify(ward)}.html').write_text(page,encoding='utf-8')
 rows=''.join(f'<p><a href="/wards/{slugify(w)}.html">{esc(w)}</a></p>' for w in sorted(wards)); (OUTPUT_DIR/'index.html').write_text(chrome_head('News by ward','Every Rochdale borough ward.',f'{SITE}/wards/',css)+'<h1>News by ward</h1>'+rows+FOOT,encoding='utf-8'); print(f'Generated {len(wards)} ward pages with portrait support.'); return 0
if __name__=='__main__': raise SystemExit(main())
