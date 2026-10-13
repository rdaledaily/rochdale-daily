#!/usr/bin/env python3
"""Recover the original publisher's lead photograph when reuse rights are verified.

Crawling a publisher page is NOT evidence that its photos may be republished.
This pass only uses matching image-specific Creative Commons/public-domain terms
or a separately documented, verified permission. Proper credit and licence link
are retained on the article, including for commercial use.

Runs on real published stories before local-library selection or Commons fallback.
Unsupported sources keep their generated cards or appropriately curated photos.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from PIL import Image, UnidentifiedImageError

from ensure_article_images import high_risk_photo_story
from licensed_source_images import fetch_licensed_source_image, permission_entries

from backfill_article_images import (
    DEFAULT_USER_AGENT,
    atomic_write_json,
    clean,
    load_articles,
    source_urls,
)

CARDS_DIR = Path("assets/img/cards")
DEFAULT_ALLOWED_DOMAINS = ""  # Domain reputation never proves image reuse permission.


def host(value: str) -> str:
    return urlparse(value).netloc.lower().removeprefix("www.")


def allowed_domains() -> set[str]:
    raw = os.getenv("IMAGE_REUSE_SOURCE_DOMAINS", DEFAULT_ALLOWED_DOMAINS)
    return {item.strip().lower().removeprefix("www.") for item in raw.split(",") if item.strip()}


def domain_allowed(value: str, allowed: set[str]) -> bool:
    name = host(value)
    return any(name == domain or name.endswith("." + domain) for domain in allowed)


def is_generated_or_placeholder(article: dict[str, Any]) -> bool:
    image = clean(article.get("image_url") or article.get("img")).lower()
    status = clean(article.get("image_status")).lower()
    return bool(
        not image
        or "generated-card" in image
        or "area-category-card" in image
        or "placeholder" in image
        or status == "cards-generated"
        or clean(article.get("image_placeholder_reason"))
    )


def slug_for(article: dict[str, Any]) -> str:
    raw = clean(article.get("slug") or article.get("id") or article.get("title"))
    return re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")[:100] or "story"


def canonicalise_download(article: dict[str, Any]) -> str:
    """Move a downloaded source photo to cards/<exact-story-slug>.<ext>."""
    downloaded = Path(clean(article.get("image_url")))
    if not downloaded.is_file() or downloaded.parent != CARDS_DIR:
        return clean(article.get("image_url"))

    suffix = downloaded.suffix.lower()
    target = CARDS_DIR / f"{slug_for(article)}{suffix}"
    if downloaded == target:
        return target.as_posix()

    if target.exists():
        # An exact-slug image is authoritative. The normal cards matcher would
        # have picked it already, but never overwrite editor-controlled bytes if
        # a concurrent/manual update created it while this run was in progress.
        downloaded.unlink(missing_ok=True)
    else:
        downloaded.replace(target)
    return target.as_posix()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--articles", type=Path, default=Path("articles.json"))
    parser.add_argument("--report", type=Path, default=Path("image_repair_report.json"))
    parser.add_argument("--timeout", type=int, default=10)
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args(argv)


def try_licensed_source_photo(
    article: dict[str, Any],
    candidates: list[str],
    *,
    timeout: int,
    permissions: dict[str, dict[str, str]],
) -> tuple[bool, str]:
    """Set an approved original-source photograph; do not touch story facts."""
    for source_url in candidates:
        try:
            result = fetch_licensed_source_image(
                source_url, permissions=permissions, timeout=timeout,
                user_agent=DEFAULT_USER_AGENT,
            )
        except (OSError, ValueError, TimeoutError, ConnectionError) as exc:
            continue
        if result is None:
            continue

        candidate, payload, extension, rights = result
        try:
            with Image.open(io.BytesIO(payload)) as image:
                image.verify()
        except (OSError, ValueError, UnidentifiedImageError):
            continue

        target = CARDS_DIR / f"{slug_for(article)}{extension}"
        if target.is_file():
            # A genuinely existing editor-supplied same-slug photograph wins;
            # the source photo must never overwrite an approved edit.
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)

        credit = (rights.get("creator") or "Original source").strip()
        licence = (rights.get("license_name") or "Used with permission").strip()
        article["image_url"] = target.as_posix()
        article["img"] = target.as_posix()
        article["image_credit"] = f"{credit} / {licence}"
        article["image_credit_url"] = rights.get("evidence_url") or source_url
        article["image_license_url"] = rights.get("license_url") or ""
        article["image_license"] = licence
        article["source_image_candidate_url"] = candidate.url
        article["image_status"] = "source-photo-cached"
        article["image_backfill_method"] = "verified-original-source-photo"
        article["source_image_reuse_status"] = "verified-source-image-license"
        article.pop("image_placeholder_reason", None)
        return True, "licensed-source-photo"
    return False, "no-cleared-source-image"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    articles = load_articles(args.articles)
    allowed = allowed_domains()
    permissions = permission_entries()
    repaired = 0
    eligible = 0
    skipped_risk = 0
    no_allowed_source = 0
    no_image = 0
    rows: list[dict[str, Any]] = []

    for article in articles:
        if clean(article.get("status") or "published").lower() != "published":
            continue
        if not is_generated_or_placeholder(article):
            continue
        if high_risk_photo_story(article):
            skipped_risk += 1
            continue
        if args.limit and eligible >= args.limit:
            break

        eligible += 1
        candidates = source_urls(article)
        # Configured domain restrictions are optional; a publisher domain alone
        # is never taken as permission. The individual image must have rights.
        if allowed:
            candidates = [url for url in candidates if domain_allowed(url, allowed)]
        if not candidates:
            no_allowed_source += 1
            rows.append({
                "slug": clean(article.get("slug")),
                "result": "no-source",
            })
            continue

        updated, reason = try_licensed_source_photo(
            article, candidates[:3], timeout=args.timeout,
            permissions=permissions,
        )
        if updated:
            repaired += 1
        else:
            no_image += 1
        rows.append({
            "slug": clean(article.get("slug")),
            "result": reason,
            "source": candidates[0],
            "after": article.get("image_url"),
        })
        print(f"{reason:24} {clean(article.get('slug') or article.get('title'))}")

    if repaired:
        atomic_write_json(args.articles, articles)
    report = {
        "eligible_placeholders": eligible,
        "repaired_with_source_photo": repaired,
        "skipped_sensitive_stories": skipped_risk,
        "no_allowed_source": no_allowed_source,
        "no_usable_source_image": no_image,
        "permission_entries": len(permissions),
        "allowed_domains": sorted(allowed),
        "items": rows,
    }
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "eligible_placeholders", "repaired_with_source_photo",
        "skipped_sensitive_stories", "no_allowed_source", "no_usable_source_image",
    )}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
