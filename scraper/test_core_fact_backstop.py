"""Regression tests for core_fact_backstop and its article_gate hook.

12 Nov 2026: Roch Valley Radio corrected an arrested man's age from "in his
50s" to 39 after Rochdale Daily had published. The story kept the old age, and
when it later fell out of the feed its page stayed public. These tests pin both
fixes: a changed source is re-checked, and a failed story loses its page.
"""
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import article_gate
import core_fact_backstop as backstop

NOW = datetime(2026, 11, 11, 22, 0, tzinfo=timezone.utc)
URL = "https://www.rochvalleyradio.com/news-features/4/crime/1429/man-arrested"
ORIGINAL = (
    "Man arrested for possessing an imitation firearm at Rochdale Armistice Day event. "
    "A man in his 50s has been arrested after police found what they believe to be an air "
    "pistol near a remembrance ceremony in Rochdale town centre. He was arrested on suspicion "
    "of possession of an imitation firearm and remains in custody."
)
CORRECTED = ORIGINAL.replace("A man in his 50s", "A 39-year-old man")


def story(**extra):
    row = {
        "slug": "man-arrested-for-possessing-imitation-firearm",
        "title": "Man arrested for possessing imitation firearm at Rochdale Armistice Day event",
        "excerpt": "A man in his 50s has been arrested near a remembrance ceremony in Rochdale.",
        "content_html": "<p>A man in his 50s was arrested on suspicion of possession of an imitation firearm near a remembrance ceremony in Rochdale town centre.</p>",
        "source_urls": [URL],
        "category": "crime",
        "area": "rochdale",
        "publication_route": "ai-grounded-rewrite",
        "source_kind": "article",
        "first_published_at": "2026-11-11T16:00:40Z",
        "published_at": "2026-11-11T16:00:40Z",
    }
    row.update(extra)
    return row


def test_story_matching_its_source_passes():
    row = story()
    counts = backstop.run([row], now=NOW, fetcher=lambda url: ORIGINAL, limit=10)
    assert row["core_fact_check"]["status"] == "passed", row["core_fact_check"]
    assert counts["passed"] == 1


def test_source_corrected_after_publication_fails_the_story():
    row = story()
    backstop.run([row], now=NOW, fetcher=lambda url: ORIGINAL, limit=10)
    later = NOW + timedelta(hours=1)
    counts = backstop.run([row], now=later, fetcher=lambda url: CORRECTED, limit=10)
    verdict = row["core_fact_check"]
    assert verdict["status"] == "failed"
    assert any("50s" in issue for issue in verdict["issues"])
    assert verdict.get("source_changed_at")
    assert counts["changed_sources"] == 1


def test_old_checked_story_is_not_refetched():
    row = story()
    backstop.run([row], now=NOW, fetcher=lambda url: ORIGINAL, limit=10)
    calls = []
    backstop.run([row], now=NOW + timedelta(days=5), fetcher=lambda url: calls.append(url) or ORIGINAL, limit=10)
    assert calls == []


def test_partial_capture_never_fails_a_story():
    # A fact may come from the source that could not be read.
    row = story(source_urls=[URL, "https://www.rochdaletimes.co.uk/other-report/"])

    def fetcher(url):
        if "rochdaletimes" in url:
            raise ConnectionError("timeout")
        return CORRECTED

    backstop.run([row], now=NOW, fetcher=fetcher, limit=10)
    assert row["core_fact_check"]["status"] == "unchecked"
    assert "capture failed" in row["core_fact_check"]["reason"]



def test_failed_capture_is_retried_then_checked():
    row = story()

    def down(url):
        raise ConnectionError("timeout")

    backstop.run([row], now=NOW, fetcher=down, limit=10)
    assert row["core_fact_check"]["status"] == "unchecked"
    backstop.run([row], now=NOW + timedelta(days=5), fetcher=lambda url: CORRECTED, limit=10)
    assert row["core_fact_check"]["status"] == "failed"

def test_unresolvable_google_news_link_is_reported_not_guessed():
    row = story(source_urls=["https://news.google.com/rss/articles/abc"])

    def fetcher(url):
        raise ValueError("Google News link did not resolve to a publisher page")

    backstop.run([row], now=NOW, fetcher=fetcher, limit=10)
    assert row["core_fact_check"]["status"] == "unchecked"
    assert "capture failed" in row["core_fact_check"]["reason"]


def test_resolved_google_news_link_is_checked():
    row = story(source_urls=["https://news.google.com/rss/articles/abc"])
    backstop.run([row], now=NOW, fetcher=lambda url: CORRECTED, limit=10)
    assert row["core_fact_check"]["status"] == "failed"


def test_cookie_wall_capture_is_not_treated_as_the_source():
    row = story()
    backstop.run([row], now=NOW, fetcher=lambda url: "We use cookies to give you the best experience. Accept cookies.", limit=10)
    assert row["core_fact_check"]["status"] == "unchecked"


def test_manual_and_editorial_stories_are_left_alone():
    row = story(manual_article=True, editorial_lock=True)
    backstop.run([row], now=NOW, fetcher=lambda url: CORRECTED, limit=10)
    assert "core_fact_check" not in row


def test_gate_drops_failed_story_and_removes_its_page():
    row = story()
    backstop.run([row], now=NOW, fetcher=lambda url: CORRECTED, limit=10)
    assert row["core_fact_check"]["status"] == "failed"
    kept, notes = article_gate.gate_articles([row])
    assert kept == []
    assert any(article_gate.CORE_FACT_HOLD in note for note in notes)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "articles").mkdir()
        page = root / "articles" / f"{row['slug']}.html"
        page.write_text("<html>old copy</html>", encoding="utf-8")
        listing = root / "index.html"
        listing.write_text(f'<ul><li><a href="/articles/{row["slug"]}.html">Old</a></li></ul>', encoding="utf-8")
        held = article_gate.hold_failed_pages([row], root)
        assert held == [row["slug"]]
        assert not page.exists()
        assert row["slug"] not in listing.read_text(encoding="utf-8")
        log = json.loads((root / "reports" / "core_fact_holds.json").read_text(encoding="utf-8"))
        assert log[-1]["slug"] == row["slug"] and log[-1]["issues"]


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
        raise SystemExit(f"{len(failures)} core-fact backstop test(s) failed")
    print("all core-fact backstop tests passed")
