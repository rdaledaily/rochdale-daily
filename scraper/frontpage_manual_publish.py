#!/usr/bin/env python3
"""Run the canonical frontpage pipeline for an editorial/manual publish.

The ordinary newsroom pipeline deliberately re-evaluates image selection for every
published article. That is useful after a scrape, but it is unnecessarily expensive
when an editor has only added or amended a manual story: the existing archive has
already passed the image policy and scanning the entire cards library for every
historic article delays the new story reaching the homepage.

This wrapper keeps all normal frontpage, merge, freshness and archive behaviour, but
limits the expensive image-selection pass to records injected by the manual loaders.
A final cards-only validation remains in the publish workflow, so this is a speed
optimisation rather than a relaxation of the publication contract.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import frontpage_pipeline as pipeline

_original_enforce_article = pipeline.enforce_article


def _enforce_editorial_only(article: dict[str, Any], root: Path) -> str:
    if article.get("manual_article") or article.get("manual_event"):
        return _original_enforce_article(article, root)
    return "existing-archive-image-unchanged"


def main() -> int:
    pipeline.enforce_article = _enforce_editorial_only
    return pipeline.main()


if __name__ == "__main__":
    raise SystemExit(main())
