from source_registry import FIRST_PARTY_BEATS, beat_names, critical_beats


names = beat_names()
assert "Rochdale Borough Council News" in names
assert "Rochdale planning applications" in names
assert "Greater Manchester Police" in names
assert "Northern Care Alliance Rochdale" in names
assert "Rochdale AFC" in names
assert "Rochdale Hornets" in names
assert "Rochdale Mayfield" in names
assert "Food Standards Agency" in names
assert len(FIRST_PARTY_BEATS) >= 20
assert len(critical_beats()) >= 3

print("First-party source registry tests passed.")
