#!/usr/bin/env python3
"""Regression tests for local councillor portrait matching."""
from __future__ import annotations

import json
from pathlib import Path

from councillor_photos import CARDS_DIR, ROSTER, build_local_portrait_map, find_portrait, image_candidates


def main() -> int:
    raw = json.loads(ROSTER.read_text(encoding="utf-8"))
    people = raw.get("councillors", [])
    assert len(people) == 60, f"Expected 60 Rochdale councillors, got {len(people)}"

    candidates = image_candidates()
    assert candidates, f"No portrait candidates found in {CARDS_DIR}"

    missing = []
    outside_cards = []
    for person in people:
        name = str(person.get("name") or "").strip()
        portrait = find_portrait(name, candidates)
        if portrait is None:
            missing.append(name)
        elif portrait.parent != CARDS_DIR:
            outside_cards.append((name, str(portrait)))

    assert not missing, "Councillor portraits not matched: " + ", ".join(missing)
    assert not outside_cards, f"Councillor portraits escaped assets/img/cards: {outside_cards}"

    mapping = build_local_portrait_map(write=False)
    assert len(mapping) == len(people)
    for name, entry in mapping.items():
        image = str(entry.get("image_url") or "")
        assert image.startswith("/assets/img/cards/"), f"{name}: invalid local portrait path {image!r}"
        assert entry.get("verified_name_match") is True, f"{name}: portrait was not name matched"
        assert not image.startswith("http"), f"{name}: remote portrait unexpectedly allowed"

    # Explicitly protect the filename variants already used by the editorial
    # library: middle names, apostrophes and a minor spelling variation.
    examples = {
        "Dylan Williams": "Dylan_James_Williams.jpg",
        "Patricia Dale": "Patricia_Mary_Dale.jpg",
        "Paul O'Neill": "Paul_ONeill.png",
        "Philip Barrett": "phillip_barrett.jpg",
        "Ashley-Louise Gilbert": "Ashley_Louise_Gilbert.jpg",
        "Jordan Tarrant-Short": "Jordan_Tarrant_Short.jpg",
    }
    for name, expected in examples.items():
        portrait = find_portrait(name, candidates)
        assert portrait is not None, name
        assert portrait.name.lower() == expected.lower(), f"{name}: expected {expected}, got {portrait.name}"

    print(f"Councillor portrait coverage passed: {len(people)}/{len(people)} local portraits matched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
