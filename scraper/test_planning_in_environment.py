#!/usr/bin/env python3
"""Planning coverage files under environment -- editorial decision, 3 Sep 2026.

Run: PYTHONPATH=scraper python scraper/test_planning_in_environment.py

Planning had discovery queries but no category of its own, so its stories were
selected and then misfiled into business (via "housing development" and
"apartments") or dropped: 3 selected, 0 published in a typical run, and zero
planning-subject stories in 30 days. The editor's ruling is that planning
belongs inside the environment beat. These cases pin that routing -- and, just
as importantly, pin that the word "planning" alone moves nothing: planning a
fundraiser is community, planning for the season is sport.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from editorial_upgrade import deterministic_category

FAILURES: list[str] = []


def check(text: str, expected: str) -> None:
    got = deterministic_category(text)
    if got == expected:
        print(f"  ok   {expected:12s} {text[:56]}")
    else:
        print(f"  FAIL wanted {expected}, got {got}: {text[:56]}")
        FAILURES.append(text[:56])


print("\nPlanning stories file as environment")
check(
    "Plans for 300 homes at Wheatsheaf get planning permission. The planning "
    "application was approved by the planning committee despite objections. "
    "The housing development includes apartments.",
    "environment",
)
check(
    "Demolition of former mill approved as planning committee backs change of "
    "use for the derelict factory site.",
    "environment",
)
check(
    "HMO planning application refused on Drake Street after residents' "
    "objections to the house in multiple occupation.",
    "environment",
)
check(
    "Planning appeal lodged over refused outline planning consent for green "
    "belt site in Norden.",
    "environment",
)
check(
    "Section 106 money from the housing development will fund a new play "
    "area, the planning committee heard.",
    "environment",
)

print("\nThe word 'planning' alone moves nothing")
check(
    "New Aldi store opening in Rochdale town centre creates 30 jobs as the "
    "retail business expands.",
    "business",
)
check(
    "Rochdale AFC planning for the new season with pre-season training "
    "sessions and squad announcements.",
    "sport",
)
check(
    "Volunteers planning a fundraiser for the food bank charity said "
    "donations are welcome.",
    "community",
)

print("\nThe rest of the environment beat is untouched")
check(
    "Flood warnings issued as heavy rainfall hits Hollingworth Lake and the "
    "River Roch bursts its banks.",
    "environment",
)
check(
    "Fly-tipping on the increase as household waste is dumped near the "
    "nature reserve.",
    "environment",
)

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED")
    raise SystemExit(1)
print("all planning-in-environment tests passed")
