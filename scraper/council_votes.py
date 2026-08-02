#!/usr/bin/env python3
"""
Rochdale Daily — council recorded votes.

WHAT THIS DOES
--------------
Rochdale Borough Council publishes agendas, reports, minutes and decision
notices, but almost every vote is minuted only as carried or lost. Individual
councillors' votes appear in one circumstance: a recorded vote. Those are
mandatory on the budget and council tax at English councils, and otherwise
happen when a group demands one.

Where a recorded vote has taken place, the agenda-item page carries blocks in
this shape:

    Voting for the motion: Councillors Ali Ahmed, Iftikhar Ahmed, Besford,
    Brett, Dale, Dearnley, Neil Emmott, Susan Emmott ...
    Voting against the motion: Councillors Dearnley, Holly ...
    Abstained: Councillors ...

This module extracts those lists and matches each name to a councillor on the
roster, so a reader can be shown how their own ward voted.

WHY IT REFUSES RATHER THAN GUESSES
----------------------------------
Minutes list surnames, with a forename or initial only where there would
otherwise be a clash. Rochdale currently has several Ahmeds, two Williamses,
two Smiths, two Howards and two Gilberts. Attributing a vote to the wrong
councillor is a serious error - it is a factual claim about a named person's
conduct in public office, published under our masthead.

So the matcher never picks a "best" candidate. A name that matches more than
one councillor, or none, is reported as unresolved and the vote is recorded
against nobody. A vote with unresolved names is still published, with the
count of names we could not place stated openly, rather than quietly dropped.

WHAT IT CANNOT DO
-----------------
It cannot show how a councillor voted on anything that was not a recorded
vote, because that information is not published anywhere. Any page built on
this data must say so plainly rather than implying the record is complete.

Usage:
    python scraper/council_votes.py --self-test
    python scraper/council_votes.py --page https://rochdale.moderngov.co.uk/mgAi.aspx?ID=32414
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ROSTER_PATH = REPO_ROOT / "council_roster.json"
OUTPUT_PATH = REPO_ROOT / "council_votes.json"

# The three outcomes ModernGov uses. Ordered longest-first so "voting against
# the motion" is matched before "voting for the motion" cannot mis-trigger.
VOTE_HEADINGS = [
    ("against", r"voting\s+against\s+(?:the\s+)?(?:motion|recommendation)s?"),
    ("abstain", r"abstain(?:ed|ing)?(?:\s+from\s+voting)?"),
    ("for", r"voting\s+for\s+(?:the\s+)?(?:motion|recommendation)s?"),
]

# Trailing words that end a name list rather than belonging to it.
LIST_TERMINATORS = re.compile(
    r"(?:\.\s|\n|voting\s+against|voting\s+for|abstain|the\s+motion\s+was|"
    r"upon\s+being|resolved|it\s+was\s+)",
    re.IGNORECASE,
)


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip()


def strip_titles(name: str) -> str:
    return re.sub(
        r"^(?:councillors?|cllrs?|the\s+mayor|mayor|alderman)\s+",
        "",
        name.strip(),
        flags=re.IGNORECASE,
    ).strip(" .,")


@dataclass
class Councillor:
    name: str
    ward: str
    party: str = ""
    uid: str = ""

    @property
    def surname(self) -> str:
        return normalise(self.name).split()[-1].lower()

    @property
    def forename(self) -> str:
        parts = normalise(self.name).split()
        return parts[0].lower() if len(parts) > 1 else ""

    @property
    def initial(self) -> str:
        return self.forename[:1]


@dataclass
class VoteRecord:
    title: str
    url: str
    date: str = ""
    committee: str = ""
    votes: dict[str, list[dict]] = field(default_factory=dict)
    unresolved: list[str] = field(default_factory=list)


def load_roster(path: Path = ROSTER_PATH) -> list[Councillor]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    out = []
    for row in raw if isinstance(raw, list) else raw.get("councillors", []):
        if not isinstance(row, dict) or not row.get("name"):
            continue
        out.append(Councillor(
            name=str(row["name"]).strip(),
            ward=str(row.get("ward") or "").strip(),
            party=str(row.get("party") or "").strip(),
            uid=str(row.get("uid") or "").strip(),
        ))
    return out


def split_names(blob: str) -> list[str]:
    """Split a 'Councillors A, B and C' list into individual names."""
    blob = strip_titles(blob)
    blob = re.sub(r"\s+and\s+", ", ", blob, flags=re.IGNORECASE)
    parts = [normalise(p).strip(" .;") for p in blob.split(",")]
    return [p for p in parts if p and not p.lower().startswith("councillor")]


def match_name(raw: str, roster: list[Councillor]) -> Councillor | None:
    """Return the one councillor this name can only be, or None.

    Never returns a best guess: an ambiguous surname resolves to None so the
    caller can report it rather than attribute a vote to the wrong person.
    """
    name = normalise(strip_titles(raw)).lower().strip(" .")
    if not name:
        return None
    tokens = name.split()

    # Full name, e.g. "Neil Emmott"
    exact = [c for c in roster if normalise(c.name).lower() == name]
    if len(exact) == 1:
        return exact[0]

    surname = tokens[-1]
    candidates = [c for c in roster if c.surname == surname]
    if not candidates:
        return None
    if len(candidates) == 1 and len(tokens) == 1:
        return candidates[0]

    if len(tokens) > 1:
        lead = tokens[0].strip(".")
        # "S. Ahmed" -> initial; "Shakil Ahmed" -> forename
        if len(lead) == 1:
            narrowed = [c for c in candidates if c.initial == lead]
        else:
            narrowed = [c for c in candidates if c.forename == lead]
        if len(narrowed) == 1:
            return narrowed[0]
        return None

    # Bare surname shared by several councillors: refuse.
    return None


def parse_recorded_vote(text: str) -> dict[str, list[str]]:
    """Pull the for/against/abstain name lists out of an agenda-item page."""
    flat = normalise(text)
    found: dict[str, list[str]] = {}
    for key, pattern in VOTE_HEADINGS:
        m = re.search(pattern + r"\s*[:\-]?\s*", flat, re.IGNORECASE)
        if not m:
            continue
        tail = flat[m.end():]
        stop = LIST_TERMINATORS.search(tail)
        blob = tail[: stop.start()] if stop else tail
        names = split_names(blob)
        if names:
            found[key] = names
    return found


def build_record(title: str, url: str, text: str, roster: list[Councillor]) -> VoteRecord:
    record = VoteRecord(title=title, url=url)
    for side, names in parse_recorded_vote(text).items():
        placed = []
        for raw in names:
            match = match_name(raw, roster)
            if match is None:
                record.unresolved.append(raw)
                continue
            placed.append({"name": match.name, "ward": match.ward, "party": match.party})
        if placed:
            record.votes[side] = placed
    return record


def by_ward(record: VoteRecord) -> dict[str, dict[str, list[str]]]:
    out: dict[str, dict[str, list[str]]] = {}
    for side, people in record.votes.items():
        for person in people:
            ward = person["ward"] or "(ward unknown)"
            out.setdefault(ward, {}).setdefault(side, []).append(person["name"])
    return out


# --------------------------------------------------------------------------
# Self-test. Uses the published wording of a real Rochdale budget vote so the
# parsing and the refusal behaviour can both be checked without a network
# call - ModernGov blocks automated requests, so live fetching needs the
# Playwright path rather than plain HTTP.
# --------------------------------------------------------------------------
SAMPLE = """
The Council considered a report outlining the recommendations of the Cabinet,
as moved by Councillor Brett and seconded by Councillor Rowbotham, in respect
of the Revenue Budget, Capital Budget and Council Tax for 2020/2021. It was
noted that an amendment had been received to the Motion, which was moved by
Councillor Dearnley and seconded by Councillor Holly. Upon being put to the
vote the Mayor declared the amendment lost. The Motion as moved and seconded
was then voted upon by means of a recorded vote.
Voting for the motion: Councillors Shakil Ahmed, Besford, Brett, Dale,
Neil Emmott, Susan Emmott and Gartside.
Voting against the motion: Councillors Dearnley, Holly and Smith.
Abstained: Councillors Williams.
"""

SAMPLE_ROSTER = [
    {"name": "Shakil Ahmed", "ward": "Kingsway", "party": "Labour"},
    {"name": "Iftikhar Ahmed", "ward": "Central Rochdale", "party": "Labour"},
    {"name": "Peter Besford", "ward": "Norden", "party": "Labour"},
    {"name": "Allen Brett", "ward": "Castleton", "party": "Labour"},
    {"name": "Peter Dale", "ward": "Bamford", "party": "Labour"},
    {"name": "Neil Emmott", "ward": "Spotland and Falinge", "party": "Labour"},
    {"name": "Susan Emmott", "ward": "Spotland and Falinge", "party": "Labour"},
    {"name": "Ashley Gartside", "ward": "Norden", "party": "Conservative"},
    {"name": "Michael Dearnley", "ward": "Milnrow and Newhey", "party": "Conservative"},
    {"name": "Pat Holly", "ward": "Healey", "party": "Conservative"},
    # deliberately ambiguous pairs
    {"name": "Terry Smith", "ward": "Wardle", "party": "Labour"},
    {"name": "Angela Smith", "ward": "Bamford", "party": "Conservative"},
    {"name": "Daniel Williams", "ward": "Kingsway", "party": "Labour"},
    {"name": "Peter Williams", "ward": "Healey", "party": "Labour"},
]


def self_test() -> int:
    roster = [Councillor(**{k: v for k, v in row.items()}) for row in SAMPLE_ROSTER]
    record = build_record("Budget Report 2020/21", "https://example.test/mgAi.aspx?ID=32414",
                          SAMPLE, roster)
    print("parsed sides:", {k: len(v) for k, v in record.votes.items()})
    for side in ("for", "against", "abstain"):
        people = record.votes.get(side, [])
        if people:
            print(f"  {side:<8}", ", ".join(f"{p['name']} ({p['ward']})" for p in people))
    print("unresolved (refused rather than guessed):", record.unresolved or "none")
    print()
    print("by ward:")
    for ward, sides in sorted(by_ward(record).items()):
        summary = "; ".join(f"{s}: {', '.join(n)}" for s, n in sides.items())
        print(f"  {ward:<24}{summary}")

    ok = True
    voted_for = {p["name"] for p in record.votes.get("for", [])}
    if "Shakil Ahmed" not in voted_for:
        print("FAIL: forename disambiguation did not resolve Shakil Ahmed"); ok = False
    if {"Neil Emmott", "Susan Emmott"} - voted_for:
        print("FAIL: two councillors sharing a surname were not both resolved"); ok = False
    if "Smith" not in record.unresolved:
        print("FAIL: ambiguous surname 'Smith' should have been refused"); ok = False
    if "Williams" not in record.unresolved:
        print("FAIL: ambiguous surname 'Williams' should have been refused"); ok = False
    for side in record.votes.values():
        for person in side:
            if person["name"] in ("Terry Smith", "Angela Smith", "Daniel Williams", "Peter Williams"):
                print(f"FAIL: guessed an ambiguous name as {person['name']}"); ok = False
    print()
    print("SELF-TEST PASSED" if ok else "SELF-TEST FAILED")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse Rochdale council recorded votes.")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--page", help="Agenda-item URL (needs a browser fetch: ModernGov blocks plain HTTP)")
    parser.add_argument("--text-file", help="Parse a saved copy of an agenda-item page instead of fetching")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    roster = load_roster()
    if not roster:
        print(f"council_votes: no roster at {ROSTER_PATH.name}; cannot attribute votes", file=sys.stderr)
        return 1

    if args.text_file:
        text = Path(args.text_file).read_text(encoding="utf-8")
        record = build_record(args.text_file, args.page or "", text, roster)
        print(json.dumps({"title": record.title, "votes": record.votes,
                          "unresolved": record.unresolved, "by_ward": by_ward(record)},
                         indent=2, ensure_ascii=False))
        return 0

    print("council_votes: pass --self-test or --text-file. Live fetching needs the "
          "Playwright path; ModernGov refuses plain HTTP requests.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
