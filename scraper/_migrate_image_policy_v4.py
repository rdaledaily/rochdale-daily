"""Disabled legacy image-policy migration.

Canonical published article images must remain under ``assets/img/cards/``.
This compatibility script intentionally performs no rewrite so an old manual
invocation cannot replace the active cards-only policy or its regression tests.
"""
from _migrate_image_policy_v2 import main


if __name__ == "__main__":
    main()
