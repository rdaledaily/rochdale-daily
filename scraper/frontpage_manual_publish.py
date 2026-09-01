#!/usr/bin/env python3
"""Run the canonical frontpage pipeline for an editorial/manual publish.

The ordinary newsroom pipeline deliberately re-evaluates image selection for every
published article and refreshes the external What's Occurrin' ticket feed. Both are
useful after a scrape, but they are unnecessarily expensive when an editor has only
added or amended a manual story: the existing archive and approved event records have
already passed those policies.

This wrapper keeps all normal frontpage, merge, freshness and archive behaviour, but
limits image selection to a manual/editorial record that does not already point at a
valid canonical cards image and reuses the existing approved ticket-event records
already present in articles.json. It also memoizes the expensive deterministic article
category calculation for the lifetime of the process. Duplicate detection is O(n²), but
category is a pure function of a record's text/category/source kind; recomputing it for
every pair turned roughly 150 records into tens of thousands of classifier calls.

A final cards-only validation and manual-publication invariant remain in the publish
workflow, so these are speed optimisations rather than relaxations of the publication
contract.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import frontpage_pipeline as pipeline

_original_enforce_article = pipeline.enforce_article
_original_article_category = pipeline.article_category
CARDS_PREFIX = "assets/img/cards/"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


@lru_cache(maxsize=4096)
def _category_for_signature(text: str, declared_category: str, source_kind: str) -> str:
    """Classify one immutable article signature once per process.

    ``frontpage_pipeline.article_category`` is deterministic for these three inputs.
    A tiny synthetic record lets us reuse that exact production logic rather than
    duplicating the classifier here. If an article's text or declared category changes,
    its signature changes and it is classified again.
    """
    return _original_article_category(
        {
            "title": text,
            "category": declared_category,
            "source_kind": source_kind,
        }
    )


def _cached_article_category(article: dict[str, Any]) -> str:
    return _category_for_signature(
        pipeline.article_text(article),
        str(article.get("category") or "news"),
        str(article.get("source_kind") or "").lower(),
    )


# Apply the memoized category lookup at import time as well as in ``main``. The
# publish workflow imports this module before generate_newspaper_pages.py, so both
# canonical passes share the fast lookup without changing any merge decision.
pipeline.article_category = _cached_article_category


def _has_valid_canonical_image(article: dict[str, Any], root: Path) -> bool:
    value = str(article.get("image_url") or article.get("img") or "").strip().replace("\\", "/")
    if not value or value.startswith(("http://", "https://")):
        return False
    rel = value.lstrip("/")
    if not rel.startswith(CARDS_PREFIX):
        return False
    path = root / rel
    try:
        return path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES and path.stat().st_size > 4096
    except OSError:
        return False


def _enforce_editorial_only(article: dict[str, Any], root: Path) -> str:
    is_editorial = bool(
        article.get("manual_article")
        or article.get("manual_event")
        or str(article.get("source_kind") or "").lower() == "editorial"
    )
    if is_editorial and not _has_valid_canonical_image(article, root):
        return _original_enforce_article(article, root)
    return "existing-canonical-image-unchanged"


def _reuse_existing_ticket_events(session: Any = None) -> tuple[list[dict[str, Any]], str]:
    """Skip the external ticket-site crawl during an editor-only publication.

    frontpage_pipeline.clean_and_integrate_events() retains current approved event
    records already present in articles.json when no fresh scraped events are supplied,
    so a manual article publish does not need up to 30 network requests before it can
    reach the site.
    """
    return [], "manual publish reused existing approved ticket events"


def main() -> int:
    pipeline.article_category = _cached_article_category
    pipeline.enforce_article = _enforce_editorial_only
    pipeline.collect_ticket_events = _reuse_existing_ticket_events
    return pipeline.main()


if __name__ == "__main__":
    raise SystemExit(main())
