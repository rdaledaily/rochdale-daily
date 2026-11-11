"""Briefings and the editor's own articles never swallow other stories.

Run: PYTHONPATH=scraper python scraper/test_roundup_clustering.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from story_identity import dedupe_article_records  # noqa: E402

FAILURES = []


def check(condition, label):
    print(('PASS ' if condition else 'FAIL ') + label)
    if not condition:
        FAILURES.append(label)


gym_body = ('<p>An Israeli man was threatened with death at Oulder Hill Leisure Complex in Rochdale after racist abuse. '
            'Police were told of the threats. The alleged aggressor continued to use the gym.</p>')
gym = {'slug': 'israeli-man-threatened-with-death-at-rochdale-gym-after-racist-abuse', 'id': 'gym1', 'category': 'crime',
       'title': 'Israeli man threatened with death at Rochdale gym after racist abuse',
       'excerpt': 'An Israeli man faced threats at Oulder Hill Leisure Complex in Rochdale.', 'content_html': gym_body,
       'published_at': '2026-11-03T13:04:24Z', 'source_url': 'https://www.uklfi.com/israeli-man-threatened'}
briefing = {'slug': 'morning-briefing-4-november-2026', 'id': 'briefing-morning-briefing-4-november-2026', 'manual_article': True,
            'editorial_lock': True, 'category': 'news', 'title': 'Morning Briefing: Wednesday 4 November 2026',
            'excerpt': 'Israeli man threatened with death at Rochdale gym after racist abuse, and more.',
            'content_html': '<h2>Israeli man threatened with death at Rochdale gym after racist abuse</h2>' + gym_body,
            'published_at': '2026-11-04T09:00:00Z'}
older = dict(briefing, slug='morning-briefing-3-november-2026', id='briefing-morning-briefing-3-november-2026',
             title='Morning Briefing: Tuesday 3 November 2026', published_at='2026-11-03T09:00:00Z')

out = {r['slug'] for r in dedupe_article_records([gym, briefing, older])}
check(gym['slug'] in out, 'a briefing never swallows a story it summarises')
check({briefing['slug'], older['slug']} <= out, 'briefings never merge with each other')

appeal = {'slug': 'police-appeal-woman-may-have-given-birth', 'id': 'm1', 'manual_article': True, 'category': 'crime',
          'title': 'Police appeal for woman who may have given birth in Rochdale',
          'excerpt': 'Greater Manchester Police appeal in Rochdale.', 'content_html': '<p>Police in Rochdale appeal for help.</p>',
          'published_at': '2026-10-23T10:00:00Z'}
murder = dict(appeal, slug='man-arrested-suspicion-murder-curzon-road-rochdale', id='m2',
              title='Man arrested on suspicion of murder on Curzon Road, Rochdale')
out = {r['slug'] for r in dedupe_article_records([appeal, murder])}
check(out == {appeal['slug'], murder['slug']}, "two of the editor's articles stay separate")

same = dict(appeal)
check(len(dedupe_article_records([appeal, same])) == 1, 'an editor article still merges with its own record')

# The live case, from the real records (fixtures_roundup_swallow.json).
import json  # noqa: E402
case = json.loads((Path(__file__).resolve().parent / 'fixtures_roundup_swallow.json').read_text(encoding='utf-8'))
out = {r['slug'] for r in dedupe_article_records([case['briefing'], case['gym']])}
check(case['gym']['slug'] in out, 'live case: the 4 Nov briefing does not swallow the gym story re-filed as crime')

# One record per page address, whatever the event import adds (4 Nov 2026).
import frontpage_pipeline as fp  # noqa: E402
article = {'slug': 'rock-classics-by-candlelight-rochdale', 'id': 'e33c', 'source_kind': 'article', 'title': 'Rock Classics by Candlelight',
           'content_html': '<p>A concert at Rochdale Town Hall.</p>', 'published_at': '2026-08-21T16:03:06Z'}
event = dict(article, source_kind='event', event_start_at='2026-11-21T19:30:00Z', source_url='https://www.whatsoccurrinevents.co.uk/x')
other = dict(article, slug='another-story', id='zz')
out = fp._dedupe_by_slug([article, other, event])
check([r['slug'] for r in out] == ['rock-classics-by-candlelight-rochdale', 'another-story'], 'two records with one address become one; order kept')

# The front-page merge had no roundup guard (7-8 Nov 2026): the Baguley
# Crescent fire and two Lonsdale Court fire reports were folded into Morning
# Briefings and their pages carried the briefing's title.
fire = {'slug': 'man-in-his-60s-injured-in-flat-fire-on-baguley-crescent-middleton', 'id': 'f1', 'category': 'news',
        'area': 'middleton', 'title': 'Man in his 60s injured in flat fire on Baguley Crescent, Middleton',
        'content_html': '<p>A man in his 60s was injured in a flat fire on Baguley Crescent in Middleton on Saturday '
                        'afternoon. Three fire engines from Blackley, Whitefield and Broughton attended.</p>',
        'published_at': '2026-11-07T19:16:00Z', 'source_url': 'https://example.org/fire'}
sunday = {'slug': 'morning-briefing-8-november-2026', 'id': 'briefing-morning-briefing-8-november-2026',
          'manual_article': True, 'editorial_lock': True, 'category': 'news',
          'title': 'Morning Briefing: Sunday 8 November 2026', 'excerpt': '4 new stories',
          'content_html': '<ul><li>Man in his 60s injured in flat fire on Baguley Crescent, Middleton (Middleton). A man in '
                          'his 60s was injured in a flat fire on Baguley Crescent in Middleton on Saturday afternoon.</li></ul>',
          'published_at': '2026-11-08T09:04:16Z'}
check(not fp._mergeable(fire, sunday), 'front-page merge: a briefing never matches a story it lists')
check(not fp._same_frontpage_story(fire, sunday), 'front-page dedupe: a briefing never matches a story it lists')
out = [r['slug'] for r in fp.merge_duplicate_articles([fire, sunday])]
check(sorted(out) == sorted([fire['slug'], sunday['slug']]), 'front-page merge keeps the story and the briefing apart')
check(fp._mergeable(sunday, dict(sunday)), 'a briefing still merges with its own record')

print()
if FAILURES:
    print(f'{len(FAILURES)} FAILED')
    sys.exit(1)
print('all roundup clustering checks passed')
