"""Guides and the community directory: valid data, safe links, never articles."""
import json
from pathlib import Path

import generate_groups
import generate_guides
from link_ban import banned_in_value

ROOT = Path(__file__).resolve().parents[1]


def test_every_guide_loads():
    guides, problems = generate_guides.load_guides()
    assert not problems, problems
    assert len(guides) >= 3


def test_directory_loads_with_unique_slugs():
    checked, groups, problems = generate_groups.load_groups()
    assert not problems, problems
    assert len({g["slug"] for g in groups}) == len(groups) >= 50


def test_rendered_pages_have_no_banned_links():
    guides, _ = generate_guides.load_guides()
    pages = [generate_guides.render_guide(g) for g in guides] + [generate_guides.render_index(guides)]
    checked, groups, _ = generate_groups.load_groups()
    pages.append(generate_groups.render(checked, groups))
    for html in pages:
        assert not banned_in_value(html)


def test_every_directory_entry_is_anchored():
    checked, groups, _ = generate_groups.load_groups()
    html = generate_groups.render(checked, groups)
    for g in groups:
        assert f'id="{g["slug"]}"' in html
    assert "free, forever" in html


def test_seo_titles_fit():
    guides, _ = generate_guides.load_guides()
    assert all(len(g["seo_title"]) <= 53 for g in guides)


def test_guides_and_directory_are_never_articles():
    articles = json.loads((ROOT / "articles.json").read_text(encoding="utf-8"))
    items = articles if isinstance(articles, list) else articles.get("articles", [])
    urls = " ".join(str(a.get("url") or a.get("link") or "") for a in items if isinstance(a, dict))
    assert "/guides/" not in urls and "/groups/" not in urls


def test_bad_slug_is_reported(tmp_path):
    p = tmp_path / "data.json"
    p.write_text(json.dumps({"checked": "2026-11-18", "groups": [
        {"slug": "Bad Slug", "name": "x", "about": "y", "category": "Schools"},
        {"slug": "ok", "name": "x", "about": "y", "category": "Schools", "website": "http://x"},
    ]}), encoding="utf-8")
    _, groups, problems = generate_groups.load_groups(p)
    assert groups == [] and len(problems) == 2
