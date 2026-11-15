"""Two of the editor's own articles are never merged with each other.

Measured on the live feed of 15 Nov 2026: the merge steps in
frontpage_pipeline grouped 64 of her articles into 26 groups on every run,
most because they cite the same bare homepage as their source.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import frontpage_pipeline as fp  # noqa: E402


def _article(slug: str, title: str, body: str, source: str, editor: bool) -> dict:
    record = {
        "id": f"id-{slug}", "slug": slug, "title": title, "content_html": f"<p>{body}</p>",
        "category": "community", "area": "rochdale", "status": "published",
        "source_name": "Facebook", "source_url": source, "source_urls": [source],
        "published_at": "2026-11-14T10:00:00Z", "first_published_at": "2026-11-14T10:00:00Z",
    }
    if editor:
        record.update({"manual_article": True, "editorial_lock": True})
    return record


BOWLS = ("syke-bowls", "Young bowlers invited to take part in Syke Bowling Club fun day",
         "Syke Bowling Club is holding a junior fun day for young bowlers.")
RUGBY = ("littleborough-rugby", "Littleborough RUFC invites more girls to discover rugby",
         "Littleborough RUFC is running open training sessions for girls.")
HOMEPAGE = "https://www.facebook.com/"


def test_two_editor_articles_sharing_a_homepage_source_stay_separate():
    left, right = _article(*BOWLS, HOMEPAGE, True), _article(*RUGBY, HOMEPAGE, True)
    assert not fp._mergeable(left, right)
    assert not fp._same_frontpage_story(left, right)
    assert len(fp.merge_duplicate_articles([left, right])) == 2
    assert len(fp._dedupe_by_url([left, right])) == 2


def test_an_editor_article_is_still_the_same_as_itself():
    left = _article(*BOWLS, HOMEPAGE, True)
    assert fp._mergeable(left, dict(left))
    assert fp._same_frontpage_story(left, dict(left))


def test_an_automated_copy_still_folds_into_the_editors_article():
    page = "https://www.example.org/news/syke-bowling-club-junior-fun-day"
    editor, automated = _article(*BOWLS, page, True), _article("syke-bowls-copy", BOWLS[1], BOWLS[2], page, False)
    assert fp._mergeable(editor, automated)
    assert len(fp.merge_duplicate_articles([editor, automated])) == 1


def test_two_automated_stories_are_unaffected():
    page = "https://www.example.org/news/syke-bowling-club-junior-fun-day"
    left, right = _article(*BOWLS, page, False), _article("syke-bowls-copy", BOWLS[1], BOWLS[2], page, False)
    assert fp._mergeable(left, right)
