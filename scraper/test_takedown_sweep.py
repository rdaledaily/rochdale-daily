"""Takedown sweep: a removed story must leave no listing on any public page.

Fixtures reproduce the markup that kept the Little Oaks story listed after the
5 Nov 2026 takedown: a section-hub card plus its JSON-LD ItemList entry, a
"More from" <li> inside another article, a topic-hub <li> with excerpt, and an
image-sitemap <url> block.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from takedown_sweep import sweep, verify  # noqa: E402

SLUG = "little-oaks-nursery-loses-planning-bid-for-caravan-in-heywood"
OTHER = "heywood-school-pupil-names-new-road"
LONGER = SLUG + "-appeal-lodged"  # must not be touched: different story

HUB = (
    '<html><head><script type="application/ld+json">{"@type": "ItemList", "itemListElement": ['
    '{"@type": "ListItem", "position": 1, "url": "https://rochdaledaily.co.uk/articles/' + OTHER + '", "name": "Pupil names road"}, '
    '{"@type": "ListItem", "position": 2, "url": "https://rochdaledaily.co.uk/articles/' + SLUG + '", "name": "Heywood nursery loses planning bid"}, '
    '{"@type": "ListItem", "position": 3, "url": "https://rochdaledaily.co.uk/articles/' + LONGER + '", "name": "Appeal"}]}'
    '</script></head><body><main>'
    '<article class="rd-card"><a href="/articles/' + OTHER + '">Pupil names road</a></article>'
    '<article class="rd-card"><a href="/articles/' + SLUG + '" tabindex="-1"><img src="x.jpg"></a>'
    '<h3><a href="/articles/' + SLUG + '">Heywood nursery loses planning bid</a></h3><p>Little Oaks...</p></article>'
    '<article class="rd-card"><a href="/articles/' + LONGER + '">Appeal</a></article>'
    "</main></body></html>"
)
ARTICLE = (
    '<html><body><main><article class="story"><h1>Other story</h1><p>Body.</p>'
    '<ul class="more"><li><a href="/articles/' + OTHER + '">Pupil names road</a></li>'
    '<li><a href="/articles/' + SLUG + '">Heywood nursery loses planning bid</a></li></ul>'
    "</article></main></body></html>"
)
TOPIC = (
    "<html><body><ul>\n<li><a href=\"/articles/" + SLUG + "\">Heywood nursery</a>"
    "<p>— Little Oaks Nursery in Heywood has been denied permission.</p>\n</li>\n"
    "<li><a href=\"/articles/" + OTHER + "\">Pupil</a></li>\n</ul></body></html>"
)
SITEMAP = (
    '<?xml version="1.0"?><urlset xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">\n'
    "  <url>\n    <loc>https://rochdaledaily.co.uk/articles/" + SLUG + "</loc>\n"
    "    <image:image><image:loc>https://rochdaledaily.co.uk/a.jpg</image:loc></image:image>\n  </url>\n"
    "  <url>\n    <loc>https://rochdaledaily.co.uk/articles/" + OTHER + "</loc>\n  </url>\n</urlset>\n"
)


def build(root: Path) -> None:
    (root / "news" / "topics").mkdir(parents=True)
    (root / "articles").mkdir()
    (root / "news" / "environment.html").write_text(HUB, encoding="utf-8")
    (root / "news" / "topics" / "planning.html").write_text(TOPIC, encoding="utf-8")
    (root / "articles" / f"{OTHER}.html").write_text(ARTICLE, encoding="utf-8")
    (root / "image-sitemap.xml").write_text(SITEMAP, encoding="utf-8")
    (root / "_redirects").write_text(f"/articles/{SLUG} /news/environment 301\n", encoding="utf-8")


def test_sweep_removes_every_listing_and_nothing_else(tmp_path):
    build(tmp_path)
    assert len(verify(tmp_path, [SLUG])) == 4

    changed = sweep(tmp_path, [SLUG])

    assert set(changed) == {
        "news/environment.html",
        "news/topics/planning.html",
        f"articles/{OTHER}.html",
        "image-sitemap.xml",
    }
    assert verify(tmp_path, [SLUG]) == []
    for path in tmp_path.rglob("*"):
        if path.is_file() and path.name != "_redirects":
            text = path.read_text(encoding="utf-8")
            assert "Little Oaks" not in text and "nursery loses" not in text
            assert OTHER in text  # neighbouring stories survive


def test_longer_slug_and_redirects_untouched(tmp_path):
    build(tmp_path)
    sweep(tmp_path, [SLUG])
    hub = (tmp_path / "news" / "environment.html").read_text(encoding="utf-8")
    assert LONGER in hub and hub.count("rd-card") == 2
    assert SLUG in (tmp_path / "_redirects").read_text(encoding="utf-8")


def test_json_ld_stays_valid_and_renumbered(tmp_path):
    build(tmp_path)
    sweep(tmp_path, [SLUG])
    hub = (tmp_path / "news" / "environment.html").read_text(encoding="utf-8")
    block = hub.split('<script type="application/ld+json">')[1].split("</script>")[0]
    items = json.loads(block)["itemListElement"]
    assert [item["position"] for item in items] == [1, 2]
    assert all(SLUG + '"' not in json.dumps(item) for item in items)


def test_sitemap_stays_well_formed(tmp_path):
    import xml.dom.minidom

    build(tmp_path)
    sweep(tmp_path, [SLUG])
    xml.dom.minidom.parse(str(tmp_path / "image-sitemap.xml"))


def test_own_page_is_never_cut_into(tmp_path):
    build(tmp_path)
    own = tmp_path / "articles" / SLUG / "index.html"
    own.parent.mkdir()
    page = f'<html><head><link rel="canonical" href="https://rochdaledaily.co.uk/articles/{SLUG}"></head><body><article>x</article></body></html>'
    own.write_text(page, encoding="utf-8")
    sweep(tmp_path, [SLUG])
    assert own.read_text(encoding="utf-8") == page
    assert verify(tmp_path, [SLUG]) == []


def test_sweep_is_idempotent(tmp_path):
    build(tmp_path)
    sweep(tmp_path, [SLUG])
    assert sweep(tmp_path, [SLUG]) == {}
