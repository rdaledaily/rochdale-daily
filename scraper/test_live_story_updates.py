from __future__ import annotations

import live_story_updates as live


def main() -> int:
    # A routine re-render/whitespace change must not renew freshness.
    old = "Police are appealing for information after an incident on Drake Street."
    same = "  Police are appealing for information after an incident on Drake Street.  "
    assert not live.materially_changed(old, same, "Police appeal", "Police appeal")

    # A named/arrest development is material and may become a timestamped update.
    updated = (
        "Police are appealing for information after an incident on Drake Street. "
        "John Example has now been arrested and remains in custody."
    )
    assert live.materially_changed(old, updated, "Police appeal", "Man arrested after Drake Street incident")

    # A changed clock/date fragment with otherwise identical content is not enough.
    before = "Lift unavailable. Updated 10:30. Passengers should use the ramp from Cromford Street."
    after = "Lift unavailable. Updated 10:45. Passengers should use the ramp from Cromford Street."
    assert not live.materially_changed(before, after, "Lift unavailable", "Lift unavailable")

    # Generic dedupe/ongoing state alone must never opt an evergreen page into the
    # live refresh lane. Only an explicit live/breaking/source-kind signal does.
    assert not live._is_developing({"is_ongoing": True, "source_kind": "article"})
    assert live._is_developing({"live_story": True, "source_kind": "article"})
    assert live._is_developing({"source_kind": "live"})

    print("Developing-story material refresh checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
