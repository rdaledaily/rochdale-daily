"""Corrections keep every source; nested hand-written files are validated (12 Nov 2026)."""
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import check_data_files as cdf
import manual_articles as ma

NOW = datetime(2026, 11, 12, 22, 0, tzinfo=timezone.utc)
ENTRY = {
    "slug": "man-charged-after-arrest",
    "title": "Man charged after Rochdale arrest",
    "body": "A man has been charged.",
    "category": "crime",
    "area": "rochdale",
    "published_at": "2026-11-11T10:00:00Z",
    "source_url": "https://www.rochvalleyradio.com/original",
    "source_urls": ["https://www.rochvalleyradio.com/original", "https://www.manchestereveningnews.co.uk/follow-up"],
}


def test_follow_up_report_is_published_as_a_source():
    record = ma._normalise(dict(ENTRY), NOW)
    assert record["source_urls"] == ENTRY["source_urls"]


def test_single_source_story_is_unchanged():
    record = ma._normalise({k: v for k, v in ENTRY.items() if k != "source_urls"}, NOW)
    assert record["source_urls"] == ["https://www.rochvalleyradio.com/original"]


def test_scrape_merge_keeps_the_follow_up():
    record = ma._normalise(dict(ENTRY), NOW)
    merged = ma._absorb_scraped_match(record, {"id": "x", "source_url": "https://www.rochdaletimes.co.uk/earlier"})
    assert "https://www.manchestereveningnews.co.uk/follow-up" in merged["source_urls"]


def test_validator_reads_dated_subfolders():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        nested = root / "manual_articles.d" / "2026" / "10"
        nested.mkdir(parents=True)
        (nested / "story.json").write_text(json.dumps(dict(ENTRY, body="Source: Zen Internet press release supplied to Rochdale Daily.")), encoding="utf-8")
        old_root, old = cdf.REPO_ROOT, list(cdf.problems)
        cdf.REPO_ROOT = root
        cdf.problems.clear()
        try:
            cdf.check_press_offices()
            assert cdf.problems and "manual_articles.d/2026/10/story.json" in cdf.problems[0]
        finally:
            cdf.REPO_ROOT = old_root
            cdf.problems[:] = old


def test_reserialised_event_markup_is_not_an_update():
    import frontpage_pipeline as fp

    stored = {"title": "Panto", "excerpt": "Fun & games", "content_html": '<p id="b" class="a">Dick Whittington at Heywood&nbsp;Civic</p>',
              "event_start_at": "2026-12-01T19:00:00Z", "event_location": "Heywood Civic"}
    rebuilt = dict(stored, excerpt="Fun &amp; games", content_html='<p class="a" id="b">Dick  Whittington at Heywood\u00a0Civic</p>')
    assert fp._event_fingerprint(stored) == fp._event_fingerprint(rebuilt)
    assert fp._event_fingerprint(stored) != fp._event_fingerprint(dict(stored, event_location="Rochdale Town Hall"))


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
        raise SystemExit(f"{len(failures)} test(s) failed")
    print("all source-url and nested-manual tests passed")
