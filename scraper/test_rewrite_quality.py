from __future__ import annotations

from scraper import (
    Candidate,
    article_is_low_quality,
    draft_quality_issues,
    redact_private_location,
)


def candidate() -> Candidate:
    return Candidate(
        source_name='Greater Manchester Police',
        source_url='https://example.test/story',
        source_title='Man charged after robbery in Rochdale town centre',
        source_summary='A 32-year-old man has been charged after a robbery in Rochdale town centre on Tuesday.',
        source_published_at='2026-07-09T12:00:00Z',
        area='rochdale',
        category='crime',
        source_body_excerpt='Police said the man was due to appear at Manchester Magistrates Court on Wednesday.',
    )


def run() -> None:
    bad = {
        'publishable': True,
        'title': 'Rochdale crime update',
        'excerpt': 'Greater Manchester Police has published a crime update connected to Rochdale and readers can use the source link.',
        'paragraphs': [
            'The update was published by Greater Manchester Police.',
            'The source item is linked with this report.',
            'Further confirmed information will be added.',
        ],
    }
    assert draft_quality_issues(bad, candidate().source_summary + ' ' + candidate().source_body_excerpt, candidate())
    assert article_is_low_quality({'publication_route': 'direct-crime-autopublish'})

    good = {
        'publishable': True,
        'title': 'Man charged after Rochdale town-centre robbery',
        'excerpt': 'A 32-year-old man has been charged following a robbery in Rochdale town centre and is due before magistrates, according to police.',
        'paragraphs': [
            'Greater Manchester Police said a 32-year-old man had been charged after a robbery in Rochdale town centre on Tuesday.',
            'The force said he was due to appear at Manchester Magistrates Court on Wednesday.',
            'No further details about the alleged incident were included in the police update.',
        ],
    }
    issues = draft_quality_issues(good, candidate().source_summary + ' ' + candidate().source_body_excerpt, candidate())
    assert not any('publishing process' in issue for issue in issues), issues
    redacted = redact_private_location('John Smith was found at 12 Example Road, OL12 3AB.')
    assert 'John Smith' in redacted
    assert '12 Example Road' not in redacted
    assert 'OL12 3AB' not in redacted
    print('Rewrite quality tests passed.')


if __name__ == '__main__':
    run()
