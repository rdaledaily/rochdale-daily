"""Tests for article_gate.py — run as: python scraper/test_article_gate.py"""
from __future__ import annotations

import copy

from article_gate import gate_articles, normalise_article


def manual(**overrides) -> dict:
    base = {
        "title": "Test story",
        "slug": "test-story",
        "published_at": "2026-07-11T00:00:00Z",
        "scraped_at": "2026-07-11T00:00:00Z",
        "area": "rochdale-borough",
        "category": "crime",
        "content_html": "<p>Body.</p>",
    }
    base.update(overrides)
    return base


def test_midnight_manual_stamp_fixed_once_and_idempotent() -> None:
    notes: list[str] = []
    fixed = normalise_article(manual(), notes)
    assert fixed is not None
    assert "T00:00:00" not in fixed["published_at"]
    # A date-only stamp becomes NOON of its own stated day: deterministic,
    # idempotent, and it never shifts the story across midnight onto the
    # wrong date the way restamping to ingestion time could.
    assert fixed["published_at"] == "2026-07-11T12:00:00Z"
    # Second pass must not re-stamp.
    stamped = fixed["published_at"]
    second = normalise_article(copy.deepcopy(fixed), [])
    assert second is not None and second["published_at"] == stamped


def test_scraper_records_never_restamped() -> None:
    notes: list[str] = []
    record = manual(publication_route="ai-grounded-rewrite")
    fixed = normalise_article(record, notes)
    assert fixed is not None
    assert fixed["published_at"] == "2026-07-11T00:00:00Z"


def test_area_alias_and_unknown_fallback() -> None:
    fixed = normalise_article(manual(), [])
    assert fixed is not None and fixed["area"] == "rochdale"
    weird = normalise_article(manual(area="atlantis"), [])
    assert weird is not None and weird["area"] == "rochdale"
    kept = normalise_article(manual(area="milnrow"), [])
    assert kept is not None and kept["area"] == "milnrow"


def test_unknown_category_falls_back_to_news() -> None:
    fixed = normalise_article(manual(category="scandal"), [])
    assert fixed is not None and fixed["category"] == "news"
    ok = normalise_article(manual(category="environment"), [])
    assert ok is not None and ok["category"] == "environment"


def test_fact_table_drops_false_mp_claim() -> None:
    bad = manual(content_html="<p>Rochdale MP Rupert Lowe said today...</p>")
    kept, notes = gate_articles([bad])
    assert kept == []
    assert any("DROPPED" in note for note in notes)


def test_true_mp_claim_survives() -> None:
    good = manual(content_html="<p>Rochdale MP Paul Waugh said today...</p>")
    kept, _ = gate_articles([good])
    assert len(kept) == 1


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    raise SystemExit(1 if failures else 0)
