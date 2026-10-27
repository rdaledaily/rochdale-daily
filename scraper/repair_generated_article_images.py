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
from datetime import datetime, timezone, timedelta
from typing import Any
from urllib.parse import urlparse

from PIL import Image, UnidentifiedImageError

from ensure_article_images import high_risk_photo_story
from licensed_source_images import (
    canonical, fetch_licensed_source_image, inactive_grants,
    permission_entries, source_grants,
)

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


def _recent(article: dict[str, Any], now: datetime, hours: int = 48) -> bool:
    raw = clean(article.get("first_published_at") or article.get("published_at"))
    try:
        published = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    return now - timedelta(hours=hours) <= published <= now + timedelta(minutes=10)


def granted_source_upgrade(article: dict[str, Any], now: datetime,
                           grants: list[dict[str, Any]]) -> bool:
    """A recent story from a granting organisation should carry that
    organisation's own photo rather than a Commons file image or a generic
    library picture. Editor photos, manual/locked stories and photos already
    taken from the source are never replaced."""
    if not grants or article.get("manual_article") or article.get("editorial_lock"):
        return False
    status = clean(article.get("image_status")).lower()
    if any(token in status for token in ("source-photo", "editorial-photo")):
        return False
    if not _recent(article, now):
        return False
    category = clean(article.get("category")).casefold()
    return any(_page_covered(url, grant) and category not in grant["exclude_categories"]
               for url in source_urls(article) for grant in grants)


def _page_covered(url: str, grant: dict[str, Any]) -> bool:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    return any(host == h or host.endswith("." + h) for h in grant["source_hosts"])


def needs_source_photo_check(article: dict[str, Any], now: datetime) -> bool:
    """Prefer verified original-source images over automated library selections.

    A manual/editorial photo is always authoritative. Older library photos
    remain untouched; this is for newly published stories, where the source
    image can be found without revisiting the entire archive each hour.
    """
    if is_generated_or_placeholder(article):
        return True
    if article.get("manual_article") or article.get("editorial_lock"):
        return False
    if clean(article.get("image_status")).lower() != "cards-library-photo":
        return False
    if clean(article.get("image_backfill_method")) != "cards-filename-match":
        return False
    raw = clean(article.get("first_published_at") or article.get("published_at"))
    try:
        published = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    return now - timedelta(hours=48) <= published <= now + timedelta(minutes=10)


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
    grants: list[dict[str, Any]] | None = None,
    skip_urls: set[str] | frozenset[str] = frozenset(),
) -> tuple[bool, str]:
    """Set an approved original-source photograph; do not touch story facts."""
    for source_url in candidates:
        try:
            result = fetch_licensed_source_image(
                source_url, permissions=permissions, timeout=timeout,
                grants=grants or [], category=article.get("category"),
                skip_urls=skip_urls, user_agent=DEFAULT_USER_AGENT,
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
        previous = clean(article.get("image_url"))
        article["image_url"] = target.as_posix()
        article["img"] = target.as_posix()
        if previous and previous != target.as_posix():
            article["image_replaced"] = previous
        article["image_credit"] = f"{credit} / {licence}"
        article["image_credit_url"] = rights.get("evidence_url") or source_url
        article["image_license_url"] = rights.get("license_url") or ""
        article["image_license"] = licence
        article["source_image_candidate_url"] = candidate.url
        if rights.get("evidence_ref"):
            article["image_permission_ref"] = rights["evidence_ref"]
            article["image_alt"] = clean(article.get("title"))
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
    grants = source_grants()
    # A picture already attached to a story from a DIFFERENT source page is the
    # organisation's default share image, not a story photo.
    used_by: dict[str, set[str]] = {}
    for row in articles:
        key = canonical(row.get("source_image_candidate_url"))
        if key:
            used_by.setdefault(key, set()).add(clean(row.get("source_url")))
    repaired = 0
    granted_upgrades = 0
    eligible = 0
    skipped_risk = 0
    no_allowed_source = 0
    no_image = 0
    rows: list[dict[str, Any]] = []

    now = datetime.now(timezone.utc)
    # Newly published articles take priority over retrospective image repairs.
    candidates_by_age = sorted(articles, key=lambda row: clean(row.get("first_published_at") or row.get("published_at")), reverse=True)
    for article in candidates_by_age:
        if clean(article.get("status") or "published").lower() != "published":
            continue
        upgrade = False
        if not needs_source_photo_check(article, now):
            if not granted_source_upgrade(article, now, grants):
                continue
            upgrade = True
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

        own = clean(article.get("source_url"))
        skip = {url for url, pages in used_by.items() if pages - {own}}
        updated, reason = try_licensed_source_photo(
            article, candidates[:3], timeout=args.timeout,
            permissions=permissions, grants=grants, skip_urls=skip,
        )
        if updated:
            repaired += 1
            granted_upgrades += int(upgrade)
            key = canonical(article.get("source_image_candidate_url"))
            if key:
                used_by.setdefault(key, set()).add(own)
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
        "source_grants_active": [g["organisation"] for g in grants],
        "source_grants_incomplete": inactive_grants(),
        "replaced_commons_or_library_with_source_photo": granted_upgrades,
        "allowed_domains": sorted(allowed),
        "items": rows,
    }
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "eligible_placeholders", "repaired_with_source_photo",
        "skipped_sensitive_stories", "no_allowed_source", "no_usable_source_image",
        "source_grants_active", "source_grants_incomplete",
        "replaced_commons_or_library_with_source_photo",
    )}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
