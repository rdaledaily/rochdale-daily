"""MEN MyRochdale newsletter lane: every story it lists is covered.

Run: PYTHONPATH=scraper python scraper/test_men_newsletter.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

import men_newsletter as mn  # noqa: E402

NOW = datetime(2026, 11, 3, 9, 0, tzinfo=timezone.utc)
FAILURES: list[str] = []


def check(condition: bool, label: str) -> None:
    print(('PASS ' if condition else 'FAIL ') + label)
    if not condition:
        FAILURES.append(label)


# --- matching, using real headline/title pairs measured on 3 Nov 2026 ------
TRUE_PAIRS = [
    ("Rochdale council deputy leader detained in Pakistan for 'short period'",
     'Rochdale council deputy leader detained briefly in Pakistan during civic visit - Manchester Evening News'),
    ('The secret safety battle over Rochdale’s Seven Sisters',
     "Residents face uncertainty as Rochdale's Seven Sisters tower blocks undergo safety review"),
    ('Urgent appeal as man, 22, goes missing in Rochdale',
     'Police appeal to find missing 22-year-old Sean in Rochdale'),
    ('Rochdale residents return to homes after car smashes into building',
     'Rochdale residents return home after gas leak caused by car crash'),
]
FALSE_PAIRS = [
    # Different missing person: the number veto.
    ('Urgent appeal as man, 22, goes missing in Rochdale',
     'URGENT: Police appeal to find missing 10-year-old Rayah in Rochdale'),
    # Only two shared words: not enough evidence.
    ('Homes at new Rochdale town centre housing complex will be affordable',
     'Trub Farm’s 158 affordable homes could offer Castleton both'),
    # A teaser with nothing in common.
    ('As she waited to learn her fate, her career was already gone',
     'Banned driver led police on high-speed chase through the streets of Rochdale'),
    # Shared place names are not evidence.
    ('The multi-billion plan to transform Rochdale',
     'Rochdale town centre: Greater Manchester borough news'),
]
for headline, title in TRUE_PAIRS:
    check(mn.is_match(headline, title), f'matches: {headline[:50]}')
for headline, title in FALSE_PAIRS:
    check(not mn.is_match(headline, title), f'rejects: {headline[:40]} vs {title[:30]}')

check(mn.clean_title('Some headline - Manchester Evening News') == 'Some headline', 'strips the MEN suffix')
check('rochdale' not in mn.headline_terms('Rochdale homes'), 'place names are not distinctive terms')
check(mn.headline_terms('Homes') == ['home'], 'plural folded')

urls = mn.search_urls('Banned driver led police on high-speed chase through the streets of Rochdale')
check([kind for kind, _ in urls] == ['exact', 'keywords'], 'exact search first, then keywords')
check(all('site%3Amanchestereveningnews.co.uk' in url for _, url in urls), 'both searches are restricted to the MEN')
check(all('when%3A7d' in url for _, url in urls), 'both searches are limited to the window')

# --- loading the leads file -------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    leads = Path(tmp) / 'leads.json'
    leads.write_text(json.dumps({'issues': [
        {'received_at': '2026-10-20T08:00:00Z', 'headlines': ['Too old to still be owed by now']},
        {'received_at': '2026-11-02T08:04:39Z', 'headlines': ['The multi-billion plan to transform Rochdale', 'short']},
        {'received_at': '2026-11-03T08:03:51Z', 'headlines': ['The multi-billion plan to transform Rochdale',
                                                              'Banned driver led police on high-speed chase']},
    ]}), encoding='utf-8')
    stories = mn.load_stories(NOW, leads)
    check([s['headline'] for s in stories] == ['The multi-billion plan to transform Rochdale',
                                                 'Banned driver led police on high-speed chase'],
          'window, minimum length and de-duplication applied')
    check(stories[0]['received_at'].startswith('2026-11-02'), 'a repeated story keeps its first email date')

    # --- the coverage ledger -------------------------------------------------
    ledger_path = Path(tmp) / 'coverage.json'
    ledger = mn.CoverageLedger(ledger_path)
    row = ledger.record(stories[0])
    check(ledger.needs_search(row, NOW), 'a new story is searched')
    ledger.set(row, 'not_found', NOW, reason='no match', last_searched_at=NOW.isoformat())
    check(not ledger.needs_search(row, NOW + timedelta(minutes=30)), 'not searched again within the interval')
    check(ledger.needs_search(row, NOW + timedelta(hours=3)), 'searched again after the interval')
    second = ledger.record(stories[1])
    ledger.set(second, 'published', NOW, article_slug='banned-driver-chase')
    ledger.save(NOW)
    reloaded = mn.CoverageLedger(ledger_path)
    summary = reloaded.summary({mn.story_key(s['headline']) for s in stories})
    check(summary['stories_in_window'] == 2 and summary['covered'] == 1 and summary['outstanding'] == 1,
          'summary counts covered and outstanding')
    check(summary['outstanding_stories'][0]['status'] == 'not_found', 'outstanding stories carry their status')
    check(not reloaded.needs_search(reloaded.record(stories[1]), NOW + timedelta(days=1)), 'a published story is never searched again')


# --- the scraper lane, with Google News stubbed ------------------------------
import scraper as core  # noqa: E402


def entry(title: str, link: str, published: datetime, href: str = 'https://www.manchestereveningnews.co.uk') -> SimpleNamespace:
    return SimpleNamespace(title=title, link=link, summary='', published_parsed=published.timetuple(),
                           published=published.strftime('%a, %d %b %Y %H:%M:%S GMT'),
                           source={'href': href, 'title': 'Manchester Evening News'})


with tempfile.TemporaryDirectory() as tmp:
    leads = Path(tmp) / 'leads.json'
    leads.write_text(json.dumps({'issues': [{'received_at': '2026-11-03T08:03:51Z', 'headlines': [
        'Banned driver led police on high-speed chase through the streets of Rochdale',
        'As she waited to learn her fate, her career was already gone',
        'Storm Austen latest as Met Office says when rain will batter Greater Manchester',
    ]}]}), encoding='utf-8')
    mn.LEADS_PATH = leads
    mn.COVERAGE_PATH = Path(tmp) / 'coverage.json'
    mn.CoverageLedger.__init__.__defaults__ = (mn.COVERAGE_PATH,)
    original_load = mn.load_stories
    mn.load_stories = lambda now=None, path=leads: original_load(now, path)

    yesterday = NOW - timedelta(hours=20)
    calls: list[str] = []

    def fake_parse(url: str):
        calls.append(url)
        if 'Banned' in url or 'banned' in url:
            return SimpleNamespace(entries=[
                entry('Rochdale crash victims named', 'https://www.manchestereveningnews.co.uk/news/a-1', yesterday),
                entry('Banned driver led police on chase through Rochdale streets - Manchester Evening News',
                      'https://www.manchestereveningnews.co.uk/news/greater-manchester-news/banned-driver-chase-2', yesterday),
            ])
        if 'Storm' in url or 'storm' in url:
            # A Greater Manchester-wide story: no locality filter applies to it.
            return SimpleNamespace(entries=[entry('Storm Austen: Met Office says when rain will batter Greater Manchester',
                                                  'https://www.manchestereveningnews.co.uk/news/storm-austen-3', yesterday)])
        return SimpleNamespace(entries=[entry('Unrelated court report from Bolton', 'https://www.manchestereveningnews.co.uk/news/x', yesterday)])

    found = core.collect_men_newsletter_candidates(now=NOW, parse=fake_parse, sleep=lambda _s: None)
    titles = {c.newsletter_headline: c for c in found}
    check(len(found) == 2, f'two of three stories resolve (got {len(found)})')
    driver = titles.get('Banned driver led police on high-speed chase through the streets of Rochdale')
    check(driver is not None and driver.source_url.endswith('banned-driver-chase-2'), 'the matching article wins, not the first result')
    check(driver is not None and driver.must_cover_source == mn.SOURCE_LABEL, 'resolved stories are must-cover')
    check('Storm Austen latest as Met Office says when rain will batter Greater Manchester' in titles,
          'a Greater Manchester-wide story is kept (no locality filter)')
    ledger = core.MEN_NEWSLETTER_LEDGER
    teaser = ledger.record({'headline': 'As she waited to learn her fate, her career was already gone', 'received_at': ''})
    check(teaser['status'] == 'not_found' and teaser['searches'] == 1, 'an unmatched teaser is reported not_found')
    check(sum('fate' in c or 'Fate' in c for c in calls) == 2, 'an unmatched story tries both searches')

    # Selection: must-cover stories ride outside the cap.
    others = [core.Candidate('Src', f'https://example.org/{i}', f'Story {i}', '', NOW.isoformat(), 'rochdale', 'news') for i in range(5)]

    def capped_select(items, limit, **_kw):
        return list(items)[:limit], {'limit': limit}

    selected, diag = core.select_with_must_cover(others, found, capped_select, limit=2)
    check(len(selected) == 4 and selected[:2] == found, 'must-cover first and outside the cap of 2')
    check(diag['must_cover_selected'] == 2, 'selection diagnostics count must-cover stories')

    # Outcomes reach the ledger and the summary.
    core.record_men_newsletter_outcome(driver, 'published', '', 'banned-driver-chase')
    core.MEN_NEWSLETTER_LEDGER.save(NOW)
    summary = core.MEN_NEWSLETTER_LEDGER.summary(core.MEN_NEWSLETTER_ACTIVE_KEYS)
    check(summary['covered'] == 1 and summary['by_status'].get('found') == 1 and summary['by_status'].get('not_found') == 1,
          f"ledger summary reflects outcomes ({summary['by_status']})")

# Locality: a published must-cover story survives the retention pass.
article = {'title': 'Storm Austen: when rain will batter Greater Manchester', 'excerpt': 'Met Office warning for the region.',
           'content_html': '<p>Bolton and Oldham will see heavy rain.</p>', 'source_name': 'Manchester Evening News',
           'source_url': 'https://www.manchestereveningnews.co.uk/news/storm-austen-3'}
check(not core.article_passes_locality(dict(article)), 'without the mark, a GM-wide story fails locality')
check(core.article_passes_locality(dict(article, must_cover_source=mn.SOURCE_LABEL)), 'with the mark it is kept')

# The model's "not about the borough" veto is waived only while a must-cover story is written.
import editorial_upgrade  # noqa: E402

draft = {'content_class': 'news_report', 'is_about_rochdale_borough': False}
check(bool(editorial_upgrade.gate_rejection(draft)), 'locality veto applies normally')
editorial_upgrade.LOCALITY_VETO_WAIVER.active = True
try:
    check(editorial_upgrade.gate_rejection(draft) == [], 'locality veto waived for must-cover')
    check(bool(editorial_upgrade.gate_rejection({'content_class': 'advert_or_listing'})), 'the news-not-advert veto still applies')
finally:
    editorial_upgrade.LOCALITY_VETO_WAIVER.active = False

print()
if FAILURES:
    print(f'{len(FAILURES)} FAILED')
    sys.exit(1)
print('all MEN newsletter checks passed')
