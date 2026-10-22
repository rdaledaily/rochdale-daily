"""Check the rendered archive against Google Search Central's article guidance."""
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

def audit(root, rows):
    findings=[]; titles=Counter(); indexed=0
    for row in rows:
        path=root/'articles'/(row['slug']+'.html')
        text=path.read_text(encoding='utf-8')
        head=BeautifulSoup(text.split('</head>',1)[0],'lxml')
        issues=[]
        if not row['indexable']:continue
        indexed+=1
        title=head.title.get_text(' ',strip=True) if head.title else ''
        if not title:issues.append('missing-title')
        titles[title]+=1
        description=head.select_one('meta[name="description"]')
        if not description or not description.get('content','').strip():issues.append('missing-description')
        if len(re.findall(r'<h1\b',text,re.I))!=1:issues.append('expected-one-main-heading')
        canonical=head.select_one('link[rel="canonical"]')
        if not canonical:issues.append('missing-canonical')
        news=[]
        def visit(value):
            if isinstance(value,list):
                for child in value:visit(child)
            if isinstance(value,dict):
                kind=value.get('@type')
                if kind=='NewsArticle' or (isinstance(kind,list) and 'NewsArticle' in kind):news.append(value)
                for child in value.values():
                    if isinstance(child,(dict,list)):visit(child)
        for script in head.select('script[type="application/ld+json"]'):
            try:visit(json.loads(script.string or script.get_text()))
            except ValueError:issues.append('invalid-jsonld')
        if not news:issues.append('missing-newsarticle-schema')
        for article in news:
            for field in ('headline','image','author','publisher','datePublished'):
                if not article.get(field):issues.append('schema-missing-'+field)
            if article.get('headline')!=row['title']:issues.append('schema-headline-mismatch')
            for field in ('datePublished','dateModified'):
                value=article.get(field)
                if not value:continue
                try:
                    stamp=datetime.fromisoformat(str(value).replace('Z','+00:00'))
                    if stamp.tzinfo is None:issues.append('schema-date-missing-timezone')
                    elif stamp>datetime.now(timezone.utc):issues.append('schema-date-in-future')
                except ValueError:issues.append('schema-invalid-'+field)
        # Inspect only the story hero; navigation icons can have empty alt.
        hero=re.search(r'<figure\b[^>]*class="article-hero-image"[^>]*>.*?</figure>',text,re.S)
        if not hero:issues.append('missing-story-image')
        else:
            image=BeautifulSoup(hero.group(),'html.parser').find('img')
            if not image or not image.get('alt','').strip():issues.append('missing-image-alt')
            if image:
                url=image.get('src','')
                if not url.startswith('http') and not (root/url.lstrip('/')).is_file():issues.append('missing-image-file')
        if issues:findings.append({'slug':row['slug'],'issues':sorted(set(issues))})
    duplicates=[{'title':title,'pages':count} for title,count in titles.items() if count>1]
    return {'indexable_articles_checked':indexed,'pages_with_issues':len(findings),'duplicate_title_groups':duplicates,'findings':findings,
            'guidance':['https://developers.google.com/search/docs/appearance/title-link','https://developers.google.com/search/docs/appearance/structured-data/article','https://developers.google.com/search/docs/crawling-indexing/sitemaps/news-sitemap'],
            'policy':'Descriptive titles and summaries, consistent schema, relevant accessible images, original publication dates, indexable canonical URLs and relevant article links. No ranking guarantee or keyword stuffing.'}
