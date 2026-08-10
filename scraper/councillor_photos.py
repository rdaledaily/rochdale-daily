#!/usr/bin/env python3
"""Find verified portraits for every Rochdale councillor.

Discovery is by full name + Rochdale. We prefer Open Council Network and official
Rochdale/GMCA profiles. A candidate page must itself contain the councillor's
full name and Rochdale before its og:image/profile image is accepted. Ambiguous
or generic images are refused. Existing verified images are retained.
"""
from __future__ import annotations
import html,json,re
from pathlib import Path
from urllib.parse import quote_plus,urlparse,urljoin
import feedparser,requests
from bs4 import BeautifulSoup
ROOT=Path(__file__).resolve().parents[1]; ROSTER=ROOT/'council_roster.json'; OUT=ROOT/'councillor_photos.json'
APPROVED=('opencouncil.network','rochdale.gov.uk','democracy.rochdale.gov.uk','rochdale.moderngov.co.uk','democracy.greatermanchester-ca.gov.uk','yourtrustrochdale.co.uk')
UA='RochdaleDaily-councillor-portraits/1.0 (news@rochdaledaily.co.uk)'
def load(p,d):
 try:return json.loads(p.read_text(encoding='utf-8'))
 except Exception:return d
def norm(s):return re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',str(s or '')))).strip()
def approved(url):
 h=(urlparse(url).hostname or '').lower(); return any(h==d or h.endswith('.'+d) for d in APPROVED)
def extract(page,name):
 try:r=requests.get(page,headers={'User-Agent':UA},timeout=20); r.raise_for_status()
 except Exception:return None
 soup=BeautifulSoup(r.text,'html.parser'); text=norm(soup.get_text(' ',strip=True)).lower()
 if name.lower() not in text or 'rochdale' not in text:return None
 candidates=[]
 for attrs in ({'property':'og:image'},{'name':'twitter:image'}):
  tag=soup.find('meta',attrs=attrs)
  if tag and tag.get('content'):candidates.append(urljoin(r.url,tag['content']))
 for img in soup.find_all('img'):
  alt=norm(img.get('alt')).lower(); src=img.get('src') or img.get('data-src')
  if src and (name.lower() in alt or ('profile' in alt and 'councillor' in alt)):candidates.append(urljoin(r.url,src))
 for image in candidates:
  low=image.lower()
  if any(x in low for x in ('logo','icon','favicon','sprite')):continue
  try:
   ir=requests.get(image,headers={'User-Agent':UA},timeout=15,stream=True)
   if ir.status_code==200 and str(ir.headers.get('content-type','')).startswith('image/'):
    return {'image_url':image,'profile_url':r.url,'image_source':urlparse(r.url).hostname,'verified_name_match':True}
  except Exception:pass
 return None
def main():
 raw=load(ROSTER,{}); people=raw.get('councillors',[]) if isinstance(raw,dict) else raw; out=load(OUT,{})
 if not isinstance(out,dict):out={}
 for p in people:
  name=str(p.get('name') or '').strip(); ward=str(p.get('ward') or '').strip()
  if not name:continue
  if out.get(name,{}).get('image_url'):continue
  queries=[f'site:opencouncil.network/people "{name}" Rochdale',f'"{name}" Rochdale councillor "Profile image"',f'"{name}" Rochdale councillor']
  found=None
  for query in queries:
   feed=feedparser.parse(f'https://www.bing.com/search?format=rss&q={quote_plus(query)}',request_headers={'User-Agent':UA})
   for e in feed.entries:
    link=str(e.get('link') or '').strip(); blob=(norm(e.get('title'))+' '+norm(e.get('summary'))).lower()
    if not link or not approved(link) or name.lower() not in blob or 'rochdale' not in blob:continue
    found=extract(link,name)
    if found:break
   if found:break
  out.setdefault(name,{}); out[name].update(found or {'verified_name_match':False,'ward':ward})
  print(('FOUND ' if found else 'MISS  ')+name)
 OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(f"Verified portraits: {sum(bool(v.get('image_url')) for v in out.values())}/{len(people)}")
 return 0
if __name__=='__main__':raise SystemExit(main())
