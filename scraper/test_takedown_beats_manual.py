"""A deliberate takedown always wins over a manual article file.

Regression for 24 Oct 2026: two taken-down editorial stories were re-injected
from manual_articles.d after the blocklist filter, so they stayed in
articles.json and on the section pages while their pages were deleted.
Run: python -m pytest -q scraper/test_takedown_beats_manual.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _site(blocked):
    root = Path(tempfile.mkdtemp())
    (root / "manual_articles.d").mkdir()
    for slug in ("kept-story", "taken-down-story"):
        (root / "manual_articles.d" / f"{slug}.json").write_text(json.dumps({
            "slug": slug, "title": slug.replace("-", " ").title(), "body": "A paragraph of text.",
            "category": "news", "published_at": "2026-10-20T10:00:00Z", "status": "published",
        }), encoding="utf-8")
    (root / "articles.json").write_text("[]", encoding="utf-8")
    (root / "story_blocklist.json").write_text(json.dumps({"title_patterns": [], "source_urls": [], "slugs": blocked}), encoding="utf-8")
    return root


def test_loader_skips_taken_down_manual_story():
    import manual_articles
    root = _site(["taken-down-story"])
    cwd = os.getcwd()
    try:
        os.chdir(root)
        slugs = [r["slug"] for r in manual_articles.load_manual_article_records()]
    finally:
        os.chdir(cwd)
    assert "kept-story" in slugs and "taken-down-story" not in slugs


def test_verifier_does_not_require_taken_down_story():
    import verify_manual_publication as v
    root = _site(["taken-down-story"])
    cwd = os.getcwd()
    try:
        os.chdir(root)
        slugs = {v.canonical_source_slug(r) for r in v.source_entries()}
    finally:
        os.chdir(cwd)
    assert slugs == {"kept-story"}
