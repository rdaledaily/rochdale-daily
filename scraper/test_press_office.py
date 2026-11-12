"""Press releases name the press office that issued them (editor's rule, 12 Nov 2026)."""
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import check_data_files as cdf
import manual_articles as ma

NOW = datetime(2026, 11, 12, 22, 0, tzinfo=timezone.utc)
BASE = {
    "slug": "middleton-man-charged-assault",
    "title": "Middleton man charged with assaulting an emergency worker",
    "body": "A Middleton man has been charged.\\n\\nSource: Greater Manchester Police press release issued on 12 November 2026.",
    "category": "crime",
    "area": "middleton",
    "published_at": "2026-11-12T10:00:00Z",
    "source_name": "Greater Manchester Police",
}


def test_press_office_becomes_the_source():
    record = ma._normalise(dict(BASE, press_office="Greater Manchester Police press office"), NOW)
    assert record["source_name"] == "Greater Manchester Police press office"
    assert record["source_names"] == ["Greater Manchester Police press office", "Greater Manchester Police"]
    assert record["press_release"] is True


def test_story_without_press_office_keeps_its_source():
    record = ma._normalise(dict(BASE, body="A statement from a resident."), NOW)
    assert record["source_name"] == "Greater Manchester Police" and "press_office" not in record



def test_press_office_is_shown_on_the_page():
    import generate_pages as gp
    record = ma._normalise(dict(BASE, press_office="Greater Manchester Police press office"), NOW)
    page = gp.render_article_page(record, [record])
    assert "Press release from Greater Manchester Police press office" in page
    plain = ma._normalise(dict(BASE), NOW)
    assert "Press release from" not in gp.render_article_page(plain, [plain])

def run_validator(entry):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "manual_articles.d").mkdir()
        (root / "manual_articles.d" / "story.json").write_text(json.dumps(entry), encoding="utf-8")
        old_root, old_errors = cdf.REPO_ROOT, list(cdf.problems)
        cdf.REPO_ROOT = root
        cdf.problems.clear()
        try:
            cdf.check_press_offices()
            return list(cdf.problems)
        finally:
            cdf.REPO_ROOT = old_root
            cdf.problems[:] = old_errors


def test_validator_requires_press_office_for_a_press_release():
    errors = run_validator(BASE)
    assert errors and "press_office" in errors[0]
    assert run_validator(dict(BASE, press_office="Greater Manchester Police press office")) == []


def test_flagged_press_release_without_office_fails():
    entry = dict(BASE, body="A Middleton man has been charged.", press_release=True)
    assert run_validator(entry)


def test_saying_no_release_was_published_is_not_a_press_release():
    entry = dict(BASE, body="No standalone press release about the visit had been published.")
    assert run_validator(entry) == []


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
        raise SystemExit(f"{len(failures)} press-office test(s) failed")
    print("all press-office tests passed")
