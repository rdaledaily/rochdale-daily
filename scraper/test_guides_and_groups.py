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


# --- Death notices (18 Nov 2026) ---
import generate_notices


def _notice(**kw):
    n = {"slug": "jane-smith-2026-11-20", "kind": "death_notice", "name": "Jane Smith", "age": 84,
         "town": "Heywood", "died": "2026-11-15", "published": "2026-11-20",
         "text": "Peacefully at home.\n\nBeloved mum <script>x</script>", "verified_with": "funeral director"}
    n.update(kw)
    return n


def test_notice_is_escaped_and_rendered(tmp_path):
    (tmp_path / "jane-smith-2026-11-20.json").write_text(json.dumps(_notice()), encoding="utf-8")
    notices, problems = generate_notices.load_notices(tmp_path)
    assert not problems and len(notices) == 1
    html = generate_notices.render_notice(notices[0])
    assert "<script>x" not in html and "&lt;script&gt;" in html
    assert "Jane Smith, 84, Heywood" in html and "15 November 2026" in html
    assert "free, forever" in generate_notices.render_index(notices)


def test_unverified_notice_is_never_published(tmp_path):
    (tmp_path / "jane-smith-2026-11-20.json").write_text(json.dumps(_notice(verified_with="")), encoding="utf-8")
    notices, problems = generate_notices.load_notices(tmp_path)
    assert notices == [] and "verified_with" in problems[0]


def test_empty_notices_index_renders():
    html = generate_notices.render_index([])
    assert "No notices have been published yet" in html and not banned_in_value(html)
