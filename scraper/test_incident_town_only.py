"""A shared town is not a shared place when one report names a street.

Fixtures are the three real records of 14 Nov 2026: the editor's Buckley Hall
Prison article matched a police appeal and a street attack on "assault" +
"Rochdale" + a gender word, took the appeal's id, and both stories left the
live feed (story_identity.incident_fact_match).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import story_identity as si  # noqa: E402

FIX = json.loads((HERE / "fixtures_incident_town_only.json").read_text(encoding="utf-8"))
PRISON, APPEAL, ATTACK = FIX["prison_editor"], FIX["police_appeal"], FIX["boundary_attack"]


def test_prison_article_is_not_the_police_appeal_or_the_street_attack():
    assert not si.precise_locations(PRISON) and si.precise_locations(APPEAL) and si.precise_locations(ATTACK)
    for other in (APPEAL, ATTACK):
        assert not si.incident_fact_match(PRISON, other)
        assert not si.incident_fact_match(other, PRISON)
        assert not si.same_story(PRISON, other)
        assert si.story_similarity(PRISON, other) < 0.3


def test_two_reports_naming_the_same_street_still_match():
    left = {
        "title": "Mum and baby escape house fire on Hollingworth Road in Littleborough",
        "content_html": "<p>A mum and her baby escaped a house fire on Hollingworth Road, Littleborough.</p>",
        "category": "news", "area": "littleborough", "published_at": "2026-11-10T09:00:00Z",
    }
    right = {
        "title": "Mother rescued from blaze at Littleborough home",
        "content_html": "<p>A mother was rescued from a blaze at a home on Hollingworth Road in Littleborough.</p>",
        "category": "news", "area": "littleborough", "published_at": "2026-11-10T15:00:00Z",
    }
    assert si.incident_fact_match(left, right)


def test_two_reports_naming_only_the_town_still_match():
    left = {
        "title": "Woman injured in Heywood assault",
        "content_html": "<p>A woman was injured in an assault in Heywood, police said.</p>",
        "category": "crime", "area": "heywood", "published_at": "2026-11-10T09:00:00Z",
    }
    right = {
        "title": "Police appeal after woman attacked in Heywood",
        "content_html": "<p>Police are appealing for witnesses after a woman was assaulted in Heywood.</p>",
        "category": "crime", "area": "heywood", "published_at": "2026-11-10T18:00:00Z",
    }
    assert not si.precise_locations(left) and not si.precise_locations(right)
    assert si.incident_fact_match(left, right)
