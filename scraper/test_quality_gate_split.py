#!/usr/bin/env python3
"""The quality gate must relax on style and never on truth.

Run: PYTHONPATH=scraper python scraper/test_quality_gate_split.py

Background. On 30 August 2026 the pipeline was binning 25 of every 27 rewrites,
and 34% of Rochdale Daily's own published articles failed the same checker. The
gate had drifted stricter than the paper's editorial judgement and was spiking
true, well-sourced reporting over house style.

The fix splits the checks: integrity failures still spike a story absolutely,
house-style failures are published and logged. This file is the guard on that
split. If someone later adds a check, it lands in the style bucket by default --
so any check that MUST block has to be named in INTEGRITY_ISSUE_MARKERS, and the
tests below are what catch the omission.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from editorial_upgrade import (
    GATE_REJECTION_PREFIX,
    integrity_issues,
    quality_issues,
    style_only,
)

FAILURES: list[str] = []


def check(condition: bool, label: str) -> None:
    if condition:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}")
        FAILURES.append(label)


def section(title: str) -> None:
    print(f"\n{title}")


SOURCE = (
    "Greater Manchester Police were called to Drake Street in Rochdale at "
    "around 4.15pm on Saturday 30 August 2026 after reports of a collision "
    "involving a cyclist. A 43-year-old man was taken to Royal Oldham Hospital "
    "with a broken leg. Drake Street was closed for three hours while officers "
    "from the Serious Collision Investigation Unit examined the scene. "
    "Anyone with dashcam footage is asked to contact police on 101."
)


def draft(title, excerpt, paragraphs, publishable=True):
    return {
        "publishable": publishable,
        "title": title,
        "excerpt": excerpt,
        "paragraphs": paragraphs,
    }


GOOD_PARAS = [
    "Drake Street in Rochdale was closed for three hours on Saturday afternoon "
    "after a cyclist was injured in a collision with a vehicle.",
    "Greater Manchester Police said officers were called at around 4.15pm on "
    "Saturday 30 August, and that a 43-year-old man was taken to Royal Oldham "
    "Hospital with a broken leg.",
    "Officers from the Serious Collision Investigation Unit examined the scene "
    "before the road reopened. Anyone with dashcam footage has been asked to "
    "contact police on 101.",
]

# --------------------------------------------------------------------------
section("Integrity failures still block absolutely")
# --------------------------------------------------------------------------

BLOCKERS = [
    (
        ["The model did not return an article object."],
        "no article object",
    ),
    (
        ["The model marked the story unpublishable."],
        "model marked it unpublishable",
    ),
    (
        ["Ground the report more clearly in the supplied facts."],
        "not grounded in the sources",
    ),
    (
        ["Rewrite the long verbatim source passage."],
        "long verbatim passage (copyright)",
    ),
    (
        [
            "The source names a road, time, figure or organisation and the "
            "draft does not. Carry the specific detail through."
        ],
        "dropped the specific detail the source carried",
    ),
    (
        [f"{GATE_REJECTION_PREFIX}NON_NEWS: the model classified this as an advert."],
        "gate rejection (advert / listing)",
    ),
    (
        [f"{GATE_REJECTION_PREFIX}NON_LOCAL: out of borough."],
        "gate rejection (out of borough)",
    ),
]
for issues, label in BLOCKERS:
    check(bool(integrity_issues(issues)), f"blocks: {label}")
    check(not style_only(issues), f"never treated as style-only: {label}")

# --------------------------------------------------------------------------
section("House-style failures do not block")
# --------------------------------------------------------------------------

STYLE = [
    (["Write a specific complete headline of 4-26 words."], "headline word count"),
    (["Write a useful standfirst."], "thin standfirst"),
    (["Avoid a generic label followed by a colon in the headline."], "colon in headline"),
    (["Use at least 4 substantive paragraphs."], "paragraph count"),
    (["Tighten the standfirst to one clear sentence."], "standfirst length"),
    (["Remove all emoji and pictographic symbols from the headline."], "emoji"),
    (
        ["Remove filler phrasing such as \"a major route\", \"in the area\"."],
        "filler phrasing",
    ),
    (
        [
            "Align the headline with the report: most of its key words never "
            "appear in the body."
        ],
        "headline/body token overlap",
    ),
    (
        [
            "Complete or remove the sentence with a missing date, time or "
            "place; never leave a preposition hanging before punctuation."
        ],
        "hanging preposition",
    ),
    (
        ["Introduce the unidentified person as 'a man' before referring to 'the man'."],
        "person introduction",
    ),
    (
        ["Replace these imprecise or formulaic expressions with exact ordinary language:"],
        "formulaic expressions",
    ),
    (
        ["Write at least 120 body words using only facts already present in the sources."],
        "body word floor",
    ),
]
for issues, label in STYLE:
    check(not integrity_issues(issues), f"does not block: {label}")
    check(style_only(issues), f"classed as style-only: {label}")

# --------------------------------------------------------------------------
section("A mixed verdict blocks on the integrity half")
# --------------------------------------------------------------------------

mixed = [
    "Avoid a generic label followed by a colon in the headline.",
    "Ground the report more clearly in the supplied facts.",
]
check(len(integrity_issues(mixed)) == 1, "one blocking issue extracted from a mixed list")
check(not style_only(mixed), "a mixed list is never style-only")
check(
    integrity_issues(mixed)[0].startswith("Ground the report"),
    "the blocking issue is the one reported to the editor",
)

# --------------------------------------------------------------------------
section("An empty verdict is not a failure")
# --------------------------------------------------------------------------

check(integrity_issues([]) == [], "no issues means nothing blocks")
check(not style_only([]), "a clean draft is not 'style-only'")

# --------------------------------------------------------------------------
section("End to end against the real checker")
# --------------------------------------------------------------------------

clean = draft(
    "Cyclist injured as Drake Street closed for three hours in Rochdale",
    "A 43-year-old man was taken to hospital with a broken leg after a "
    "collision on Drake Street on Saturday afternoon, police have said.",
    GOOD_PARAS,
)
issues = quality_issues(clean, SOURCE, "article")
check(not integrity_issues(issues), "a clean, grounded report has no blocking issues")

# Same facts, deliberately bad house style: label-colon headline.
styled = draft(
    "BREAKING: Cyclist injured as Drake Street closed for three hours",
    "A 43-year-old man was taken to hospital with a broken leg after a "
    "collision on Drake Street on Saturday afternoon, police have said.",
    GOOD_PARAS,
)
styled_issues = quality_issues(styled, SOURCE, "article")
check(
    not integrity_issues(styled_issues),
    "a label-colon headline never blocks a true story",
)

# Ungrounded: nothing to do with the source at all.
ungrounded = draft(
    "Rochdale library announces new opening hours for autumn term",
    "The library will open later on Thursdays from September, the council has "
    "confirmed in its latest cultural services update.",
    [
        "Rochdale library will extend its Thursday opening hours from September "
        "as part of the council's autumn cultural programme.",
        "The council said the change follows a consultation with regular users "
        "of the reading rooms and the local studies collection.",
        "No change has been announced for weekend opening, which remains as "
        "published on the council's website.",
    ],
)
ungrounded_issues = quality_issues(ungrounded, SOURCE, "article")
check(
    bool(integrity_issues(ungrounded_issues)),
    "a report unrelated to its source is still blocked",
)

# Unpublishable flag set by the model.
refused = draft("Anything at all here", "Any standfirst here at all", GOOD_PARAS, publishable=False)
check(
    bool(integrity_issues(quality_issues(refused, SOURCE, "article"))),
    "a draft the model marked unpublishable is still blocked",
)

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED:")
    for name in FAILURES:
        print(f"  - {name}")
    raise SystemExit(1)
print("all quality-gate split tests passed")
