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
assert 'comments' in reader_ending({'title':'Roadworks in Heywood','category':'traffic'})
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
    assert all(p.count('data-rd-reader-ending="1"')==1 for p in after)
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
print('Archive editorial contract checks passed.')
