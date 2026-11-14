"""One release, one page: syndicated copies of the same press release.

Fixtures are the live records of 14 Nov 2026 (see story_identity.syndicated_twin).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import story_identity as si  # noqa: E402
from editorial_twins import split_editorial_twins  # noqa: E402

FIX = json.loads((HERE / "fixtures_syndicated_twins.json").read_text(encoding="utf-8"))
TOY_ED, TOY_COUNCIL, TOY_IYA = FIX["toy_editor"], FIX["toy_council"], FIX["toy_inyourarea"]


def test_three_copies_of_the_toy_appeal_release_are_twins():
    assert si.syndicated_twin(TOY_ED, TOY_COUNCIL)
    assert si.syndicated_twin(TOY_ED, TOY_IYA)
    assert si.syndicated_twin(TOY_COUNCIL, TOY_IYA)
    # Under both existing bars, which is why they ran together.
    assert not si.same_story(TOY_COUNCIL, TOY_IYA)
    assert not si.editorial_twin(TOY_ED, TOY_COUNCIL)


def test_lookalikes_in_the_same_score_band_are_left_alone():
    # Different contract awards: same wording, no shared headline entity.
    assert not si.syndicated_twin(FIX["contract_1"], FIX["contract_2"])
    # Same church, different notices: shared entity, no shared fact.
    assert not si.syndicated_twin(FIX["church_service"], FIX["church_notices"])
    # An early report and the editor's later one with new figures.
    assert not si.syndicated_twin(FIX["sleepout_editor"], FIX["sleepout_bot"])


def test_two_editor_stories_are_never_twins():
    assert si.is_editor_record(TOY_ED) and si.is_editor_record(FIX["toy_roundup_editor"])
    assert not si.syndicated_twin(TOY_ED, FIX["toy_roundup_editor"])
    assert not si.syndicated_twin(TOY_ED, {**TOY_COUNCIL, "manual_article": True})


def test_outside_seven_days_is_not_a_twin():
    late = {**TOY_IYA, "published_at": "2026-11-25T09:00:00Z", "first_published_at": "2026-11-25T09:00:00Z"}
    assert not si.syndicated_twin(TOY_COUNCIL, late)


def test_editor_version_is_kept_and_copies_point_to_it():
    feed = [TOY_IYA, TOY_ED, FIX["toy_roundup_editor"], TOY_COUNCIL, FIX["contract_1"], FIX["contract_2"]]
    kept, twins = split_editorial_twins(feed)
    assert [r["slug"] for r in kept] == [
        TOY_ED["slug"], FIX["toy_roundup_editor"]["slug"], FIX["contract_1"]["slug"], FIX["contract_2"]["slug"],
    ]
    assert sorted((t["slug"], k["slug"]) for t, k in twins) == sorted([
        (TOY_IYA["slug"], TOY_ED["slug"]), (TOY_COUNCIL["slug"], TOY_ED["slug"]),
    ])


def test_without_an_editor_version_the_first_published_is_kept():
    kept, twins = split_editorial_twins([TOY_IYA, TOY_COUNCIL])
    assert [r["slug"] for r in kept] == [TOY_COUNCIL["slug"]]
    assert [(t["slug"], k["slug"]) for t, k in twins] == [(TOY_IYA["slug"], TOY_COUNCIL["slug"])]
