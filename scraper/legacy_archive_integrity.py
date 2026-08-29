#!/usr/bin/env python3
"""Audit retained static Rochdale Daily article pages.

The current newsroom archive (articles.json) is handled by story_integrity_audit.py,
but hundreds of older static article pages remain reachable and searchable. This
module audits those retained pages as well.

It checks three things:
1. high-confidence section/category mistakes in the page metadata and visible UI;
2. the page's canonical/social image for obvious semantic mismatches;
3. every related-story thumbnail, ensuring it is the canonical image belonging
   to the headline it sits beside rather than an image accidentally copied from
   another story.

Default mode is report-only. --apply performs only conservative corrections.
"""
from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path
from typing import Any

from ensure_article_images import set_generated
from story_integrity_audit import clean, headline_category, visual_family_mismatch

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "articles"
REPORT = ROOT / "reports" / "legacy_story_integrity_audit.json"
SITE = "https://rochdaledaily.co.uk/"


def meta(source: str, key: str) -> str:
    patterns = (
        rf'<meta[^>]+property=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']*)',
        rf'<meta[^>]+name=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']*)',
    )
    for pattern in patterns:
        match = re.search(pattern, source, re.I)
        if match:
            return html.unescape(match.group(1)).strip()
    return ""


def visible_text(source: str, pattern: str) -> str:
    match = re.search(pattern, source, re.I | re.S)
    if not match:
        return ""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", match.group(1)))).strip()


def title_of(source: str) -> str:
    title = meta(source, "og:title") or visible_text(source, r"<h1[^>]*>(.*?)</h1>")
    return re.sub(r"\s*[|–-]\s*Rochdale Daily\s*$", "", title, flags=re.I).strip()


def category_of(source: str) -> str:
    return (
        meta(source, "article:section")
        or visible_text(source, r'<span[^>]+class=["\'][^"\']*story-kicker[^"\']*["\'][^>]*>(.*?)</span>')
        or "News"
    ).strip().lower()


def og_image_of(source: str) -> str:
    return meta(source, "og:image")


def is_generated_image(url: str) -> bool:
    value = clean(url).lower()
    return any(token in value for token in ("generated-card", "area-category-card", "placeholder"))


def image_reason(record: dict[str, Any], proposed_category: str) -> str:
    url = clean(record.get("image"))
    if not url:
        return "missing canonical/social image"

    pseudo = {
        "title": record.get("title", ""),
        "excerpt": record.get("description", ""),
        "category": proposed_category,
        "image_url": url,
        "img": url,
        "image_match_title": Path(url.split("?", 1)[0]).name,
    }
    mismatch, reason = visual_family_mismatch(pseudo)
    if mismatch:
        return reason

    # An old generated category card can have the wrong section embedded in the
    # artwork after a category correction. Regenerate it from the corrected
    # headline/category rather than preserving a stale visual label.
    if proposed_category != record.get("category") and is_generated_image(url):
        return "generated card belongs to the old category and must be rebuilt"
    return ""


def replace_meta_content(source: str, key: str, value: str) -> str:
    pattern = re.compile(
        rf'(<meta[^>]+(?:property|name)=["\']{re.escape(key)}["\'][^>]+content=["\'])([^"\']*)(["\'])',
        re.I,
    )
    return pattern.sub(lambda m: m.group(1) + html.escape(value, quote=True) + m.group(3), source)


