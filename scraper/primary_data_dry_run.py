#!/usr/bin/env python3
"""PROBE BRANCH ONLY - never merge to main.

Measures every North West and Lancashire news outlet as a candidate RSS source
for Rochdale Daily, from a GitHub runner (the same network the newsroom runs
on). For each outlet: which feed URL works, HTTP status, item count, items per
day, robots verdict, and - the number that matters - how many current items
pass the newsroom's OWN gates (is_fresh, should_drop, source_text_is_local)
exactly as collect_rss_candidates() would apply them to an untrusted feed.
Publishes nothing and writes no state.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.stderr = sys.stdout  # the workflow only tees stdout
_pip = subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', '--no-cache-dir', '-r',
                       str(Path(__file__).resolve().parents[1] / 'requirements.txt')],
                      capture_output=True, text=True)
print('pip exit', _pip.returncode, _pip.stderr[-800:])

import feedparser  # noqa: E402
import requests  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import scraper  # noqa: E402
    import robots_rules  # noqa: E402
except Exception:  # noqa: BLE001
    import traceback
    traceback.print_exc(file=sys.stdout)
    raise

# The production collector's feed User-Agent (collect_rss_candidates).
FEED_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
           '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')
BOT_UA = 'RochdaleDailyBot/1.0'
OUT = Path('dry_run_samples')
OUT.mkdir(exist_ok=True)
NOW = datetime.now(timezone.utc)

NQ = '/news/rss/'  # Newsquest pattern
NW = '/rss'        # National World pattern
RE = '/?service=rss'  # Reach pattern

# (name, region, homepage, [candidate feed paths or absolute URLs])
OUTLETS = [
    # Greater Manchester
    ('Manchester Evening News — news', 'Greater Manchester', 'https://www.manchestereveningnews.co.uk', ['/news/?service=rss', '/news/greater-manchester-news/?service=rss']),
    ('Manchester Evening News — Rossendale', 'Lancashire', 'https://www.manchestereveningnews.co.uk', ['/all-about/rossendale?service=rss']),
    ('Manchester Evening News — Whitworth', 'Lancashire', 'https://www.manchestereveningnews.co.uk', ['/all-about/whitworth?service=rss']),
    ('Manchester Evening News — Oldham', 'Greater Manchester', 'https://www.manchestereveningnews.co.uk', ['/all-about/oldham?service=rss']),
    ('Manchester Evening News — Bury', 'Greater Manchester', 'https://www.manchestereveningnews.co.uk', ['/all-about/bury?service=rss']),
    ('The Bolton News', 'Greater Manchester', 'https://www.theboltonnews.co.uk', [NQ]),
    ('Bury Times', 'Greater Manchester', 'https://www.burytimes.co.uk', [NQ]),
    ('The Oldham Times', 'Greater Manchester', 'https://www.theoldhamtimes.co.uk', [NQ]),
    ('Leigh Journal', 'Greater Manchester', 'https://www.leighjournal.co.uk', [NQ]),
    ('Wigan Today', 'Greater Manchester', 'https://www.wigantoday.net', [NW]),
    ('Manchester World', 'Greater Manchester', 'https://www.manchesterworld.uk', [NW]),
    ('The Mill', 'Greater Manchester', 'https://manchestermill.co.uk', ['/feed']),
    ('The Meteor', 'Greater Manchester', 'https://themeteor.org', ['/feed/']),
    ('Salford Star', 'Greater Manchester', 'https://www.salfordstar.com', ['/feed', '/rss']),
    ('Quest Media Network (Oldham/Tameside Reporter)', 'Greater Manchester', 'https://questmedianetwork.co.uk', ['/rss', '/feed']),
    ('Oldham Chronicle', 'Greater Manchester', 'https://www.oldham-chronicle.co.uk', ['/feed', '/rss']),
    ('Saddleworth Independent', 'Greater Manchester', 'https://saddleworthindependent.co.uk', ['/feed/']),
    ('The Manc', 'Greater Manchester', 'https://themanc.com', ['/feed/']),
    ('I Love Manchester', 'Greater Manchester', 'https://ilovemanchester.com', ['/feed']),
    ('Manchester Wire', 'Greater Manchester', 'https://www.manchesterwire.co.uk', ['/feed']),
    ('Stockport Nub News', 'Greater Manchester', 'https://stockport.nub.news', ['/rss', '/news/rss']),
    ('Place North West', 'North West', 'https://www.placenorthwest.co.uk', ['/feed/']),
    ('Prolific North', 'North West', 'https://www.prolificnorth.co.uk', ['/feed/']),
    ('TheBusinessDesk North West', 'North West', 'https://www.thebusinessdesk.com', ['/northwest/rss', '/rss']),
    ('Bdaily', 'North West', 'https://bdaily.co.uk', ['/feed', '/rss']),
    ('BBC North West Tonight / ITV Granada (ITV)', 'North West', 'https://www.itv.com/news/granada', []),
    # Lancashire
    ('BBC Lancashire', 'Lancashire', 'https://www.bbc.co.uk/news/england/lancashire', ['https://feeds.bbci.co.uk/news/england/lancashire/rss.xml']),
    ('Lancashire Telegraph', 'Lancashire', 'https://www.lancashiretelegraph.co.uk', [NQ]),
    ('Asian Image', 'Lancashire', 'https://www.asianimage.co.uk', [NQ]),
    ('Lancashire Post (LEP)', 'Lancashire', 'https://www.lep.co.uk', [NW]),
    ('Blackpool Gazette', 'Lancashire', 'https://www.blackpoolgazette.co.uk', [NW]),
    ('Lancaster Guardian', 'Lancashire', 'https://www.lancasterguardian.co.uk', [NW]),
    ('Burnley Express', 'Lancashire', 'https://www.burnleyexpress.net', [NW]),
    ('Pendle Today', 'Lancashire', 'https://www.pendletoday.co.uk', [NW]),
    ('Clitheroe Advertiser', 'Lancashire', 'https://www.clitheroeadvertiser.co.uk', [NW]),
    ('Chorley Guardian', 'Lancashire', 'https://www.chorley-guardian.co.uk', [NW]),
    ('Leyland Guardian', 'Lancashire', 'https://www.leylandguardian.co.uk', [NW]),
    ('Garstang Courier', 'Lancashire', 'https://www.garstangcourier.co.uk', [NW]),
    ('Fleetwood Today', 'Lancashire', 'https://www.fleetwoodtoday.co.uk', [NW]),
    ('Lancs Live', 'Lancashire', 'https://www.lancs.live', [RE, '/news/?service=rss']),
    ('Blog Preston', 'Lancashire', 'https://www.blogpreston.co.uk', ['/feed/']),
    ('Lancashire Business View', 'Lancashire', 'https://www.lancashirebusinessview.co.uk', ['/feed', '/rss']),
    ('Central Radio', 'Lancashire', 'https://www.central.radio', ['/feed/', '/rss']),
    ('Rossendale Radio', 'Lancashire', 'https://www.rossendaleradio.co.uk', ['/feed/']),
    ('Bacup Times', 'Lancashire', 'https://www.bacuptimes.co.uk', ['/feed/']),
    # Merseyside
    ('BBC Merseyside', 'Merseyside', 'https://www.bbc.co.uk/news/england/merseyside', ['https://feeds.bbci.co.uk/news/england/merseyside/rss.xml']),
    ('Liverpool Echo', 'Merseyside', 'https://www.liverpoolecho.co.uk', [RE, '/news/?service=rss']),
    ('Liverpool World', 'Merseyside', 'https://www.liverpoolworld.uk', [NW]),
    ('The Post (Liverpool)', 'Merseyside', 'https://www.livpost.co.uk', ['/feed']),
    ('St Helens Star', 'Merseyside', 'https://www.sthelensstar.co.uk', [NQ]),
    ('Wirral Globe', 'Merseyside', 'https://www.wirralglobe.co.uk', [NQ]),
    # Cheshire
    ('Cheshire Live', 'Cheshire', 'https://www.cheshire-live.co.uk', [RE, '/news/?service=rss']),
    ('Warrington Guardian', 'Cheshire', 'https://www.warringtonguardian.co.uk', [NQ]),
    ('Knutsford Guardian', 'Cheshire', 'https://www.knutsfordguardian.co.uk', [NQ]),
    ('Northwich Guardian', 'Cheshire', 'https://www.northwichguardian.co.uk', [NQ]),
    ('Runcorn and Widnes World', 'Cheshire', 'https://www.runcornandwidnesworld.co.uk', [NQ]),
    ('Macclesfield Nub News', 'Cheshire', 'https://macclesfield.nub.news', ['/rss', '/news/rss']),
    # Cumbria
    ('BBC Cumbria', 'Cumbria', 'https://www.bbc.co.uk/news/england/cumbria', ['https://feeds.bbci.co.uk/news/england/cumbria/rss.xml']),
    ('News & Star', 'Cumbria', 'https://www.newsandstar.co.uk', [NQ]),
    ('Times & Star', 'Cumbria', 'https://www.timesandstar.co.uk', [NQ]),
    ('Whitehaven News', 'Cumbria', 'https://www.whitehavennews.co.uk', [NQ]),
    ('Westmorland Gazette', 'Cumbria', 'https://www.thewestmorlandgazette.co.uk', [NQ]),
    ('North West Evening Mail', 'Cumbria', 'https://www.nwemail.co.uk', [NQ]),
    ('Cumbria Crack', 'Cumbria', 'https://www.cumbriacrack.com', ['/feed/']),
]


def get(url: str, ua: str = FEED_UA, timeout: int = 20):
    try:
        r = requests.get(url, headers={'User-Agent': ua, 'Accept': 'application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5'}, timeout=timeout, allow_redirects=True)
        return r.status_code, r.headers.get('content-type', ''), r.content, r.url
    except Exception as exc:  # noqa: BLE001
        return None, f'{type(exc).__name__}: {exc}'[:120], b'', url


def robots(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    status, _, body, _ = get(f'{parts.scheme}://{parts.netloc}/robots.txt', BOT_UA, 15)
    if status in (404, 410):
        return 'no-robots-file'
    if status != 200:
        return f'robots-http-{status}'
    try:
        parser = robots_rules.parse(body.decode('utf-8', 'replace'))
        ok_bot = parser.can_fetch(BOT_UA, url)
        ok_any = parser.can_fetch('*', url)
        return 'allowed' if (ok_bot and ok_any) else f'DISALLOWED(bot={ok_bot},*={ok_any})'
    except Exception as exc:  # noqa: BLE001
        return f'robots-parse-error {exc}'[:60]


def discover(home: str) -> list[str]:
    status, _, body, final = get(home)
    if status != 200:
        return []
    html = body.decode('utf-8', 'replace')
    found = re.findall(r'<link[^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]*>', html, re.I)
    urls = []
    for tag in found:
        m = re.search(r'href=["\']([^"\']+)', tag)
        if m:
            urls.append(urllib.parse.urljoin(final, m.group(1)))
    return urls[:4]


def measure_feed(name: str, url: str) -> dict:
    status, ctype, body, final = get(url)
    res = {'url': url, 'final_url': final, 'http': status, 'content_type': ctype}
    if status != 200 or not body:
        return res
    feed = feedparser.parse(body)
    entries = list(feed.entries)
    res['entries'] = len(entries)
    res['bozo'] = bool(getattr(feed, 'bozo', False)) and not entries
    dates = [scraper.entry_datetime(e) for e in entries]
    dates = [d for d in dates if d]
    if dates:
        newest, oldest = max(dates), min(dates)
        span_days = max((newest - oldest).total_seconds() / 86400, 0.25)
        res['newest'] = newest.isoformat()
        res['per_day'] = round(len(dates) / span_days, 1)
    fresh, local = 0, []
    for e in entries:
        title = scraper.strip_markdown(getattr(e, 'title', ''))
        summ_html = str(getattr(e, 'summary', '') or getattr(e, 'description', '') or '')
        try:
            from bs4 import BeautifulSoup
            summ = scraper.strip_markdown(BeautifulSoup(summ_html, 'lxml').get_text(' ', strip=True))
        except Exception:  # noqa: BLE001
            summ = summ_html
        link = scraper.canonicalise_url(str(getattr(e, 'link', '') or ''))
        pub = scraper.entry_datetime(e)
        if not (link and title and scraper.is_fresh(pub)):
            continue
        fresh += 1
        text = f'{title} {summ}'
        if scraper.should_drop(text, link):
            continue
        if not scraper.source_text_is_local(text, name, link, False):
            continue
        area = scraper.source_text_area(text, 'rochdale', name, link, False)
        local.append({'title': title, 'area': area, 'published': pub.isoformat() if pub else '', 'url': link})
    res['fresh'] = fresh
    res['rochdale_pass'] = len(local)
    res['rochdale_items'] = local
    return res


def probe(outlet) -> dict:
    name, region, home, cands = outlet
    urls = [c if c.startswith('http') else home.rstrip('/') + c for c in cands]
    tried = []
    best = None
    for u in urls:
        r = measure_feed(name, u)
        tried.append({k: r.get(k) for k in ('url', 'http', 'content_type', 'entries')})
        if r.get('entries'):
            best = r
            break
    if best is None:
        for u in discover(home):
            if u in urls:
                continue
            r = measure_feed(name, u)
            tried.append({k: r.get(k) for k in ('url', 'http', 'content_type', 'entries')})
            if r.get('entries'):
                best = r
                best['discovered'] = True
                break
    out = {'name': name, 'region': region, 'homepage': home, 'tried': tried}
    if best:
        out.update(best)
        out['robots'] = robots(best['url'])
    return out


def main() -> None:
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(probe, OUTLETS))
    (OUT / 'nw_outlets.json').write_text(json.dumps(results, indent=2, default=str))
    print(f'North West / Lancashire outlet probe — {NOW:%Y-%m-%d %H:%M} UTC — {len(results)} outlets')
    print('Gate = the newsroom\'s own is_fresh + should_drop + source_text_is_local (untrusted feed)\n')
    working = [r for r in results if r.get('entries')]
    for r in sorted(results, key=lambda x: (-(x.get('rochdale_pass') or -1), x['name'])):
        if r.get('entries'):
            print(f"OK   {r['name']} [{r['region']}] {r['url']}")
            print(f"     items={r['entries']} per_day≈{r.get('per_day')} fresh={r.get('fresh')} ROCHDALE_PASS={r.get('rochdale_pass')} robots={r.get('robots')} newest={r.get('newest','')[:16]}")
            for it in r.get('rochdale_items', [])[:12]:
                print(f"       + [{it['area']}] {it['title'][:110]}")
        else:
            print(f"FAIL {r['name']} [{r['region']}]")
            for t in r['tried']:
                print(f"       {t['http']} {str(t['content_type'])[:50]} {t['url']}")
    total = sum(r.get('rochdale_pass') or 0 for r in working)
    print(f"\nWorking feeds: {len(working)}/{len(results)} · Rochdale items passing gates right now: {total}")


if __name__ == '__main__':
    try:
        main()
    except Exception:  # noqa: BLE001
        import traceback
        traceback.print_exc(file=sys.stdout)
        raise
