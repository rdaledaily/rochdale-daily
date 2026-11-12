"""dateModified, article:modified_time and the sitemap change only when a story does.

12 Nov 2026: in 60 builds, last_updated_at changed 683 times and 603 of those
had no change to the text (every What's On listing, re-stamped on each scrape).
JSON-LD dateModified passed that straight to Google. These tests pin the fix and
the homepage "Recently updated" links that send crawlers to real updates.
"""
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import article_gate
import frontpage_pipeline as fp
import generate_pages as gp
import recently_updated as ru

PUBLISHED = "2026-11-10T09:00:00Z"
NOW = datetime(2026, 11, 12, 22, 0, tzinfo=timezone.utc)


def automated(**extra):
    row = {"slug": "s", "title": "T", "first_published_at": PUBLISHED, "published_at": PUBLISHED,
           "last_updated_at": "2026-11-12T21:40:00Z", "scraped_at": "2026-11-12T21:40:00Z",
           "source_kind": "article", "category": "news", "area": "rochdale", "content_html": "<p>x</p>"}
    row.update(extra)
    return row


def test_rescrape_is_not_a_modification():
    assert gp.last_modified_at(automated()) == PUBLISHED


def test_correction_is_a_modification():
    row = automated(corrections=[{"date": "2026-11-12", "note": "Corrected."}])
    assert gp.last_modified_at(row) == "2026-11-12"


def test_newsdesk_edit_is_a_modification():
    row = automated(manual_article=True, last_updated_at="2026-11-11T12:00:00Z")
    assert gp.last_modified_at(row) == "2026-11-11T12:00:00Z"


def test_live_update_timestamp_is_the_modification():
    row = automated(live_story=True, live_updates=[{"timestamp": "2026-11-11T08:00:00Z"}, {"timestamp": "2026-11-11T15:00:00Z"}])
    assert gp.last_modified_at(row) == "2026-11-11T15:00:00Z"


def test_real_content_change_is_a_modification():
    assert gp.last_modified_at(automated(content_updated_at="2026-11-11T10:00:00Z")) == "2026-11-11T10:00:00Z"


def test_json_ld_keeps_published_and_reports_honest_modified():
    row = automated(corrections=[{"date": "2026-11-12", "note": "Corrected."}])
    data = json.loads(gp.json_ld(row, "https://rochdaledaily.co.uk/articles/s", ""))
    article = next(n for n in data["@graph"] if n.get("@type") in ("NewsArticle", "Article"))
    assert article["datePublished"] == PUBLISHED
    assert article["dateModified"] == "2026-11-12"
    plain = json.loads(gp.json_ld(automated(), "https://rochdaledaily.co.uk/articles/s", ""))
    plain_article = next(n for n in plain["@graph"] if n.get("@type") in ("NewsArticle", "Article"))
    assert plain_article["dateModified"] == PUBLISHED


def test_gate_no_longer_turns_a_scrape_into_an_update():
    row = automated(last_updated_at=PUBLISHED, scraped_at="2026-11-12T21:40:00Z")
    kept, _ = article_gate.gate_articles([row])
    assert kept[0]["last_updated_at"] == PUBLISHED


def test_unchanged_event_keeps_its_update_date():
    previous = {"title": "Panto", "excerpt": "e", "content_html": "<p>c</p>", "event_start_at": "2026-12-01T19:00:00Z",
                "event_location": "Heywood Civic", "last_updated_at": "2026-11-01T10:00:00Z"}
    rescraped = dict(previous, last_updated_at="2026-11-12T21:40:00Z", scraped_at="2026-11-12T21:40:00Z")
    assert fp._event_fingerprint(previous) == fp._event_fingerprint(rescraped)
    moved = dict(rescraped, event_start_at="2026-12-02T19:00:00Z")
    assert fp._event_fingerprint(previous) != fp._event_fingerprint(moved)


def test_homepage_links_recently_updated_stories_only():
    rows = [
        automated(slug="corrected", title="Corrected story", corrections=[{"date": "2026-11-12", "note": "Corrected."}]),
        automated(slug="rescraped", title="Only re-scraped"),
        automated(slug="no-page", title="No page", corrections=[{"date": "2026-11-12", "note": "Corrected."}]),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "articles").mkdir()
        for slug in ("corrected", "rescraped"):
            (root / "articles" / f"{slug}.html").write_text("<html></html>", encoding="utf-8")
        chosen = ru.choose(rows, NOW, root)
        assert [r["slug"] for r in chosen] == ["corrected"]
        index = root / "index.html"
        index.write_text("<main>\n<!-- WEEKLY_LOCAL_NEWS_END -->\n</main>", encoding="utf-8")
        assert ru.refresh(index, rows, NOW, root) == 1
        page = index.read_text(encoding="utf-8")
        assert '<a href="/articles/corrected">Corrected story</a>' in page and "Corrected <time" in page
        assert "rescraped" not in page
        ru.refresh(index, rows, NOW, root)
        assert index.read_text(encoding="utf-8").count(ru.START) == 1


if __name__ == "__main__":
    failures = []
    for name, test in sorted(globals().items()):
        if name.startswith("test_") and callable(test):
            try:
                test()
                print(f"ok   {name}")
            except AssertionError as exc:
                failures.append(name)
                print(f"FAIL {name}: {exc}")
    if failures:
        raise SystemExit(f"{len(failures)} honest-modified-date test(s) failed")
    print("all honest-modified-date tests passed")
