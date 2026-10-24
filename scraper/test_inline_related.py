"""In-text Read more links: strict, never crime, never stacked.

Run: python -m pytest -q scraper/test_inline_related.py
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import inline_related as R  # noqa: E402

BODY = "".join(f"<p>Paragraph {n}.</p>" for n in range(1, 8))


def make_root(articles, archive=()):
    root = Path(tempfile.mkdtemp())
    (root / "articles").mkdir()
    (root / "_redirects").write_text("/articles/retired-hollingworth /news/ 301\n", encoding="utf-8")
    (root / "archive-index.json").write_text(json.dumps(list(archive)), encoding="utf-8")
    for entry in archive:
        slug = entry["slug"]
        (root / "articles" / f"{slug}.html").write_text(
            f'<html><head><link rel="canonical" href="https://rochdaledaily.co.uk/articles/{slug}.html"></head></html>',
            encoding="utf-8")
    return root


def story(slug, title, **extra):
    record = {"slug": slug, "title": title, "category": "environment", "content_html": BODY}
    record.update(extra)
    return record


# Rarity scores are tuned for a paper-sized corpus (~2,100 headlines), so the
# tests use one too. Common words recur; "Hollingworth" stays rare.
_COMMON = "family road warning council plans homes school community event football business".split()
FILLER = [story(f"filler-{n}", f"{_COMMON[n % 11].title()} {_COMMON[(n * 7) % 11]} update number {n}") for n in range(2100)]


def test_related_requires_distinctive_shared_words():
    a = story("lake-volunteers", "Volunteers needed at Hollingworth Lake visitor centre")
    b = story("lake-guide", "Visitor guide to Hollingworth Lake released")
    c = story("road-family", "Family road warning issued in October")
    idx = R.Index([a, b, c] + FILLER, make_root([]))
    assert [s for s, _ in idx.related(a)] == ["lake-guide"]
    assert idx.related(c) == []                       # only common words shared


def test_crime_and_sensitive_excluded_both_ways():
    a = story("lake-a", "Hollingworth Lake visitor centre reopens")
    crime = story("lake-crime", "Man charged after Hollingworth Lake visitor centre theft", category="crime")
    death = story("lake-death", "Inquest into Hollingworth Lake visitor centre death")
    idx = R.Index([a, crime, death] + FILLER, make_root([]))
    assert idx.related(a) == []
    assert idx.related(crime) == []


def test_archive_targets_filtered_and_retired_skipped():
    a = story("lake-a", "Hollingworth Lake visitor centre reopens")
    archive = [
        {"slug": "lake-archive", "title": "Hollingworth Lake visitor centre to close for works", "category": "environment"},
        {"slug": "lake-social", "title": "Not a bad way to start a Wednesday! Our walk round Hollingworth Lake visitor centre", "category": "environment"},
        {"slug": "retired-hollingworth", "title": "Hollingworth Lake visitor centre news", "category": "environment"},
    ]
    idx = R.Index([a] + FILLER, make_root([a], archive))
    assert [s for s, _ in idx.related(a)] == ["lake-archive"]


def test_insert_positions_and_never_after_last_paragraph():
    a = story("lake-a", "Hollingworth Lake visitor centre reopens")
    others = [story("lake-1", "Hollingworth Lake Wave of Light walk returns"),
              story("lake-2", "Volunteers needed at Hollingworth Lake nature reserve"),
              story("lake-3", "Hollingworth Lake sailing club wins regional prize")]
    articles = [a] + others + FILLER
    R._CACHE.clear()
    R._CACHE[id(articles)] = R.Index(articles, make_root([]))
    out = R.insert(BODY, a, articles)
    assert out.count('class="rd-related-inline"') == 3
    assert out.index("Paragraph 2.</p>") < out.index("rd-related-inline") < out.index("Paragraph 3.")
    short = "<p>One.</p><p>Two.</p>"
    assert R.insert(short, a, articles).count("rd-related-inline") == 0


def test_render_read_back_does_not_stack():
    import generate_pages
    from archive_quality import article_body
    a = story("lake-a", "Hollingworth Lake visitor centre reopens")
    b = story("lake-b", "Hollingworth Lake visitor centre summer guide")
    articles = [dict(a), dict(b)] + FILLER
    R._CACHE.clear()
    R._CACHE[id(articles)] = R.Index(articles, make_root([]))
    record = dict(a)
    for _ in range(3):
        page = generate_pages.render_article_page(dict(record), articles)
        assert page.count('class="rd-related-inline"') == 1
        record["content_html"] = article_body(page)
        assert "rd-related-inline" not in record["content_html"]


def test_links_use_clean_urls():
    # 24 Oct 2026: ".html" links were rewritten by the theme step after
    # archive_quality had re-added them, so normalise_public_theme --check
    # failed and every publishing lane stopped.
    a = story("lake-a", "Hollingworth Lake visitor centre reopens")
    b = story("lake-b", "Hollingworth Lake visitor centre summer guide")
    articles = [a, b] + FILLER
    R._CACHE.clear()
    R._CACHE[id(articles)] = R.Index(articles, make_root([]))
    out = R.insert(BODY, a, articles)
    assert 'href="/articles/lake-b"' in out and ".html" not in out
