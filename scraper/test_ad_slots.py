"""Advert slots are render-time furniture: never stored, never stacked.

Regression for 23 Oct 2026: generate_pages added a slot on every render and
archive_quality read bodies back from rendered pages into articles.json, so
slots accumulated (105 stories reached 13 each; ads.js filled and counted all
of them). Run: python scraper/test_ad_slots.py
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ad_slots  # noqa: E402

BODY = '<p>One.</p><p>Two.</p><p>Three.</p><p>Four.</p><p>Five.</p>'


def test_exactly_one_slot_after_third_paragraph():
    out = ad_slots.insert_incontent_ad(BODY)
    assert ad_slots.count_ad_slots(out) == 1
    assert out.startswith('<p>One.</p><p>Two.</p><p>Three.</p>' + ad_slots.AD_SLOT_HTML + '<p>Four.</p>')


def test_no_stray_closing_paragraph():
    out = ad_slots.insert_incontent_ad(BODY)
    assert out.count('</p>') == BODY.count('</p>')
    assert ad_slots.AD_SLOT_HTML + '</p>' not in out


def test_idempotent_over_many_renders():
    out = BODY
    for _ in range(15):
        out = ad_slots.insert_incontent_ad(out)
    assert ad_slots.count_ad_slots(out) == 1
    assert out == ad_slots.insert_incontent_ad(BODY)


def test_stacked_slots_any_attribute_order_collapse_to_one():
    # BeautifulSoup reorders attributes alphabetically; that is the shape
    # actually stored in articles.json on 23 Oct.
    soup_slot = '<div aria-hidden="true" class="ad-slot ad-slot-incontent" data-ad-slot="article-incontent" role="presentation"></div>'
    dirty = '<p>One.</p><p>Two.</p><p>Three.</p>' + soup_slot * 13 + '<p>Four.</p>'
    assert ad_slots.count_ad_slots(dirty) == 13
    assert ad_slots.count_ad_slots(ad_slots.insert_incontent_ad(dirty)) == 1
    assert 'ad-slot' not in ad_slots.strip_ad_slots(dirty)


def test_short_story_slot_at_end():
    out = ad_slots.insert_incontent_ad('<p>Only.</p><p>Two.</p>')
    assert out == '<p>Only.</p><p>Two.</p>' + ad_slots.AD_SLOT_HTML


def test_no_paragraphs_unchanged():
    assert ad_slots.insert_incontent_ad('plain text') == 'plain text'


def test_render_then_read_back_loop_is_stable():
    """The real loop: render a page, read the body back the way
    archive_quality does, store it, render again."""
    import generate_pages
    from archive_quality import article_body

    record = {'slug': 't', 'title': 'Test story', 'content_html': BODY, 'category': 'news'}
    for _ in range(5):
        page = generate_pages.render_article_page(dict(record), [dict(record)])
        assert ad_slots.count_ad_slots(page) == 1, ad_slots.count_ad_slots(page)
        record['content_html'] = article_body(page)
        assert 'ad-slot' not in record['content_html']


def test_scrub_stored_slots_cleans_feed_file():
    import generate_pages
    dirty = '<p>A.</p>' + ad_slots.AD_SLOT_HTML * 3 + '<p>B.</p>'
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'articles.json'
        path.write_text(json.dumps([{'slug': 'x', 'content_html': dirty, 'title': '£5'}], ensure_ascii=False), encoding='utf-8')
        assert generate_pages.scrub_stored_ad_slots(path) == 3
        rows = json.loads(path.read_text(encoding='utf-8'))
        assert rows[0]['content_html'] == '<p>A.</p><p>B.</p>'
        assert '£5' in path.read_text(encoding='utf-8')
        assert generate_pages.scrub_stored_ad_slots(path) == 0


if __name__ == '__main__':
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print('ok  ', name)
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print('FAIL', name, repr(exc))
    sys.exit(1 if failures else 0)
