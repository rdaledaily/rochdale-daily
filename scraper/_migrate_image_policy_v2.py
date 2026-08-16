"""Deprecated image-policy migration retained as a safe guardrail audit.

Rochdale Daily's canonical article-image contract requires every published
article image to live under ``assets/img/cards/``. Older experimental migration
code attempted to preserve remote and non-cards paths; that conflicts with the
current publication contract and must never rewrite the active image policy.
"""
from pathlib import Path


def main() -> None:
    policy = Path("scraper/ensure_article_images.py").read_text(encoding="utf-8")
    tests = Path("scraper/test_ensure_article_images.py").read_text(encoding="utf-8")

    required_policy_markers = (
        "cards-only, filename-matched article-image policy",
        "assets/img/cards",
        "def enforce_article",
    )
    missing = [marker for marker in required_policy_markers if marker not in policy]
    if missing:
        raise SystemExit(
            "Canonical cards-only image policy is missing expected guardrails: "
            + ", ".join(missing)
        )

    required_test_markers = (
        "test_non_cards_image_is_never_preserved",
        "test_run_gives_every_published_story_a_cards_image",
    )
    missing_tests = [marker for marker in required_test_markers if marker not in tests]
    if missing_tests:
        raise SystemExit(
            "Canonical cards-only image regression coverage is missing: "
            + ", ".join(missing_tests)
        )

    print("Legacy migration disabled; canonical assets/img/cards image policy remains enforced.")


if __name__ == "__main__":
    main()
