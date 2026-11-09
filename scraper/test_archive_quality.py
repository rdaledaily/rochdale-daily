"""Guard reader structure, conservative edits and the complete link graph."""
from pathlib import Path
import tempfile

from archive_quality import safe_edit, related_graph, apply, scan, save, fingerprint
from editorial_contract import reader_ending, ward_decision, category_for

assert safe_edit('The changes is useful.', 'The changes are useful.')
assert not safe_edit('22 people attended.', '23 people attended.')
assert not safe_edit('The suspect was arrested.', 'The suspect was convicted.')
assert not safe_edit('Police said “wait here”.', 'Police said “go home”.')
assert not safe_edit('John Smith spoke.', 'James Smith spoke.')
assert not safe_edit('The homes may open.', 'The homes will open.')
assert not reader_ending({'title':'Man charged with burglary','category':'crime'})
assert not reader_ending({'title':'Roadworks in Heywood','category':'traffic'})  # withdrawn 9 Nov 2026
assert not ward_decision({'title':'Glenn Middleton speaks','area':'rochdale'})['wards']
assert not ward_decision({'title':'Work in Middleton','area':'middleton'})['wards']
assert category_for({'title':'Guided court chamber tour','category':'crime'}) == 'events'
rows=[{'slug':str(i),'title':'Local housing plans '+str(i),'area':'rochdale','category':'business','indexable':True,'published_at':'2026-10-01'} for i in range(5)]
graph,incoming=related_graph(rows)
assert all(graph[r['slug']] and incoming[r['slug']] for r in rows)
assert all(slug!=target for slug,targets in graph.items() for target in targets)

with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp); (root/'articles').mkdir()
    for i in range(2):
        slug='story-'+str(i)
        page='<html><head><link rel="canonical" href="https://rochdaledaily.co.uk/articles/'+slug+'"><meta name="robots" content="index,follow"></head><body><h1>Local housing plans</h1><div class="article-copy"><p>New homes are proposed in Rochdale.</p></div><section class="comments-section"></section></body></html>'
        (root/'articles'/f'{slug}.html').write_text(page)
    save(root/'articles.json',[])
    apply(root)
    before=[p.read_text() for p in sorted((root/'articles').glob('*.html'))]
    apply(root)
    after=[p.read_text() for p in sorted((root/'articles').glob('*.html'))]
    assert before==after, 'Archive final pass must be idempotent'
    assert all(p.count('data-rd-reader-ending="1"')==0 for p in after)  # no comment invitation, 9 Nov 2026
    assert all(p.count('id="rd-archive-related"')==1 for p in after)
    # Sources are inside article-copy in the current template: never add an
    # extra closing div before them, and never swallow the source links.
    p=root/'articles/story-0.html'
    text=p.read_text().replace('</div><section class="comments-section">','<details class="article-sources"><summary>Sources</summary><a href="https://example.org/source">Source</a></details></div><section class="comments-section">')
    # Use a clean current-template fixture with sources before its closing div.
    text='<html><head><link rel="canonical" href="https://rochdaledaily.co.uk/articles/story-0"></head><body><h1>Local housing plans</h1><div class="article-copy"><p>New homes are proposed.</p><details class="article-sources"><summary>Sources</summary><a href="https://example.org/source">Source</a></details></div><section class="comments-section"></section></body></html>'
    p.write_text(text)
    apply(root); once=p.read_text();apply(root);assert p.read_text()==once
    assert once.count('<div')==once.count('</div>')
    assert 'https://example.org/source' in once
    # Absolute first-party images must stay valid URLs, never /https://...
    from unittest.mock import patch
    p.write_text(p.read_text().replace('</head>', '<meta property="og:image" content="https://rochdaledaily.co.uk/assets/img/cards/photo.jpg"></head>'))
    with patch('image_hierarchy.choose_image', return_value='internal'):
        apply(root, images=True, network_images=False)
    assert 'src="https://rochdaledaily.co.uk/assets/img/cards/photo.jpg"' in p.read_text()
    assert 'src="/https://' not in p.read_text()
# A double-quoted meta description may contain an apostrophe. The archive
# metadata refresh must replace the whole attribute, not stop at the apostrophe.
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    (root / 'articles').mkdir()
    slug = 'apostrophe-description'
    excerpt = "Rochdale's deadline has passed; applications remain open."
    page = (
        '<html><head><link rel="canonical" href="https://rochdaledaily.co.uk/articles/' + slug + '">'
        '<meta name="description" content="Rochdale&#x27;s deadline has passed; applications remain open.">'
        '<meta property="og:description" content="Rochdale&#x27;s deadline has passed; applications remain open.">'
        '</head><body><h1>School admissions update</h1>'
        '<div class="article-copy"><p>Families can still apply for a place.</p></div></body></html>'
    )
    path = root / 'articles' / (slug + '.html')
    path.write_text(page)
    save(root / 'articles.json', [{
        'slug': slug, 'title': 'School admissions update', 'excerpt': excerpt,
        'category': 'education', 'area': 'rochdale',
        'published_at': '2026-11-02T09:00:00Z',
    }])
    apply(root)
    once = path.read_text()
    assert '<meta name="description" content="Rochdale&#x27;s deadline has passed; applications remain open.">' in once
    assert '<meta property="og:description" content="Rochdale&#x27;s deadline has passed; applications remain open.">' in once
    apply(root)
    twice = path.read_text()
    assert twice.count('<meta name="description" content="Rochdale&#x27;s deadline has passed; applications remain open.">') == 1
    assert twice.count('<meta property="og:description" content="Rochdale&#x27;s deadline has passed; applications remain open.">') == 1

# 6 Nov 2026: the low-detail image check may veto generic stock on the wrong
# story, never a photo named for the story or its subject.
from image_hierarchy import named_for_story
assert named_for_story({'slug': 'kingsway-hotel-in-rochdale-listed-for-sale-at-425-000', 'title': 'Kingsway Hotel listed'},
                       'assets/img/cards/kingsway-hotel-in-rochdale-listed-for-sa.jpg')
assert named_for_story({'slug': 'x', 'title': 'New Greater Manchester Mayor Bev Craig visits Rochdale'},
                       'assets/img/cards/manchester_mayor.jpg')
assert named_for_story({'slug': 'y', 'title': 'Littleborough residents help boost flood resilience through Resilient Roch project'},
                       'assets/img/cards/resilient_roch_project.jpg')
assert not named_for_story({'slug': 'z', 'title': 'Middleton protest planned as organiser sets out bail conditions'},
                           'assets/img/cards/bail.jpg')
assert not named_for_story({'slug': 'w', 'title': 'New MOT station opens on Maclure Road'}, 'assets/img/cards/tram.jpg')
assert not named_for_story({'slug': 'v', 'title': 'Housing allocation for Bamford'}, 'assets/img/cards/rochdale-borough-housing.jpg')
assert not named_for_story({'slug': 'u', 'title': 'Roadworks on Well i th Lane'}, 'assets/img/cards/x-place-generated-card.jpg')

print('Archive editorial contract checks passed.')
