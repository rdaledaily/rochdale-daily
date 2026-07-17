"""Regression tests for article_gate.py.

Run from the repository root with:

    python scraper/test_article_gate.py
"""
from __future__ import annotations

import copy
import traceback
from typing import Any, Callable

from article_gate import gate_articles, normalise_article


def manual(**overrides: Any) -> dict[str, Any]:
    """Return a representative manually-entered article record."""
    article: dict[str, Any] = {
        "title": "Test story",
        "slug": "test-story",
        "published_at": "2026-07-11T00:00:00Z",
        "scraped_at": "2026-07-11T00:00:00Z",
        "area": "rochdale-borough",
        "category": "crime",
        "content_html": "<p>Body.</p>",
    }
    article.update(overrides)
    return article


def test_midnight_manual_stamp_fixed_once_and_idempotent() -> None:
    notes: list[str] = []
    fixed = normalise_article(manual(), notes)

    assert fixed is not None
    assert fixed["published_at"] == "2026-07-11T12:00:00Z"
    assert fixed["first_published_at"] == "2026-07-11T12:00:00Z"
    assert "T00:00:00" not in fixed["published_at"]

    stamped = fixed["published_at"]
    second = normalise_article(copy.deepcopy(fixed), [])

    assert second is not None
    assert second["published_at"] == stamped
    assert second["first_published_at"] == stamped


def test_scraper_records_never_restamped() -> None:
    notes: list[str] = []
    record = manual(publication_route="ai-grounded-rewrite")
    fixed = normalise_article(record, notes)

    assert fixed is not None
    assert fixed["published_at"] == "2026-07-11T00:00:00Z"
    assert fixed["first_published_at"] == "2026-07-11T00:00:00Z"


def test_area_alias_and_unknown_fallback() -> None:
    aliased = normalise_article(manual(), [])
    unknown = normalise_article(manual(area="atlantis"), [])
    canonical = normalise_article(manual(area="milnrow"), [])
    whitworth = normalise_article(manual(area="whitworth"), [])

    assert aliased is not None and aliased["area"] == "rochdale"
    assert unknown is not None and unknown["area"] == "rochdale"
    assert canonical is not None and canonical["area"] == "milnrow"
    assert whitworth is not None and whitworth["area"] == "whitworth"


def test_unknown_category_falls_back_to_news() -> None:
    unknown = normalise_article(manual(category="scandal"), [])
    canonical = normalise_article(manual(category="environment"), [])
    alias = normalise_article(manual(category="sports"), [])

    assert unknown is not None and unknown["category"] == "news"
    assert canonical is not None and canonical["category"] == "environment"
    assert alias is not None and alias["category"] == "sport"


def test_two_argument_api_loads_blocklist_implicitly() -> None:
    fixed = normalise_article(manual(), [])

    assert fixed is not None
    assert fixed["slug"] == "test-story"


def test_explicit_blocklist_argument_remains_supported() -> None:
    fixed = normalise_article(manual(), [], [])

    assert fixed is not None
    assert fixed["slug"] == "test-story"


def test_missing_title_is_dropped() -> None:
    notes: list[str] = []
    fixed = normalise_article(manual(title=""), notes)

    assert fixed is None
    assert any("missing title" in note for note in notes)


def test_missing_meaningful_content_is_dropped() -> None:
    notes: list[str] = []
    fixed = normalise_article(
        manual(content_html="", excerpt="", summary=""),
        notes,
    )

    assert fixed is None
    assert any("missing meaningful article content" in note for note in notes)


def test_fact_table_drops_false_mp_claim() -> None:
    bad = manual(content_html="<p>Rochdale MP Rupert Lowe said today...</p>")
    kept, notes = gate_articles([bad])

    assert kept == []
    assert any("verified current MP" in note for note in notes)


def test_true_mp_claim_survives() -> None:
    good = manual(content_html="<p>Rochdale MP Paul Waugh said today...</p>")
    kept, _ = gate_articles([good])

    assert len(kept) == 1


def test_former_mp_reference_is_not_treated_as_current_claim() -> None:
    historical = manual(
        content_html="<p>Former Rochdale MP Simon Danczuk attended the event.</p>"
    )
    kept, _ = gate_articles([historical])

    assert len(kept) == 1


def test_duplicate_slugs_are_removed() -> None:
    first = manual(title="First version", slug="same-story")
    second = manual(title="Second version", slug="same-story")

    kept, notes = gate_articles([first, second])

    assert len(kept) == 1
    assert kept[0]["slug"] == "same-story"
    assert any("duplicate slug" in note for note in notes)


def test_police_matter_is_preserved_and_not_inferred_from_category() -> None:
    explicit = normalise_article(manual(police_matter=True), [])
    absent = normalise_article(manual(category="crime"), [])

    assert explicit is not None and explicit["police_matter"] is True
    assert absent is not None and absent["police_matter"] is False


def _run_tests() -> int:
    failures = 0
    tests: list[tuple[str, Callable[[], None]]] = sorted(
        (
            (name, value)
            for name, value in globals().items()
            if name.startswith("test_") and callable(value)
        ),
        key=lambda item: item[0],
    )

    for name, test in tests:
        try:
            test()
        except AssertionError as exc:
            failures += 1
            detail = str(exc) or "assertion failed"
            print(f"FAIL {name}: {detail}")
        except Exception:
            failures += 1
            print(f"ERROR {name}")
            traceback.print_exc()
        else:
            print(f"PASS {name}")

    print(
        f"{len(tests) - failures} passed, {failures} failed, "
        f"{len(tests)} total"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run_tests())
