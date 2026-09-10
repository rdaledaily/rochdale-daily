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

    # A full publishing cleanup must reach a fixed point in one call. Some
    # feeds arrive encoded more than once; historically &amp;amp; or an encoded
    # emoji was revealed by pass one and only removed by pass two, causing the
    # canonical publisher's immediate verification pass to fail.
    encoded = (
        "  News &amp;amp; views &#x26;#x1F4F0; "
        "[source](https://example.com/?utm_source=chatgpt.com)   "
    )
    once = hygiene.clean_text(encoded)
    twice = hygiene.clean_text(once)
    assert once == twice
    assert once == "News & views"

    nested_payload = {
        "title": "Update &amp;amp; reaction",
        "body": "Details &#x26;#128240;",
        "source_url": "https://example.com/story?utm_source=chatgpt.com&id=7",
    }
    first_json = hygiene.clean_json(nested_payload)
    second_json = hygiene.clean_json(first_json)
    assert first_json == second_json
    assert first_json["title"] == "Update & reaction"
    assert first_json["body"] == "Details"
    assert first_json["source_url"] == "https://example.com/story?id=7"

    print("Content hygiene metadata and idempotency checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
