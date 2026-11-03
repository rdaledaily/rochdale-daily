"""MEN MyRochdale newsletter: every story it lists is one Rochdale Daily covers.

The editor's rule (3 Nov 2026): stories from news@newsletters.e.manchester-
eveningnews.co.uk are not leads to be weighed, they are stories that are
covered every time. This module turns each newsletter headline into a MEN
article and keeps a ledger of what happened to every one of them.

Why the old route missed half of them (measured 3 Nov 2026, run 08:57Z):
each headline became ONE Google News query for the exact headline in quotes.
The newsletter writes its own teaser headlines, so the article is often
indexed under different words. 6 of 12 queries returned nothing; two others
returned 61 and 100 loose matches (Google drops the quotes when nothing
matches), and every result then went through the ordinary age and locality
filters, so nothing marked them as stories that must run.

Resolution here is two searches, stopping at the first match:
  1. the exact headline (works when the teaser IS the article headline);
  2. the headline's distinctive words, site-restricted to the MEN.
Each result's title is scored against the newsletter headline, and only a
real match is accepted. A headline that matches nothing is reported as
not_found - there is no substitute source and no guess.

The email's own links are never followed: they are per-subscriber tracking
redirects, and following them would log clicks against the editor's
subscription and expose her subscriber id.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

ROOT = Path(__file__).resolve().parents[1]
LEADS_PATH = ROOT / 'scraper' / 'men_newsletter_leads.json'
COVERAGE_PATH = ROOT / 'reports' / 'men_newsletter_coverage.json'

SOURCE_LABEL = 'MEN MyRochdale newsletter'
QUERY_LABEL = 'MEN MyRochdale newsletter story'
PUBLISHER_DOMAIN = 'manchestereveningnews.co.uk'

# A newsletter story stays owed for this long after the email arrived.
WINDOW_DAYS = 7
# An unresolved headline is searched again no sooner than this.
RESEARCH_INTERVAL = timedelta(hours=2)
# Google News queries this collector may spend in one run.
MAX_QUERIES_PER_RUN = 24

# Title match: at least half of the headline's distinctive words, and never
# fewer than three of them, must appear in the article title; and where both
# carry numbers, they must share one. Measured 3 Nov 2026 against the 507-story
# archive: with two shared words "Homes at new Rochdale town centre housing
# complex will be affordable" matched five unrelated housing stories, and
# "Urgent appeal as man, 22, goes missing" matched an appeal for a missing
# 10-year-old. Three words plus the number veto accepted every true pair seen.
MATCH_MIN_SCORE = 0.5
MATCH_MIN_SHARED = 3

# Terminal states: the story needs nothing more.
DONE_STATUSES = {'published', 'already_covered'}

STOPWORDS = frozenset('''
a an the and or but if of to in on at by for with from as into onto over under
after before about after against between through during without within upon
is are was were be been being am has have had do does did will would shall
should can could may might must not no nor so than that this these those
it its it's he she they them his her their our we you your i me my
who whom whose which what when where why how all any each every some such
up out off down just only also very more most much many one two new latest
here there now then still yet ever been get got gets says said say
'''.split())

# Words nearly every result of a site-restricted Rochdale search shares. They
# say nothing about WHICH story it is, so they are not counted as evidence.
GENERIC_PLACE_TERMS = frozenset({'rochdale', 'greater', 'manchester', 'borough', 'town', 'centre'})

_SUFFIX_RE = re.compile(r'\s+[-|–—]\s+(?:manchester evening news|men)\s*$', re.IGNORECASE)
_WORD_RE = re.compile(r"[a-z0-9£]+(?:'[a-z]+)?")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def clean_title(title: str) -> str:
    """Drop the ' - Manchester Evening News' tail Google News appends."""
    return _SUFFIX_RE.sub('', ' '.join(str(title or '').split())).strip()


def headline_terms(text: str) -> list[str]:
    """Distinctive words of a headline, in order, lower-cased and de-duplicated.

    Curly quotes become straight, a possessive 's is dropped, and a plural s
    is folded so "homes" matches "home".
    """
    text = str(text or '').lower().replace('’', "'").replace('‘', "'")
    terms: list[str] = []
    for word in _WORD_RE.findall(text):
        if word.endswith("'s"):
            word = word[:-2]
        word = word.strip("'")
        if word in STOPWORDS or word in GENERIC_PLACE_TERMS or (len(word) < 3 and not word.isdigit()):
            continue
        if len(word) > 4 and word.endswith('s') and not word.endswith('ss'):
            word = word[:-1]
        if word not in terms:
            terms.append(word)
    return terms


def title_match(headline: str, title: str) -> tuple[float, int]:
    """(score, shared): share of the headline's distinctive words in the title."""
    wanted = headline_terms(headline)
    if not wanted:
        return 0.0, 0
    have = set(headline_terms(clean_title(title)))
    shared = sum(1 for term in wanted if term in have)
    return shared / len(wanted), shared


def _numbers(text: str) -> set[str]:
    return {term for term in headline_terms(text) if any(ch.isdigit() for ch in term)}


def is_match(headline: str, title: str) -> bool:
    score, shared = title_match(headline, title)
    if score < MATCH_MIN_SCORE or shared < MATCH_MIN_SHARED:
        return False
    wanted, have = _numbers(headline), _numbers(clean_title(title))
    return not (wanted and have and not (wanted & have))


