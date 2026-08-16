from __future__ import annotations

import scrub_personal_name as scrub


def main() -> int:
    payload = {
        "title": "A person named Sarah Pickles attends a public meeting",
        "body": "Sarah Pickles spoke at the meeting and is part of the reported facts.",
        "byline": "Sarah Pickles",
        "nested": {
            "author_name": "Sarah Jane Pickles",
            "image_credit": "Sarah Pickles Photography",
        },
    }
    cleaned, changes = scrub._clean_metadata(payload)
    assert changes == 2
    assert cleaned["byline"] == "Rochdale Daily"
    assert cleaned["nested"]["author_name"] == "Rochdale Daily"
    # Journalism and unrelated credits are never silently rewritten.
    assert cleaned["title"] == payload["title"]
    assert cleaned["body"] == payload["body"]
    assert cleaned["nested"]["image_credit"] == payload["nested"]["image_credit"]
    print("Scoped privacy scrub checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