def replace_category(source: str, old: str, new: str) -> str:
    old_display = old.title()
    new_display = new.title()
    old_anchor = re.escape(old.lower())

    source = replace_meta_content(source, "article:section", new_display)

    # Keywords are secondary metadata, but leaving the old section there sends
    # contradictory classification signals to search engines.
    def kw(m: re.Match[str]) -> str:
        value = m.group(2)
        value = re.sub(rf'(?i)(^|,\s*){re.escape(old_display)}(?=\s*,|$)', lambda x: x.group(1) + new_display, value)
        return m.group(1) + html.escape(value, quote=True) + m.group(3)
    source = re.sub(
        r'(<meta[^>]+name=["\']keywords["\'][^>]+content=["\'])([^"\']*)(["\'])',
        kw,
        source,
        flags=re.I,
    )

    source = re.sub(
        r'("articleSection"\s*:\s*")[^"]*(")',
        lambda m: m.group(1) + new_display + m.group(2),
        source,
        flags=re.I,
    )
    source = re.sub(
        rf'("position"\s*:\s*2\s*,\s*"name"\s*:\s*"){re.escape(old_display)}("\s*,\s*"item"\s*:\s*"https://rochdaledaily\.co\.uk/#){old_anchor}("\s*\}})',
        lambda m: m.group(1) + new_display + m.group(2) + new.lower() + m.group(3),
        source,
        flags=re.I,
    )
    source = re.sub(
        rf'(<a\s+href=["\']\.\./index\.html#){old_anchor}(["\'][^>]*>){re.escape(old_display)}(</a>)',
        lambda m: m.group(1) + new.lower() + m.group(2) + new_display + m.group(3),
        source,
        flags=re.I,
    )
    source = re.sub(
        rf'(<span[^>]+class=["\'][^"\']*story-kicker[^"\']*["\'][^>]*>){re.escape(old_display)}(</span>)',
        lambda m: m.group(1) + new_display + m.group(2),
        source,
        flags=re.I,
    )
    source = re.sub(
        rf'(<div[^>]+class=["\'][^"\']*sidebar-box[^"\']*["\'][^>]*>\s*<h3>More in ){re.escape(old_display)}(</h3>)',
        lambda m: m.group(1) + new_display + m.group(2),
        source,
        flags=re.I,
    )
    # Category-specific archive bylines are stale after reclassification. Use a
    # neutral newsroom byline rather than inventing a new specialist desk.
    source = re.sub(
        rf'(<div[^>]+class=["\'][^"\']*article-byline[^"\']*["\'][^>]*>By\s+Rochdale Daily\s+){re.escape(old_display)}(</div>)',
        r'\1Newsdesk\2',
        source,
        flags=re.I,
    )
    return source


def generated_card(record: dict[str, Any], category: str) -> str:
    article = {
        "slug": record["slug"],
        "title": record["title"],
        "excerpt": record.get("description", ""),
        "area": "rochdale",
        "category": category,
        "types": [category],
        "image_url": "",
        "img": "",
    }
    set_generated(article, ROOT)
    return clean(article.get("image_url") or article.get("img"))


def replace_primary_image(source: str, old_url: str, new_path: str) -> str:
    absolute = new_path if re.match(r"https?://", new_path, re.I) else SITE + new_path.lstrip("/")
    source = replace_meta_content(source, "og:image", absolute)
    source = replace_meta_content(source, "twitter:image", absolute)
    source = re.sub(
        r'("image"\s*:\s*\[\s*")[^"]*("\s*\])',
        lambda m: m.group(1) + absolute + m.group(2),
        source,
        count=1,
        flags=re.I,
    )

    # Only replace the page's explicit hero/modal image. Never globally replace
    # the URL: the same old image may also be incorrectly attached to a
    # different related-story headline, which is repaired separately below.
    source = re.sub(
        r'(<img[^>]+class=["\'][^"\']*(?:modal-image|article-hero-image)[^"\']*["\'][^>]+src=["\'])[^"\']*(["\'])',
        lambda m: m.group(1) + html.escape(absolute, quote=True) + m.group(2),
        source,
        flags=re.I,
    )
    return source


RELATED_RE = re.compile(
    r'(<a[^>]+class=["\'][^"\']*related-story[^"\']*["\'][^>]+href=["\'](?P<href>[^"\']+)["\'][^>]*>\s*'
    r'<img[^>]+src=["\'])(?P<img>[^"\']*)(["\'][^>]*>.*?'
    r'<span[^>]+class=["\'][^"\']*related-title[^"\']*["\'][^>]*>.*?</span>\s*</a>)',
    re.I | re.S,
)


def related_target_slug(href: str) -> str:
    value = href.split("#", 1)[0].split("?", 1)[0].strip()
    if not value or re.match(r"https?://", value, re.I):
        match = re.search(r"/articles/([^/?#]+)\.html", value, re.I)
        return match.group(1) if match else ""
    return Path(value).stem


