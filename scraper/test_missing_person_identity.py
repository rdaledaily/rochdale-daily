"""Separate appeals must survive every clustering/fallback path."""
from story_identity import same_story, story_similarity, dedupe_article_records, build_story_key
from frontpage_pipeline import records_match, _same_frontpage_story

SEAN = dict(id='legacy-collision', title='Urgent appeal for missing 22-year-old man in Rochdale', excerpt='Police are seeking help to locate Sean, a 22-year-old man missing from Milkstone.', source_url='https://example.com/sean', area='rochdale', category='news', published_at='2026-10-21T18:46:51Z')
KODY = dict(id='legacy-collision', title='Urgent appeal for missing 16-year-old girl in Rochdale', excerpt='Greater Manchester Police are seeking help to locate Kody, a 16-year-old girl missing from Norden.', source_url='https://example.com/kody', area='rochdale', category='news', published_at='2026-10-10T14:16:21Z')
OTHER = {**SEAN, 'excerpt': 'Police are seeking help to locate Adam, a 22-year-old man missing from Milkstone.', 'source_url': 'https://example.com/adam'}
UNNAMED = {**SEAN, 'excerpt': 'Greater Manchester Police appeal for help finding a missing man.', 'source_url': 'https://example.com/unnamed'}
FOLLOWUP = {**SEAN, 'id': 'new-id', 'title': 'Missing Sean found safe following police appeal', 'source_url': 'https://another.example/sean', 'published_at': '2026-10-22T10:00:00Z'}
for other in (KODY, OTHER, UNNAMED):
    assert not same_story(SEAN, other)
    assert story_similarity(SEAN, other) == 0
    assert not records_match(SEAN, other)
    assert not _same_frontpage_story(SEAN, other)
    assert len(dedupe_article_records([SEAN, other])) == 2
assert build_story_key(SEAN) != build_story_key(KODY)
assert same_story(SEAN, FOLLOWUP)
assert len(dedupe_article_records([SEAN, FOLLOWUP])) == 1
# Old keys and IDs are not allowed to overrule the person check.
for other in (KODY, OTHER):
    assert not records_match({**SEAN, 'story_key': 'same'}, {**other, 'story_key': 'same'})
print('Missing-person identity regressions passed.')

assert not same_story(SEAN, {**FOLLOWUP, "published_at": "2026-12-01T10:00:00Z"})
