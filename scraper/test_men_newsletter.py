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

# --- duplicates, real reasons, source-text floor (3 Nov 2026 live run) -------
from selection_policy import is_job_or_career_post  # noqa: E402

def must(headline, title, url='https://www.manchestereveningnews.co.uk/news/x-1', text='y ' * 400, when=NOW):
    return core.Candidate('Manchester Evening News', url, title, text, core.iso_utc(when), 'rochdale', 'news',
                          source_body_excerpt=text, must_cover_source=mn.SOURCE_LABEL, newsletter_headline=headline)

archive = [  # the originals the live run duplicated, with their real titles
    {'slug': 'homes-evacuated-in-rochdale-after-car-crashes-into-house-and-causes-gas-leak', 'published_at': '2026-10-31T18:36:00Z',
     'title': 'Homes evacuated in Rochdale after car crashes into house and causes gas leak'},
    {'slug': 'police-appeal-for-help-in-locating-kibriya-ahmed', 'published_at': '2026-10-29T19:03:00Z',
     'title': 'Police appeal for help in locating Kibriya Ahmed after his children reported missing'},
    {'slug': 'rochdale-council-deputy-leader-detained-briefly-in-pakistan', 'published_at': '2026-10-28T11:03:00Z',
     'title': 'Rochdale council deputy leader detained briefly in Pakistan during civic visit'},
    {'slug': 'ignite-fire-festival-rochdale-town-hall-square-november-20-22', 'published_at': '2026-10-08T20:35:00Z',
     'title': 'Ignite Fire Festival returns to Rochdale Town Hall Square from November 20 to 22'},
    {'slug': 'rochdale-driver-jailed-16-months-dangerous-police-pursuit', 'published_at': '2026-11-02T14:58:00Z',
     'title': 'Rochdale driver jailed for 16 months after dangerous police pursuit'},
]
by_story = {}
cases = [
    ('Homes evacuated after car crashes into house and causes gas leak',
     'Rochdale homes evacuated after car crashes into house and causes a gas leak', '2026-10-31T18:40:00Z', archive[0]['slug']),
    ('Appeal for wanted man with Rochdale links after his children reported missing',
     'Appeal for wanted man with Rochdale and Manchester links after his children reported missing', '2026-10-29T19:03:00Z', archive[1]['slug']),
    ("Rochdale council deputy leader detained in Pakistan for 'short period'",
     "Rochdale council deputy leader Daalat Ali detained in Pakistan for 'short period'", '2026-10-28T11:07:00Z', archive[2]['slug']),
]
for headline, title, when, slug in cases:
    c = must(headline, title, when=datetime.fromisoformat(when.replace('Z', '+00:00')))
    status, _reason, got = core.must_cover_block(c, by_story, archive)
    check(status == 'already_covered' and got == slug, f'duplicate caught: {headline[:45]}')
banned = must('Banned driver led police on high-speed chase through the streets of Rochdale',
              'Banned driver led police on high-speed chase through the streets of Rochdale', when=datetime(2026, 11, 2, 17, 12, tzinfo=timezone.utc))
check(core.must_cover_block(banned, by_story, archive)[0] == '', 'a genuinely new story is still written')
old = dict(archive[1], published_at='2026-09-01T10:00:00Z')
check(core.find_covering_article(cases and must(cases[1][0], cases[1][1], when=datetime(2026, 10, 29, tzinfo=timezone.utc)), [old]) is None,
      'an article outside the 14-day window does not count as cover')

career = must('As she waited to learn her fate, her career was already gone', 'As she waited to learn her fate, her career was already gone')
check(not is_job_or_career_post(career), 'the careers filter no longer removes a must-cover story')
check(is_job_or_career_post({'title': 'Apply now: careers at the council, vacancies open', 'source_url': 'https://x.org/jobs/1'}),
      'the careers filter still works for everything else')
check(core.must_cover_block(career, by_story, archive)[0] == '', 'the career headline is written')

thin = must('Some story with plenty of distinct words', 'Some story with plenty of distinct words',
            url='https://news.google.com/rss/articles/CBMiabc?oc=5', text='short')
status, reason, _ = core.must_cover_block(thin, by_story, archive)
check(status == 'waiting_for_text' and 'characters of source text' in reason, 'an unresolved link with thin text waits, with the real reason')
check(core.must_cover_block(must('Council dashboard', 'Council dashboard', url='https://www.rochdale.gov.uk/bin-collection-day'), by_story, archive)[0]
      in ('rejected', ''), 'service pages are judged by the service-page rule only')

# Same-run twins: an ordinary candidate on the same incident is dropped.
gas = must(cases[0][0], cases[0][1])
other = core.Candidate('Roch Valley Radio', 'https://www.rochvalleyradio.com/news/gas', 'Homes evacuated after car crashes into house causing gas leak',
                       '', NOW.isoformat(), 'rochdale', 'news')
