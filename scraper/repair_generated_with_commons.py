#!/usr/bin/env python3
"""Replace generated article cards with relevant Wikimedia Commons photographs.

This is a conservative last-resort pass. Editor-curated cards and permitted
publisher lead photographs are tried first by the normal image pipeline. This
script only touches articles still carrying a generated/placeholder card.

A Commons result is accepted only when it is a freely licensed bitmap and its
file title overlaps the story/area terms. Crime stories are excluded: attaching
a generic place photograph to an alleged offence can falsely imply that the
pictured premises are connected with the incident.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from PIL import Image

from backfill_article_images import atomic_write_json, clean, load_articles
from repair_generated_article_images import is_generated_or_placeholder, slug_for

API = "https://commons.wikimedia.org/w/api.php"
CARDS_DIR = Path("assets/img/cards")
UA = "RochdaleDailyCommonsImage/1.0 (news@rochdaledaily.co.uk)"
FREE_LICENSE_HINTS = ("cc by", "cc-by", "cc0", "public domain", "pd-")
STOP = {
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "at", "for", "from",
    "with", "after", "before", "over", "under", "into", "near", "new", "latest",
    "rochdale", "borough", "greater", "manchester", "says", "set", "could", "will",
}
PLACE_TYPES = (
    "road", "street", "lane", "park", "library", "reservoir", "canal", "station",
    "school", "academy", "college", "church", "mosque", "hall", "hospital",
    "infirmary", "stadium", "lake", "bridge", "interchange", "prison", "centre",
)


def words(value: Any) -> list[str]:
    return [w for w in re.sub(r"[^a-z0-9]+", " ", clean(value).lower()).split() if len(w) >= 3 and w not in STOP]


def named_place(title: str) -> str:
    # Pull a short capitalised place phrase ending in a recognisable place type.
    types = "|".join(PLACE_TYPES)
    pattern = re.compile(rf"\b((?:[A-Z][A-Za-z'’-]*\s+){{0,4}}(?:{types}))\b", re.I)
    matches = [m.group(1).strip() for m in pattern.finditer(title)]
    if not matches:
        return ""
    # Prefer the most specific phrase rather than a bare generic word such as Park.
    return max(matches, key=lambda value: (len(value.split()), len(value)))


def query_for(article: dict[str, Any]) -> str:
    """The story's named subject (image_hierarchy.subject_for), or "".

    Measured 6 Nov 2026: this pass checked 145 stories and repaired none.
    named_place() was compiled with re.I, so its "capitalised words" matched
    any words and the search became the headline ("goblins move Rochdale
    Parish Church Rochdale"); with no named place it fell back to the area or
    to six headline words. Commons needs every word to match, so nothing
    came back, and an area photo would only have decorated the story. One
    rule now serves both Commons paths: a named subject, or no search."""
    from image_hierarchy import subject_for
    return subject_for(article)


def strip_tags(value: Any) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", clean(value))).strip()


def request_json(params: dict[str, Any], timeout: int) -> dict[str, Any]:
    url = API + "?" + urlencode(params)
    req = Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def search(article: dict[str, Any], timeout: int) -> list[dict[str, Any]]:
    data = request_json({
        "action": "query",
        "generator": "search",
        "gsrsearch": '"' + query_for(article) + '"',
        "gsrnamespace": 6,
        "gsrlimit": 12,
        "prop": "imageinfo",
        "iiprop": "url|extmetadata|mime",
        "iiurlwidth": 1200,
        "format": "json",
        "formatversion": 2,
    }, timeout)
    return list((data.get("query") or {}).get("pages") or [])


def score(article: dict[str, Any], page: dict[str, Any]) -> int:
    title_words = set(words(article.get("title")))
    area_words = set(words(article.get("area")))
    file_words = set(words(page.get("title")))
    overlap = len(title_words & file_words)
    area_overlap = len(area_words & file_words)
    place = named_place(clean(article.get("title")))
    place_words = set(words(place))
    place_overlap = len(place_words & file_words)
    # Named-place matches are strongest; otherwise require real subject overlap.
    return place_overlap * 8 + overlap * 3 + area_overlap * 2


def acceptable(article: dict[str, Any], page: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """image_hierarchy.acceptable: a bitmap under CC BY, CC BY-SA, CC0 or public
    domain (never NC or ND: the site carries advertising), whose title or
    description contains every word of the named subject. The old hint test
    ("cc by" in the licence) also passed CC BY-NC."""
    from image_hierarchy import acceptable as hierarchy_acceptable
    info = ((page.get("imageinfo") or [{}])[0])
    subject = query_for(article)
    return bool(subject) and hierarchy_acceptable(page, subject, article), info


def download(url: str, target: Path, timeout: int) -> bool:
    req = Request(url, headers={"User-Agent": UA, "Accept": "image/jpeg,image/png,image/webp,*/*;q=0.1"})
    with urlopen(req, timeout=timeout) as response:
        payload = response.read(12 * 1024 * 1024 + 1)
    if len(payload) > 12 * 1024 * 1024 or len(payload) < 4096:
        return False
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_bytes(payload)
    try:
        with Image.open(temp) as image:
            image.verify()
        with Image.open(temp) as image:
            if image.width < 400 or image.height < 220:
                temp.unlink(missing_ok=True)
                return False
            rgb = image.convert("RGB")
            rgb.thumbnail((1600, 1200))
            rgb.save(target, "JPEG", quality=88, optimize=True)
    finally:
        temp.unlink(missing_ok=True)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--articles", type=Path, default=Path("articles.json"))
    parser.add_argument("--report", type=Path, default=Path("commons_image_repair_report.json"))
    parser.add_argument("--timeout", type=int, default=10)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv or sys.argv[1:])

    articles = load_articles(args.articles)
    repaired = 0
    checked = 0
    rows: list[dict[str, Any]] = []
    CARDS_DIR.mkdir(parents=True, exist_ok=True)

    for article in articles:
        if clean(article.get("status") or "published").lower() != "published":
            continue
        if clean(article.get("category")).lower() == "crime":
            continue
        if not is_generated_or_placeholder(article):
            continue
        if args.limit and checked >= args.limit:
            break
        checked += 1
        if not query_for(article):
            rows.append({"slug": clean(article.get("slug")), "result": "no-specific-subject"})
            continue
        best: tuple[int, dict[str, Any], dict[str, Any]] | None = None
        try:
            pages = search(article, args.timeout)
        except Exception as exc:
            rows.append({"slug": clean(article.get("slug")), "result": "search-failed", "error": str(exc)[:160]})
            continue
        for page in pages:
            ok, info = acceptable(article, page)
            if not ok:
                continue
            candidate = (score(article, page), page, info)
            if best is None or candidate[0] > best[0]:
                best = candidate
        if best is None:
            rows.append({"slug": clean(article.get("slug")), "result": "no-relevant-commons-image", "query": query_for(article)})
            continue

        _, page, info = best
        source_url = clean(info.get("thumburl") or info.get("url"))
        if not source_url:
            continue
        target = CARDS_DIR / f"{slug_for(article)}.jpg"
        try:
            if not download(source_url, target, args.timeout):
                rows.append({"slug": clean(article.get("slug")), "result": "download-rejected"})
                continue
        except Exception as exc:
            rows.append({"slug": clean(article.get("slug")), "result": "download-failed", "error": str(exc)[:160]})
            continue

        meta = info.get("extmetadata") or {}
        artist = strip_tags((meta.get("Artist") or {}).get("value")) or "Wikimedia Commons contributor"
        license_name = strip_tags((meta.get("LicenseShortName") or {}).get("value"))
        page_url = clean(info.get("descriptionurl")) or "https://commons.wikimedia.org/wiki/" + clean(page.get("title")).replace(" ", "_")
        article["image_url"] = target.as_posix()
        article["img"] = target.as_posix()
        article["image_credit"] = f"{artist} / Wikimedia Commons" + (f" ({license_name})" if license_name else "")
        article["image_credit_url"] = page_url
        article["image_status"] = "commons-photo-cached"
        article["image_backfill_method"] = "wikimedia-commons"
        article["source_image_reuse_status"] = "commons-free-license"
        article.pop("image_placeholder_reason", None)
        repaired += 1
        rows.append({
            "slug": clean(article.get("slug")),
            "result": "repaired",
            "query": query_for(article),
            "commons_title": page.get("title"),
            "image_url": target.as_posix(),
            "credit_url": page_url,
        })
        print(f"commons-repaired   {clean(article.get('slug') or article.get('title'))}")

    if repaired:
        atomic_write_json(args.articles, articles)
    report = {"checked_placeholders": checked, "repaired_with_commons": repaired, "items": rows}
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"checked_placeholders": checked, "repaired_with_commons": repaired}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
