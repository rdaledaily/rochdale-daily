"""Newsdesk checks on article pages are only ever the editor's own.

Run: PYTHONPATH=scraper python scraper/test_story_checks.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import story_checks as sc  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, label: str) -> None:
    print(('PASS ' if condition else 'FAIL ') + label)
    if not condition:
        FAILURES.append(label)


published = datetime(2026, 11, 3, 9, 12, tzinfo=timezone.utc)
check(sc.checked_label('2026-11-03T11:05:00Z', published) == 'Checked by the newsdesk 11:05 GMT', 'same-day check shows the time')
check(sc.checked_label('2026-11-04T08:30:00Z', published) == 'Checked by the newsdesk 4 Nov 08:30 GMT', 'a later day shows the date')
check(sc.checked_label('2026-07-01T10:00:00Z', datetime(2026, 7, 1, 8, tzinfo=timezone.utc)) == 'Checked by the newsdesk 11:00 BST',
      'summer checks are shown in BST')
check(sc.checked_label('not a time', published) == '', 'a malformed time shows nothing')

with tempfile.TemporaryDirectory() as tmp:
    snap = Path(tmp) / 'checks.json'
    live = {'some-story-slug': '2026-11-03T11:05:00Z'}
    checks, origin = sc.load_checks(fetch=lambda: dict(live), path=snap)
    check(origin == 'api' and checks == live, 'the live API is used when it answers')
    check(json.loads(snap.read_text())['checks'] == live, 'a successful read refreshes the snapshot')
    checks, origin = sc.load_checks(fetch=lambda: None, path=snap)
    check(origin == 'snapshot' and checks == live, 'a failed read falls back to the snapshot, keeping every check')
    checks, origin = sc.load_checks(fetch=lambda: {}, path=snap)
    check(checks == {} and json.loads(snap.read_text())['checks'] == {}, 'an undone check disappears from the snapshot too')
    snap.write_text(json.dumps({'checks': {'Bad Slug!': '2026-11-03T11:05:00Z', 'good-slug-here': 'yesterday'}}))
    check(sc.read_snapshot(snap) == {}, 'malformed entries are ignored, never shown')

# Rendering: the line appears only when a check exists.
import generate_pages as gp  # noqa: E402

base = {
    'slug': 'some-story-slug', 'title': 'Roadworks close Drake Street for two weeks', 'excerpt': 'Drake Street closes on Monday.',
    'content_html': '<p>Drake Street will close from Monday for resurfacing work.</p>', 'category': 'traffic',
    'published_at': '2026-11-03T09:12:00Z', 'first_published_at': '2026-11-03T09:12:00Z', 'source_url': 'https://www.rochdale.gov.uk/x',
}
plain = gp.render_article_page(dict(base), [dict(base)])
check('class="article-checked"' not in plain and 'Checked by the newsdesk' not in plain, 'an unchecked story carries no Checked line')
checked = gp.render_article_page(dict(base, checked_at='2026-11-03T11:05:00Z'), [dict(base)])
check('Checked by the newsdesk 11:05 GMT' in checked, 'a checked story shows the line')
check('href="/editorial-standards#checking"' in checked, 'the line links to what a check means')
check('datetime="2026-11-03T11:05:00Z"' in checked, 'the exact time is machine-readable')
check('/assets/js/article-checked.js' in plain, 'pages load the script that shows checks made since the build')

standards = (Path(__file__).resolve().parents[1] / 'editorial-standards.html').read_text(encoding='utf-8')
check('id="checking"' in standards and 'has not yet been checked' in standards, 'the standards page says what a check is')

print()
if FAILURES:
    print(f'{len(FAILURES)} FAILED')
    sys.exit(1)
print('all newsdesk check tests passed')
