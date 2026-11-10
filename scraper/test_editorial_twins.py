"""The pipeline's copy of a story the editor already published leaves the feed.

Fixtures are the real records from 10 Nov 2026 ("Why have you repeated this
story ... remove duplicates as a rule").
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import story_identity as si  # noqa: E402
from editorial_twins import mark_ledger, retire_twins, split_editorial_twins  # noqa: E402

FIX = json.loads((HERE / "fixtures_editorial_twins.json").read_text(encoding="utf-8"))
DRUG_BOT = FIX["man-jailed-for-over-a-decade-for-role-in-rochdale-drug-supply"]
DRUG_ED = FIX["rochdale-adam-drug-line-haider-ali-jailed"]
GOLD_BOT = FIX["police-warn-of-rising-family-gold-burglaries-in-rochdale-and-surrounding-areas"]
GOLD_ED = FIX["police-warn-rochdale-homes-family-gold-burglaries-darker-nights"]
CB_BOT = FIX["future-of-college-bank-towers-uncertain-as-renovation-could-take-over-a-decade"]
CB_ED = FIX["college-bank-seven-sisters-housing-future"]


def _shift(record, hours):
    when = datetime.fromisoformat(record["published_at"].replace("Z", "+00:00")) + timedelta(hours=hours)
    return {**record, "published_at": when.isoformat().replace("+00:00", "Z")}


def test_both_reported_pairs_are_twins():
    assert si.editorial_twin(DRUG_ED, DRUG_BOT)
    assert si.editorial_twin(GOLD_ED, GOLD_BOT)
    # ...even though the general matcher keeps them apart (its bar is unchanged).
    assert not si.same_story(DRUG_ED, DRUG_BOT)
    assert not si.same_story(GOLD_ED, GOLD_BOT)


def test_direction_matters_and_two_editor_stories_never_twin():
    assert not si.editorial_twin(DRUG_BOT, DRUG_ED)
    assert not si.editorial_twin(DRUG_ED, {**DRUG_BOT, "manual_article": True})


def test_window_and_unrelated_pairs():
    assert not si.editorial_twin(DRUG_ED, _shift(DRUG_BOT, 60))
    assert not si.editorial_twin(DRUG_ED, GOLD_BOT)
    # Next-highest live pair on 10 Nov (0.48): a different College Bank piece.
    assert si.is_editor_record(CB_ED) and not si.is_editor_record(CB_BOT)
    assert not si.editorial_twin(CB_ED, {**CB_BOT, "published_at": CB_ED["published_at"]})


def test_split_keeps_editor_and_everything_else():
    feed = [DRUG_BOT, DRUG_ED, GOLD_BOT, GOLD_ED, CB_BOT]
    kept, twins = split_editorial_twins(feed)
    slugs = [r["slug"] for r in kept]
    assert slugs == [DRUG_ED["slug"], GOLD_ED["slug"], CB_BOT["slug"]]
    assert [(t["slug"], e["slug"]) for t, e in twins] == [
        (DRUG_BOT["slug"], DRUG_ED["slug"]),
        (GOLD_BOT["slug"], GOLD_ED["slug"]),
    ]
    assert kept[0] is DRUG_ED  # the editor's record is not edited


def test_retire_redirects_to_editor_page_and_holds_ledger(tmp_path):
    pages = tmp_path / "articles"
    pages.mkdir()
    (pages / f"{DRUG_BOT['slug']}.html").write_text("<html>twin</html>", encoding="utf-8")
    (pages / f"{DRUG_ED['slug']}.html").write_text("<html>editor</html>", encoding="utf-8")
    redirects = tmp_path / "_redirects"
    redirects.write_text("/rochdale / 301\n", encoding="utf-8")
    ledger = tmp_path / "rewrite_ledger.json"
    ledger.write_text(json.dumps({"entries": {
        DRUG_BOT["source_url"]: {"outcome": "published", "urls": [DRUG_BOT["source_url"]]},
        "https://example.org/other": {"outcome": "published", "urls": []},
    }}), encoding="utf-8")

    report = retire_twins([(DRUG_BOT, DRUG_ED)], pages_dir=pages, redirects_path=redirects, ledger_path=ledger)

    assert report["pages_removed"] == 1 and report["redirects_written"] == 1
    assert not (pages / f"{DRUG_BOT['slug']}.html").exists()
    assert (pages / f"{DRUG_ED['slug']}.html").exists()
    rules = redirects.read_text(encoding="utf-8")
    assert f"/articles/{DRUG_BOT['slug']} /articles/{DRUG_ED['slug']} 301" in rules
    assert f"/articles/{DRUG_BOT['slug']}.html /articles/{DRUG_ED['slug']} 301" in rules
    entries = json.loads(ledger.read_text(encoding="utf-8"))["entries"]
    assert entries[DRUG_BOT["source_url"]]["outcome"] == "editorial_twin"
    assert entries["https://example.org/other"]["outcome"] == "published"

    # Idempotent: a second run writes nothing new.
    again = retire_twins([(DRUG_BOT, DRUG_ED)], pages_dir=pages, redirects_path=redirects, ledger_path=ledger)
    assert again["redirects_written"] == 0 and again["ledger_entries_marked"] == 0
    assert redirects.read_text(encoding="utf-8") == rules


def test_existing_redirect_rule_wins(tmp_path):
    redirects = tmp_path / "_redirects"
    redirects.write_text(f"/articles/{DRUG_BOT['slug']} /news/crime 301\n", encoding="utf-8")
    report = retire_twins([(DRUG_BOT, DRUG_ED)], pages_dir=tmp_path, redirects_path=redirects,
                          ledger_path=tmp_path / "missing.json")
    assert report["redirects_written"] == 0
    assert mark_ledger(tmp_path / "missing.json", [(DRUG_BOT, DRUG_ED)]) == 0
