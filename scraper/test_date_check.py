"""A weekday that the calendar contradicts never publishes.

Run: python scraper/test_date_check.py   (or pytest)
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import date_check as dc  # noqa: E402


def test_wrong_pairs_found():
    assert dc.weekday_errors("on Saturday, September 10, 2026", "2026-09-01")
    assert dc.weekday_errors("this Saturday, 12 November", "2026-11-12")
    assert dc.weekday_errors("Tuesday, 17 November 2027", "2026-11-02")
    assert dc.weekday_errors("on Sunday, 31 August 2026", "2026-08-31")


def test_right_pairs_pass():
    assert not dc.weekday_errors("this Saturday, 14 November", "2026-11-12")
    assert not dc.weekday_errors("Tuesday 17 November 2026 and Friday, 6 November", "2026-11-02")
    assert not dc.weekday_errors("on Saturday, September 5, 2026", "2026-09-01")
    # No year: a date that is right in the following year is accepted.
    assert not dc.weekday_errors("by Friday 7 May", "2026-11-10")
    # History with its own year.
    assert not dc.weekday_errors("on Tuesday, 6 June 1944", "2026-06-06")


def test_corrections_block_ignored():
    page = ('<p>On Saturday 14 November.</p><section class="article-corrections"><h3>Corrections</h3>'
            '<p>The match was dated Saturday 12 November.</p></section>')
    assert not dc.weekday_errors(page, "2026-11-12")


def test_quality_gate_blocks_wrong_weekday():
    import editorial_upgrade as eu
    marker = dc.ISSUE_MARKER
    assert any(marker in m for m in eu.INTEGRITY_ISSUE_MARKERS)
    issue = dc.issue_text(dc.weekday_errors("on Saturday, September 10, 2026", "2026-09-01"))
    assert eu.integrity_issues([issue]) == [issue]


def test_repository_clean():
    found = dc.scan()
    assert not found, found


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            except AssertionError as exc:
                failed += 1
                print(f"FAIL {name} {exc}")
    sys.exit(1 if failed else 0)