unrelated = core.Candidate('Src', 'https://example.org/z', 'Library opens new reading room for children', '', NOW.isoformat(), 'rochdale', 'news')
picked, _ = core.select_with_must_cover([other, unrelated], [gas], lambda items, limit, **kw: (list(items)[:limit], {}), limit=5)
check(other not in picked and unrelated in picked, 'another outlet\'s report of the same incident is not written alongside')

# Reconciliation: the ledger never points at a removed article.
with tempfile.TemporaryDirectory() as tmp:
    core.MEN_NEWSLETTER_LEDGER = mn.CoverageLedger(Path(tmp) / 'c.json')
    row = core.MEN_NEWSLETTER_LEDGER.record({'headline': cases[0][0], 'received_at': '2026-11-02T08:04:39Z'})
    core.MEN_NEWSLETTER_LEDGER.set(row, 'published', NOW, article_slug='rochdale-homes-evacuated-duplicate',
                                   resolved_title=cases[0][1], resolved_published_at='2026-10-31T18:40:00Z')
    row2 = core.MEN_NEWSLETTER_LEDGER.record({'headline': 'A story whose only article was taken down entirely', 'received_at': '2026-11-02T08:04:39Z'})
    core.MEN_NEWSLETTER_LEDGER.set(row2, 'published', NOW, article_slug='gone-article', resolved_title='A story whose only article was taken down entirely')
    changed = core.reconcile_men_newsletter_ledger(archive)
    check(changed == 2, 'both stale rows reconciled')
    check(row['status'] == 'already_covered' and row['article_slug'] == archive[0]['slug'], 're-pointed at the live original')
    check(row2['status'] == 'not_found' and row2['article_slug'] == '', 'reopened when nothing live covers it')

# Editor removals are final: the lane never re-creates a story taken down.
with tempfile.TemporaryDirectory() as tmp:
    core.MEN_NEWSLETTER_LEDGER = mn.CoverageLedger(Path(tmp) / 'r.json')
    original_blocklist = core.load_story_blocklist
    core.load_story_blocklist = lambda: {'slugs': ['rochdale-s-historic-hall-and-gardens-duplicate', 'legally-removed-story'],
                                         'title_patterns': [], 'source_urls': []}
    try:
        # The live row as it stood on 3 Nov: reopened, slug only in the reason.
        festival = core.MEN_NEWSLETTER_LEDGER.record({'headline': 'The historic Rochdale hall and gardens with spectacular fire festival',
                                                      'received_at': '2026-10-29T08:08:20Z'})
        core.MEN_NEWSLETTER_LEDGER.set(festival, 'not_found', NOW, article_slug='', resolved_url='',
                                       reason='its article rochdale-s-historic-hall-and-gardens-duplicate is no longer live; searching again')
        legal = core.MEN_NEWSLETTER_LEDGER.record({'headline': 'A court story that the editor took down on advice', 'received_at': '2026-11-02T08:00:00Z'})
        core.MEN_NEWSLETTER_LEDGER.set(legal, 'published', NOW, article_slug='legally-removed-story')
        changed = core.reconcile_men_newsletter_ledger([])
        check(changed == 2, f'both removed stories reconciled ({changed})')
        check(festival['status'] == 'removed_by_editor' and festival['removed_slug'] == 'rochdale-s-historic-hall-and-gardens-duplicate',
              'a reopened row whose article the editor removed is closed, not re-searched')
        check(legal['status'] == 'removed_by_editor', 'a story taken down by the editor is never re-created')
        check(not core.MEN_NEWSLETTER_LEDGER.needs_search(legal, NOW + timedelta(days=1)), 'a removed story is never searched again')
        summary = core.MEN_NEWSLETTER_LEDGER.summary()
        check(summary['removed_by_editor'] == 2 and summary['outstanding'] == 0 and not summary['outstanding_stories'],
              'removed stories are reported apart from outstanding ones')
        check(core.reconcile_men_newsletter_ledger([]) == 0, 'reconciliation is stable on a second run')
    finally:
        core.load_story_blocklist = original_blocklist

# Before writing: a story the editor removed is recognised from the takedown list itself.
removed = ['rochdale-s-historic-hall-and-gardens-to-host-spectacular-fire-festival-and-light',
           'police-appeal-for-information-on-wanted-man-linked-to-missing-children-in-rochda']
festival_again = must('The historic Rochdale hall and gardens with spectacular fire festival',
                      'The historic Rochdale hall and gardens with spectacular fire festival and light show')
status, reason, _ = core.must_cover_block(festival_again, {}, [], removed)
check(status == 'removed_by_editor' and removed[0] in reason, 'a removed story found again is not re-created')
sean = must('Urgent appeal as man, 22, goes missing in Rochdale', 'Urgent appeal as man, 22, goes missing in Rochdale')
check(core.must_cover_block(sean, {}, [], removed)[0] == '', 'a different appeal sharing a few words is still written')
check(core.removed_story_match(sean, removed) == '', 'the removed-story match is two-way, not one-way')

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
