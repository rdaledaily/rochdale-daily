"""Prepare source-led follow-up assignments and social drafts; never publish or send."""
from __future__ import annotations
import argparse
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

def clean(value):
    return ' '.join(html.unescape(re.sub('<[^>]+>', ' ', str(value or ''))).split())

def draft(article):
    slug=str(article.get('slug') or '')
    if not re.fullmatch('[a-z0-9-]+',slug): return None
    if str(article.get('status') or 'published')!='published' or article.get('requires_approval') or article.get('paid_submission') or article.get('sponsored'): return None
    title=clean(article.get('title'));summary=clean(article.get('excerpt') or article.get('summary'))
    if not title:return None
    url='https://rochdaledaily.co.uk/articles/'+slug
    return {'title':title,'url':url,'source_url':article.get('source_url') or '',
      'social_draft':'\n\n'.join(part for part in [title,summary,url+'?'+urlencode({'utm_source':'facebook','utm_medium':'social','utm_campaign':'local-reporting'})] if part),
      'review_before_posting':['Confirm the post and opening paragraph answer the same reader question.','Check current dates and practical arrangements against the identified source.','Preserve qualifications, allegations and right of reply. Do not add a teaser claim.'],
      'follow_up_assignment':{'question':'What has changed since this report, and what documented outcome remains outstanding?',
        'actions':['Read the linked source and earlier coverage.','Check the next published decision, deadline or official update.','If a response is needed, prepare a specific question for editorial approval; do not invent or send it automatically.','Update the existing article unless there is a materially separate development.']}}

def build(articles, now):
    output=[]
    for article in articles:
      if not isinstance(article,dict):continue
      try:stamp=datetime.fromisoformat(str(article.get('first_published_at') or article.get('published_at') or '').replace('Z','+00:00'))
      except ValueError:continue
      if stamp.tzinfo is None:stamp=stamp.replace(tzinfo=timezone.utc)
      if not 0<=(now-stamp).total_seconds()<=7*86400:continue
      row=draft(article)
      if row:output.append((stamp,row))
    return {'generated_at':now.isoformat(),'drafts_only':True,'items':[row for _,row in sorted(output,key=lambda pair:pair[0],reverse=True)[:12]]}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--input',default='articles.json');parser.add_argument('--output',default='reports/readership-desk.json');args=parser.parse_args()
    raw=json.loads(Path(args.input).read_text(encoding='utf-8'));articles=raw if isinstance(raw,list) else raw.get('articles',[])
    target=Path(args.output);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(build(articles,datetime.now(timezone.utc)),indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print('Prepared editorial assignments and social drafts; nothing sent.')
if __name__=='__main__':main()
