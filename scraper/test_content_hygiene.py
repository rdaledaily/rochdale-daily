from __future__ import annotations

import content_hygiene as hygiene


def test_public_metadata_fields_are_cleaned() -> None:
    payload = {
        "title": "Title \U0001f4f0",
        "body": "Body \U0001f4f0",
        "byline": "Rochdale Daily \U0001f4f0",
        "image_credit": "Photographer \U0001f4f7",
        "source_name": "Source \U0001f310",
        "image_alt": "Alt \U0001f5bc",
    }
    cleaned = hygiene.clean_json(payload)
    assert cleaned["title"] == "Title"
    assert cleaned["body"] == "Body"
    assert cleaned["byline"] == "Rochdale Daily"
    assert cleaned["image_credit"] == "Photographer"
    assert cleaned["source_name"] == "Source"
    assert cleaned["image_alt"] == "Alt"


def test_detector_scope_matches_cleaner_scope() -> None:
    assert hygiene.has_public_text_violation({"byline": "Name \U0001f4f0"})
    cleaned = hygiene.clean_json({"byline": "Name \U0001f4f0"})
    assert not hygiene.has_public_text_violation(cleaned)


def test_private_machine_field_does_not_block_verification() -> None:
    # Detection is intentionally aligned with the fields the fixer owns.
    assert not hygiene.has_public_text_violation({"internal_note": "Keep \U0001f4f0"})
