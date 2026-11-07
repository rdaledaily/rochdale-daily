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
import licensed_source_images
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


def editor_image_slugs() -> set[str] | None:
    """Slugs of manual stories whose own file names a photo.

    Only those photos are the editor's choice. A manual story whose file names
    no image is given a library picture by the pipeline, which then labels it
    "editorial-photo" like a supplied one, so the label alone cannot tell them
    apart. Returns None if the manual files cannot be read: every manual story
    is then treated as editor-chosen and left alone.
    """
    try:
        import manual_articles
        records = manual_articles.load_manual_article_records()
    except Exception as exc:  # report, never guess
        print(f"::warning::Could not read manual story files ({exc}); manual images left unchanged.")
        return None
    return {clean(row.get("slug")) for row in records if clean(row.get("image_url") or row.get("img"))}


def source_photo_cached(article: dict[str, Any]) -> bool:
    """An organisation's photo for this story was fetched on an earlier run."""
    try:
        known = json.loads((CARDS_DIR / "credits.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        known = {}
    if not isinstance(known, dict):
        return False
    stem = slug_for(article)
    return "Used with permission" in str(known.get(stem, "")) and any(
        (CARDS_DIR / f"{stem}{suffix}").is_file() for suffix in (".jpg", ".jpeg", ".png", ".webp"))


def pipeline_chose_manual_image(article: dict[str, Any], editor_images: set[str] | None) -> bool:
    """Standing editorial rule: when a manual story comes from a granting
    organisation (e.g. the council) and the editor supplied no photo, use that
    organisation's own photo instead of the picture the pipeline attached.
    A photo the editor supplied is never replaced."""
    if editor_images is None:
        return False
    if not (article.get("manual_article") or article.get("editorial_lock")):
        return False
    if clean(article.get("slug")) in editor_images:
        return False
    return not source_photo_cached(article)


def granted_source_upgrade(article: dict[str, Any], now: datetime,
                           grants: list[dict[str, Any]],
                           editor_images: set[str] | None = None) -> bool:
    """A story from a granting organisation should carry that organisation's
    own photo rather than a Commons file image or a generic library picture.

    Scraped stories: recent ones only. Manual/locked stories: only when the
    editor supplied no photo of their own (see pipeline_chose_manual_image),
    at any age. Editor photos and photos already taken from the source are
    never replaced."""
    if not grants:
        return False
    manual_pick = pipeline_chose_manual_image(article, editor_images)
    if (article.get("manual_article") or article.get("editorial_lock")) and not manual_pick:
        return False
    status = clean(article.get("image_status")).lower()
    if "source-photo" in status:
        return False
    if not manual_pick:
        if "editorial-photo" in status:
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


# Council pages that never carry a story photograph: roadworks directory
# records, downloads, service pages. Measured 6 Nov 2026: of 36 council-sourced
# stories in the last 200, 24 came from such pages, and because the repair
# pass works newest-first with a fixed per-run limit, they took every slot on
# every run, so real council press releases (foster carers, 26 Oct) aged out
# of the window without ever being checked.
NO_PHOTO_PAGE_RE = re.compile(
    r"/directory-record/|/downloads/|/counciltax\b|/school-admissions|"
    r"/roadworks-repairs-restrictions/|/houses-multiple-occupation|mgListPlanItems|"
    r"mgCalendar|/LicensingActPremises/",
    re.I,
)
GRANT_BACKLOG_DAYS = 14


def grant_pages(article: dict[str, Any], grants: list[dict[str, Any]]) -> list[str]:
    """Source pages on a granting organisation's own site that can hold a
    story photograph, in source order."""
    pages: list[str] = []
    for url in source_urls(article):
        if url in pages or NO_PHOTO_PAGE_RE.search(url):
            continue
        # A home page's picture is the organisation's banner, not this story's.
        if urlparse(url).path.strip("/") == "":
            continue
        if any(_page_covered(url, grant) for grant in grants):
            pages.append(url)
    return pages


def grant_backlog(article: dict[str, Any], now: datetime, grants: list[dict[str, Any]],
                  editor_images: set[str] | None = None) -> bool:
    """A story from a granting organisation, published in the last
    GRANT_BACKLOG_DAYS, still showing a generated card, a library picture or a
    Commons file image. Editor photos and photos already taken from the source
    are never replaced (same rule as granted_source_upgrade)."""
    if not grants or not grant_pages(article, grants):
        return False
    status = clean(article.get("image_status")).lower()
    if "source-photo" in status:
        return False
    if article.get("manual_article") or article.get("editorial_lock"):
        if not pipeline_chose_manual_image(article, editor_images):
            return False
    elif "editorial-photo" in status:
        return False
    if not _recent(article, now, hours=24 * GRANT_BACKLOG_DAYS):
        return False
    category = clean(article.get("category")).casefold()
    return any(_page_covered(url, grant) and category not in grant["exclude_categories"]
               for url in grant_pages(article, grants) for grant in grants)


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


def record_credit(target: Path, credit_line: str) -> None:
    """Write the credit into assets/img/cards/credits.json so it survives.

    Manual stories are rebuilt from the editor's files every run; the photo is
    then re-selected by its slug filename through set_curated, which takes its
    credit from credits.json. Without this entry the organisation's credit
    would become "Rochdale Daily" on the next run.
    """
    path = target.parent / "credits.json"
    try:
        credits = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        credits = {}
    if not isinstance(credits, dict):
        credits = {}
    if credits.get(target.stem) == credit_line:
        return
    credits[target.stem] = credit_line
    path.write_text(json.dumps(credits, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--articles", type=Path, default=Path("articles.json"))
    parser.add_argument("--report", type=Path, default=Path("image_repair_report.json"))
    parser.add_argument("--no-gmp-match", action="store_true", help="skip the GMP release lookup (tests, offline runs)")
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
    for suffix in (".jpg", ".jpeg", ".png", ".webp"):
        cached = CARDS_DIR / f"{slug_for(article)}{suffix}"
        try:
            known = json.loads((CARDS_DIR / "credits.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            known = {}
        if cached.is_file() and isinstance(known, dict) and "Used with permission" in str(known.get(cached.stem, "")):
            # Already fetched on an earlier run; ensure_article_images re-selects it
            # by slug with its recorded credit. No need to hit the source again.
            return False, "source-photo-already-cached"
    for source_url in candidates:
        try:
            result = fetch_licensed_source_image(
                source_url, permissions=permissions, timeout=timeout,
                grants=grants or [], category=article.get("category"),
                skip_urls=skip_urls, user_agent=DEFAULT_USER_AGENT,
            )
        except (OSError, ValueError, TimeoutError, ConnectionError) as exc:
            article["_image_diagnosis"] = {"page": source_url, "verdict": f"page-fetch-failed: {str(exc)[:120]}"}
            continue
        if result is None:
            article["_image_diagnosis"] = dict(licensed_source_images.LAST_DIAGNOSIS)
            continue

        candidate, payload, extension, rights = result
        try:
            with Image.open(io.BytesIO(payload)) as image:
                image.verify()
        except (OSError, ValueError, UnidentifiedImageError):
            continue

        target = CARDS_DIR / f"{slug_for(article)}{extension}"
        if target.is_file() and target.read_bytes() == payload:
            # The SAME permitted photo was cached by an earlier run whose credit
            # was not recorded (before credits.json was written). Record it now
            # rather than skipping, so the organisation's credit is restored.
            pass
        elif target.is_file():
            # A genuinely existing editor-supplied same-slug photograph wins;
            # the source photo must never overwrite an approved edit.
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file():
            target.write_bytes(payload)

        credit = (rights.get("creator") or "Original source").strip()
        licence = (rights.get("license_name") or "Used with permission").strip()
        record_credit(target, f"{credit} / {licence}")
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
    editor_images = editor_image_slugs() if grants else None
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
    # GMP's own release for crime and police stories that reached the paper
    # through other outlets (gmp_release_match.py). Report-only unless
    # GMP_RELEASE_MATCH=apply; in apply mode the release joins the story's
    # sources and the granted-source step below takes its photo.
    gmp_release = {"mode": "off"}
    if grants and any(g["organisation"] == "Greater Manchester Police" for g in grants) and not args.no_gmp_match:
        from gmp_release_match import run as match_gmp_releases
        gmp_release = match_gmp_releases(articles)
    # Newly published articles take priority over retrospective image repairs.
    candidates_by_age = sorted(articles, key=lambda row: clean(row.get("first_published_at") or row.get("published_at")), reverse=True)
    # Stories whose source is a granting organisation's own page go first:
    # they are the only ones a photo can actually be found for. Everything
    # else (other publishers, which need an image-level licence) uses whatever
    # of the per-run limit is left.
    queue: list[tuple[dict[str, Any], bool, list[str]]] = []
    for article in candidates_by_age:
        if clean(article.get("status") or "published").lower() != "published":
            continue
        upgrade = False
        pages = grant_pages(article, grants)
        if pages and grant_backlog(article, now, grants, editor_images):
            upgrade = not is_generated_or_placeholder(article)
        elif not needs_source_photo_check(article, now):
            if not granted_source_upgrade(article, now, grants, editor_images):
                continue
            upgrade = True
        queue.append((article, upgrade, pages))
    queue.sort(key=lambda row: 0 if row[2] else 1)  # stable: newest first within each group

    for article, upgrade, pages in queue:
        # Crime, court and sensitive stories: no guessed picture, but the photo
        # the permitted source published with its own release (a GMP appeal,
        # a council notice) is the story's photo and is used (editor's rule,
        # 7 Nov 2026). Only the granted pages are tried for these stories.
        risky = high_risk_photo_story(article)
        if risky and not pages:
            skipped_risk += 1
            continue
        if args.limit and eligible >= args.limit:
            break

        eligible += 1
        candidates = pages if risky else pages + [url for url in source_urls(article)
                                                  if url not in pages and not NO_PHOTO_PAGE_RE.search(url)]
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
        row = {
            "slug": clean(article.get("slug")),
            "result": reason,
            "source": candidates[0],
            "after": article.get("image_url"),
        }
        diagnosis = article.pop("_image_diagnosis", None)
        if diagnosis and not updated:
            row["why"] = diagnosis
        rows.append(row)
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
        "gmp_release_matches": gmp_release,
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
