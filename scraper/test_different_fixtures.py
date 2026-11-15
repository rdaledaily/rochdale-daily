"""Different opponents are different stories (story_identity.different_fixtures).

Fixtures are real records from the feed of 6 Nov 2026, when the league defeat
at Port Vale was folded into the Trophy defeat to Doncaster Rovers and a
"watch Port Vale v Rochdale" piece into the FA Cup preview against Fleetwood.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import story_identity as si  # noqa: E402

FIX = json.loads((HERE / "fixtures_different_fixtures.json").read_text(encoding="utf-8"))


def _sport(title: str, when: str = "2026-11-14T10:00:00Z", body: str = "") -> dict:
    return {"title": title, "content_html": f"<p>{body or title}.</p>", "category": "sport",
            "area": "rochdale", "published_at": when, "first_published_at": when}


def test_real_pairs_from_6_november_are_separate_stories():
    for left, right in (("port_vale_defeat", "trophy_defeat"), ("watch_port_vale", "fleetwood_preview")):
        assert si.different_fixtures(FIX[left], FIX[right])
        assert si.story_similarity(FIX[left], FIX[right]) == 0.0
        assert not si.ongoing_story_match(FIX[left], FIX[right])
        assert not si.same_story(FIX[left], FIX[right])


def test_opponents_are_read_from_the_headline():
    assert si.fixture_opponents(_sport("Accrington Stanley thrash Rochdale 5-0 in League Two clash")) == {"accrington stanley"}
    assert si.fixture_opponents(_sport("Rochdale falls to Crewe in 3-2 defeat in League Two")) == {"crewe"}
    assert si.fixture_opponents(_sport("Rochdale AFC Women to host Wythenshawe Town in league clash")) == {"wythenshawe town"}
    assert si.fixture_opponents(_sport("Ian Henderson set to break Rochdale AFC club appearance record")) == set()


def test_same_opponent_is_never_blocked():
    preview = _sport("Rochdale faces York City in League Two after dramatic title decider")
    report = _sport("Ollie Pearce's goal secures victory for York City against Rochdale", "2026-11-14T17:30:00Z")
    assert not si.different_fixtures(preview, report)
    assert not si.different_fixtures(_sport("Rochdale falls to Crewe in 3-2 defeat"), _sport("Crewe Alexandra beat Rochdale 3-2"))
    assert not si.different_fixtures(_sport("Oldham beat Rochdale"), _sport("Oldham Athletic to face Rochdale in derby"))


def test_guard_needs_an_opponent_on_both_sides_and_only_applies_to_sport():
    assert not si.different_fixtures(_sport("Rochdale AFC manager urges team to aim high this season"),
                                     _sport("Rochdale AFC suffers 4-2 defeat at Port Vale"))
    news = {**_sport("Port Vale fan charged after incident in Rochdale"), "category": "crime"}
    assert not si.different_fixtures(news, _sport("Rochdale AFC to face Doncaster Rovers"))