def repair_related_images(source: str, page_slug: str, canonical: dict[str, str], issues: list[dict[str, Any]], apply: bool) -> str:
    def repl(match: re.Match[str]) -> str:
        target = related_target_slug(match.group("href"))
        expected = clean(canonical.get(target))
        current = html.unescape(clean(match.group("img")))
        if not target or not expected:
            return match.group(0)
        if current.rstrip("/") == expected.rstrip("/"):
            return match.group(0)
        issues.append({
            "page": page_slug,
            "target_slug": target,
            "current_image": current,
            "expected_image": expected,
        })
        if not apply:
            return match.group(0)
        return match.group(1) + html.escape(expected, quote=True) + match.group(4)
    return RELATED_RE.sub(repl, source)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    current_slugs: set[str] = set()
    current_path = ROOT / "articles.json"
    if current_path.exists():
        current = json.loads(current_path.read_text(encoding="utf-8"))
        rows = current if isinstance(current, list) else current.get("articles", [])
        current_slugs = {clean(a.get("slug")) for a in rows if isinstance(a, dict)}

    records: dict[str, dict[str, Any]] = {}
    sources: dict[str, str] = {}
    for path in sorted(PAGES.glob("*.html")):
        source = path.read_text(encoding="utf-8", errors="ignore")
        title = title_of(source)
        if not title:
            continue
        slug = path.stem
        sources[slug] = source
        records[slug] = {
            "slug": slug,
            "path": str(path.relative_to(ROOT)),
            "title": title,
            "description": meta(source, "description") or meta(source, "og:description"),
            "category": category_of(source),
            "image": og_image_of(source),
            "current_feed": slug in current_slugs,
        }

    category_changes: list[dict[str, Any]] = []
    image_changes: list[dict[str, Any]] = []
    changed_pages: set[str] = set()

    # First pass: category and canonical image. Skip current-feed pages because
    # story_integrity_audit.py is their source of truth and will regenerate them.
    for slug, record in records.items():
        if record["current_feed"]:
            continue
        source = sources[slug]
        old_category = record["category"] or "news"
        proposed = headline_category({"slug": slug, "title": record["title"], "category": old_category}) or old_category
        if proposed != old_category:
            category_changes.append({
                "slug": slug,
                "title": record["title"],
                "from": old_category,
                "to": proposed,
            })
            if args.apply:
                source = replace_category(source, old_category, proposed)
                record["category"] = proposed
                changed_pages.add(slug)

        reason = image_reason(record, proposed)
        if reason:
            item = {
                "slug": slug,
                "title": record["title"],
                "category": proposed,
                "old_image": record["image"],
                "reason": reason,
            }
            if args.apply:
                new_path = generated_card(record, proposed)
                source = replace_primary_image(source, record["image"], new_path)
                absolute = new_path if re.match(r"https?://", new_path, re.I) else SITE + new_path.lstrip("/")
                record["image"] = absolute
                item["new_image"] = absolute
                changed_pages.add(slug)
            image_changes.append(item)
        sources[slug] = source

    # Build the final canonical-image map after any page-image corrections, then
    # repair each related card to use the target story's own canonical image.
    canonical = {slug: clean(record.get("image")) for slug, record in records.items() if clean(record.get("image"))}
    related_image_changes: list[dict[str, Any]] = []
    for slug, source in list(sources.items()):
        updated = repair_related_images(source, slug, canonical, related_image_changes, args.apply)
        if args.apply and updated != source:
            sources[slug] = updated
            changed_pages.add(slug)

    if args.apply:
        for slug in changed_pages:
            (PAGES / f"{slug}.html").write_text(sources[slug], encoding="utf-8")

    report = {
        "policy": "legacy static archive: conservative headline classification, canonical social-image safety, and exact related-headline/image pairing",
        "mode": "apply" if args.apply else "report-only",
        "total_static_pages": len(records),
        "current_feed_pages_skipped": sum(1 for r in records.values() if r["current_feed"]),
        "legacy_pages_audited": sum(1 for r in records.values() if not r["current_feed"]),
        "category_change_count": len(category_changes),
        "image_change_count": len(image_changes),
        "related_image_change_count": len(related_image_changes),
        "changed_page_count": len(changed_pages),
        "category_changes": category_changes,
        "image_changes": image_changes,
        "related_image_changes": related_image_changes,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({k: report[k] for k in (
        "mode", "total_static_pages", "current_feed_pages_skipped", "legacy_pages_audited",
        "category_change_count", "image_change_count", "related_image_change_count", "changed_page_count"
    )}, indent=2))
    for item in category_changes[:120]:
        print(f"CATEGORY {item['from']} -> {item['to']}: {item['title']}")
    for item in image_changes[:80]:
        print(f"IMAGE {item['slug']}: {item['reason']}")
    for item in related_image_changes[:80]:
        print(f"RELATED {item['page']} -> {item['target_slug']}: thumbnail mismatch")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