def _google_news_url(query: str) -> str:
    return 'https://news.google.com/rss/search?q=' + quote_plus(query) + '&hl=en-GB&gl=GB&ceid=GB:en'


def search_urls(headline: str) -> list[tuple[str, str]]:
    """The searches tried for one headline, in order: exact, then keywords."""
    phrase = ' '.join(str(headline).replace('"', '').split())
    urls = [('exact', _google_news_url(f'site:{PUBLISHER_DOMAIN} "{phrase}" when:{WINDOW_DAYS}d'))]
    terms = headline_terms(headline)
    if len(terms) >= MATCH_MIN_SHARED:
        keywords = ' '.join(terms[:7])
        urls.append(('keywords', _google_news_url(f'site:{PUBLISHER_DOMAIN} {keywords} when:{WINDOW_DAYS}d')))
    return urls


def load_stories(now: datetime | None = None, path: Path = LEADS_PATH) -> list[dict[str, str]]:
    """Every newsletter story still inside its window, oldest email first."""
    now = now or utc_now()
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    stories: list[dict[str, str]] = []
    seen: set[str] = set()
    for issue in payload.get('issues', []) if isinstance(payload, dict) else []:
        received = _parse_time(issue.get('received_at')) if isinstance(issue, dict) else None
        if not received or received > now + timedelta(minutes=5) or now - received > timedelta(days=WINDOW_DAYS):
            continue
        for headline in issue.get('headlines', []):
            if not isinstance(headline, str):
                continue
            headline = ' '.join(headline.split())[:300]
            key = headline.casefold()
            if len(headline) < 15 or key in seen:
                continue
            seen.add(key)
            stories.append({'headline': headline, 'received_at': _iso(received)})
    return stories


def story_key(headline: str) -> str:
    return ' '.join(str(headline).casefold().split())


class CoverageLedger:
    """reports/men_newsletter_coverage.json - one record per newsletter story.

    status is one of:
      not_found        no MEN article matched either search yet
      found            matched; waiting to be written this run
      published        Rochdale Daily published it (article_slug)
      already_covered  an existing Rochdale Daily article already carries it
      rewrite_failed   matched but the rewrite/quality gate stopped it (reason)
      held             the rewrite ledger is holding it after repeated failures
      rejected         the matched page is a service/dashboard page, not an article
      waiting_for_text the article was found but its text could not be read yet;
                       retried every run, never written from a headline alone
    """

    def __init__(self, path: Path = COVERAGE_PATH):
        self.path = path
        self.records: dict[str, dict[str, Any]] = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
                for row in data.get('stories', []) if isinstance(data, dict) else []:
                    if isinstance(row, dict) and row.get('headline'):
                        self.records[story_key(row['headline'])] = row
            except (OSError, ValueError):
                self.records = {}

    def record(self, story: dict[str, str]) -> dict[str, Any]:
        key = story_key(story['headline'])
        row = self.records.get(key)
        if row is None:
            row = {
                'headline': story['headline'],
                'received_at': story['received_at'],
                'status': 'not_found',
                'reason': '',
                'resolved_url': '',
                'resolved_title': '',
                'article_slug': '',
                'searches': 0,
                'last_searched_at': '',
                'updated_at': '',
            }
            self.records[key] = row
        return row

    def needs_search(self, row: dict[str, Any], now: datetime) -> bool:
        if row.get('status') in DONE_STATUSES:
            return False
        if row.get('resolved_url'):
            return False
        last = _parse_time(row.get('last_searched_at'))
        return last is None or now - last >= RESEARCH_INTERVAL

    def set(self, row: dict[str, Any], status: str, now: datetime, **fields: Any) -> None:
        row['status'] = status
        for name, value in fields.items():
            row[name] = value
        if status in DONE_STATUSES | {'found'}:
            row['reason'] = fields.get('reason', '')
        row['updated_at'] = _iso(now)

    def prune(self, now: datetime) -> None:
        """Forget stories whose email is older than the window plus a week."""
        horizon = timedelta(days=WINDOW_DAYS * 2)
        self.records = {
            key: row for key, row in self.records.items()
            if (_parse_time(row.get('received_at')) or now) >= now - horizon
        }

    def summary(self, active_keys: set[str] | None = None) -> dict[str, Any]:
        rows = [row for key, row in self.records.items() if active_keys is None or key in active_keys]
        counts: dict[str, int] = {}
        for row in rows:
            counts[row.get('status', 'unknown')] = counts.get(row.get('status', 'unknown'), 0) + 1
        covered = counts.get('published', 0) + counts.get('already_covered', 0)
        return {
            'source': SOURCE_LABEL,
            'rule': 'Every story in the MEN MyRochdale newsletter is covered (editor, 3 Nov 2026).',
            'window_days': WINDOW_DAYS,
            'stories_in_window': len(rows),
            'covered': covered,
            'outstanding': len(rows) - covered,
            'by_status': dict(sorted(counts.items())),
            'outstanding_stories': [
                {key: row.get(key, '') for key in ('headline', 'received_at', 'status', 'reason', 'resolved_url')}
                for row in sorted(rows, key=lambda item: item.get('received_at', ''))
                if row.get('status') not in DONE_STATUSES
            ],
        }

    def save(self, now: datetime) -> None:
        self.prune(now)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            'generated_at': _iso(now),
            'source': SOURCE_LABEL,
            'stories': sorted(self.records.values(), key=lambda item: (item.get('received_at', ''), item.get('headline', ''))),
        }
        temporary = self.path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        temporary.replace(self.path)
