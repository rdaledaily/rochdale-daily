#!/usr/bin/env python3
"""Enforce Rochdale Daily's canonical article-image contract.

Every published article must resolve to a real local file under
``assets/img/cards/``. Relevant local images found elsewhere in the repository
are migrated into the cards cache; remote/non-local canonical paths are cleared
and handed to ``ensure_article_images`` for a curated cards match or generated
fallback.

Source/credit metadata may still record where an image came from. This module
controls the *canonical publication path* only.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import ensure_article_images as images

CARDS_PREFIX = "assets/img/cards/"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def clean(value: Any) -> str:
    return str(value or "").strip()


def is_remote(value: Any) -> bool:
    parsed = urlparse(clean(value))
    return parsed.scheme.lower() in {"http", "https"}


def local_rel(value: Any) -> str:
    text = clean(value).replace("\\", "/")
    if not text or is_remote(text):
        return ""
    return text.lstrip("/")


def cards_rel(value: Any) -> str:
    rel = local_rel(value)
    return rel if rel.startswith(CARDS_PREFIX) else ""


def valid_image_file(root: Path, rel: str) -> bool:
    if not rel:
        return False
    path = root / rel
    try:
        return (
            path.is_file()
            and path.suffix.lower() in IMAGE_SUFFIXES
            and path.stat().st_size > 4096
        )
    except OSError:
        return False


def canonical_ok(article: dict[str, Any], root: Path) -> bool:
    rel = cards_rel(article.get("image_url") or article.get("img"))
    return bool(rel and valid_image_file(root, rel))


def _safe_stem(article: dict[str, Any]) -> str:
    raw = clean(article.get("slug") or article.get("id") or article.get("title") or "story")
    return re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")[:90] or "story"


def migrate_local_image(article: dict[str, Any], root: Path) -> str:
    """Copy a usable local non-cards image into the canonical cards cache."""
    rel = local_rel(article.get("image_url") or article.get("img"))
    if not rel or rel.startswith(CARDS_PREFIX) or not valid_image_file(root, rel):
        return ""

    source = root / rel
    suffix = source.suffix.lower()
    target_rel = f"{CARDS_PREFIX}{_safe_stem(article)}-canonical{suffix}"
    target = root / target_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() or target.stat().st_size != source.stat().st_size:
        shutil.copy2(source, target)

    article["image_url"] = target_rel
    article["img"] = target_rel
    article["image_status"] = "source-photo-cached"
    article["image_backfill_method"] = "cards-local-migration"
    article["source_image_reuse_status"] = "cards-only"
    return target_rel


def enforce_article(article: dict[str, Any], root: Path) -> str:
    if canonical_ok(article, root):
        # Let the established relevance matcher replace an obviously unrelated
        # cards image, while retaining already meaningful source/editorial cards.
        result = images.enforce_article(article, root)
    else:
        migrated = migrate_local_image(article, root)
        if migrated:
            result = images.enforce_article(article, root)
        else:
            article.pop("image_url", None)
            article.pop("img", None)
            result = images.enforce_article(article, root)

    if not canonical_ok(article, root):
        raise RuntimeError(
            f"cards-only image invariant failed for {_safe_stem(article)}: "
            f"{clean(article.get('image_url') or article.get('img'))!r}"
        )
    return result


def validate(rows: list[Any], root: Path) -> list[str]:
    errors: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if clean(row.get("status") or "published").lower() != "published":
            continue
        if not canonical_ok(row, root):
            errors.append(
                f"{_safe_stem(row)} -> {clean(row.get('image_url') or row.get('img')) or '<missing>'}"
            )
    return errors


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--articles", type=Path, default=Path("articles.json"))
    parser.add_argument("--report", type=Path, default=Path("cards_image_policy_report.json"))
    parser.add_argument("--check", action="store_true", help="Validate only; do not modify the feed")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    root = Path.cwd()
    payload = json.loads(args.articles.read_text(encoding="utf-8"))
    rows = payload if isinstance(payload, list) else payload.get("articles", [])
    if not isinstance(rows, list):
        raise SystemExit("Article feed must contain a JSON list")

    if args.check:
        errors = validate(rows, root)
        if errors:
            print("Published articles violating assets/img/cards/ canonical image policy:", file=sys.stderr)
            for error in errors[:100]:
                print(f"- {error}", file=sys.stderr)
            if len(errors) > 100:
                print(f"... and {len(errors) - 100} more", file=sys.stderr)
            return 1
        print("Cards-only canonical image policy passed.")
        return 0

    stats = {"published": 0, "changed": 0, "already_valid": 0}
    items: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if clean(row.get("status") or "published").lower() != "published":
            continue
        stats["published"] += 1
        before = clean(row.get("image_url") or row.get("img"))
        was_valid = canonical_ok(row, root)
        result = enforce_article(row, root)
        after = clean(row.get("image_url") or row.get("img"))
        if before != after:
            stats["changed"] += 1
        elif was_valid:
            stats["already_valid"] += 1
        items.append({"slug": _safe_stem(row), "before": before, "after": after, "result": result})

    errors = validate(rows, root)
    if errors:
        raise SystemExit("cards-only image enforcement left invalid published records")

    args.articles.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.report.write_text(
        json.dumps(
            {
                "policy": "published canonical image_url must be a real local assets/img/cards/ file",
                "stats": stats,
                "items": items,
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
