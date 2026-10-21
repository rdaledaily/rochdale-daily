"""Regression: folklore cannot turn into an active police incident."""
import json
from datetime import datetime, timezone
from pathlib import Path
from feature_policy import normalise_feature, is_reserve_feature
from article_gate import normalise_article
from frontpage_pipeline import apply_category_rules, article_category, arrange_frontpage
from generate_pages import render_article_page
from live_story_updates import _is_developing


def main():
    source = next(a for a in json.loads(Path('articles.json').read_text()) if a.get('evergreen_id') == 'clegg-hall-boggart')
    broken = dict(source, category='crime', is_ongoing=True, live_story=True, breaking_news=True, police_matter=True)
    for marker in ({'is_evergreen': True}, {'evergreen_id': 'old-feature'}, {'source_kind': 'evergreen'}, {'publication_route': 'evergreen_fallback'}):
        assert is_reserve_feature(marker)
    feature = normalise_feature(broken)
    assert feature['category'] == 'community'
    assert feature['first_published_at'] == broken['first_published_at']
    assert feature['sources'] == broken['sources']
    assert feature == normalise_feature(feature)
    assert article_category(broken) == 'community'
    assert apply_category_rules(broken) == feature
    assert not _is_developing(broken)
    gated = normalise_article(broken, [])
    assert gated['category'] == 'community' and not gated['is_ongoing']
    assert not gated['police_matter'] and not gated['breaking_news']
    page = render_article_page(broken, [broken])
    assert 'Report what you know' not in page
    assert '<span class="kicker-chip">Feature</span>' in page
    assert '<span class="kicker-chip">ONGOING' not in page
    news = dict(source, id='real-news', slug='real-news', is_evergreen=False, evergreen_id='', source_kind='article', publication_route='editorial', category='health')
    assert normalise_feature(news) == news
    assert arrange_frontpage([feature, news], datetime.now(timezone.utc))[0]['id'] == 'real-news'
    prose = dict(broken, content_html='<p class="ongoing-label">ONGOING STORY</p><p>Original legend.</p><h2>Update timeline</h2><ul><li>Duplicate</li></ul>')
    assert normalise_feature(prose)['content_html'] == '<p>Original legend.</p>'
    print('feature policy regression checks passed')

if __name__ == '__main__':
    main()
