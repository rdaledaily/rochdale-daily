from __future__ import annotations

import content_hygiene as hygiene


def main() -> int:
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
    assert hygiene.has_public_text_violation({"byline": "Name \U0001f4f0"})
    assert not hygiene.has_public_text_violation(cleaned)
    assert not hygiene.has_public_text_violation({"internal_note": "Keep \U0001f4f0"})
    print("Content hygiene metadata checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
