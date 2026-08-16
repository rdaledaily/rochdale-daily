"""Compatibility entry point for the disabled legacy image migration.

This script intentionally performs no rewrite. It delegates to the cards-only
policy audit retained in v2 so an old manual invocation cannot weaken the
canonical ``assets/img/cards/`` contract.
"""
from _migrate_image_policy_v2 import main


if __name__ == "__main__":
    main()
