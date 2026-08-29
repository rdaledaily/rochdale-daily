#!/usr/bin/env python3
"""Whole-archive editorial integrity audit for Rochdale Daily.

This is deliberately conservative. It corrects only high-confidence category
mistakes and removes/replaces images that cannot be defended from the article
metadata. A neutral Rochdale Daily headline card is preferable to a misleading
photo of a hospital, police scene, school, court, person or other institution.

Run modes:
  classify  -- category/type corrections only
  final     -- category corrections plus image safety enforcement and report
  check     -- do not write; fail if a high-confidence issue remains
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from ensure_article_images import set_generated

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_CATEGORIES = {
    "business", "community", "crime", "education", "environment", "events", "health",
    "news", "politics", "sport", "traffic", "transport",
}


def clean(value: Any) -> str:
    return str(value or "").strip()


def words(value: Any) -> str:
    return re.sub(r"\s+", " ", clean(value)).strip()


def text(article: dict[str, Any], *fields: str) -> str:
    return " ".join(words(article.get(field)) for field in fields if article.get(field))


def hit(pattern: str, value: str) -> bool:
    return bool(re.search(pattern, value, re.I | re.S))


# Headline-first rules. These are intentionally high precision. The previous
# failure mode was body vocabulary (for example "mental health" in a list of
# priorities) overriding the actual subject of the story.
HEADLINE_RULES: tuple[tuple[str, str], ...] = (
    ("community", r"\b(?:youth council|youth cabinet|youth parliament|young people'?s council)\b"),
    ("crime", r"\b(?:murder|manslaughter|rape|rapist|grooming gang|sexual (?:assault|offence|abuse)|"
              r"stabbing|shooting|robbery|burglary|theft|fraud|arrested?|charged|convicted|sentenced|"
              r"jailed|prison|court hearing|magistrates'? court|crown court|police appeal|wanted (?:man|woman|person)|"
              r"drug raid|cannabis farm|deportation|parole)\b"),
    ("traffic", r"\b(?:roadworks?|road works?|road closure|road closed|lane closure|traffic|"
                r"collision|crash|congestion|diversion|potholes?|speeding|M62|A627(?:\(M\))?)\b"),
    ("transport", r"\b(?:train|railway|rail service|tram|metrolink|bee network|bus service|buses|"
                  r"bus route|station|timetable|public transport|northern rail|service disruption)\b"),
    ("education", r"\b(?:school|academy|college|university|ofsted|teacher|headteacher|pupil|"
                  r"student|GCSE|A[- ]level|education results?|exam results?)\b"),
    ("sport", r"\b(?:rochdale afc|rochdale hornets|football|rugby|cricket|boxing|netball|athletics|"
              r"parkrun|MMA|muay thai|fixture|match|league|cup tie|goalkeeper|striker|manager .{0,35} victory|"
              r"defender|midfielder|forward|sports? club|tennis|badminton|basketball)\b"),
    ("events", r"\b(?:festival|concert|gig|exhibition|performance|parade|fair|"
               r"bingo|open day|community event|live music|show at|tour at)\b"),
    ("news", r"\b(?:restoration of historic|historic .{0,45} restored|heritage restoration|"
             r"listed building restoration|historic steps)\b"),
    ("politics", r"\b(?:councillor|council leader|council cabinet|council budget|council tax|"
                 r"local election|general election|by[- ]election|mayor|member of parliament|\bMP\b|"
                 r"parliament|minister|manifesto|political party|labour party|conservative party|"
                 r"reform uk|liberal democrats?|workers party)\b"),
    ("health", r"\b(?:NHS|hospital|infirmary|doctor|GP\b|general practice|clinic|patient|pharmacy|"
               r"vaccination|health service|mental health (?:service|support|session|team|clinic)|"
               r"fitness session|exercise class|wellbeing service)\b"),
    ("environment", r"\b(?:flood|flooding|weather warning|weather forecast|heatwave|met office|"
                    r"reservoir|recycling|litter|fly.?tipping|waste collection|landfill|"
                    r"wildlife|biodiversity|nature reserve|woodland|tree planting|tree felling|"
                    r"pollution|air quality|sewage|climate|net zero|moor fire|green belt|canal|river)\b"),
    ("community", r"\b(?:charity|fundraiser|fundraising|food ?bank|volunteer|community group|"
                  r"community centre|support group|homelessness|rough sleeper|church|mosque|"
                  r"residents'? group|community project|community award|local hero)\b"),
    ("business", r"\b(?:business|company|shop|store|restaurant|pub|cafe|café|takeaway|retail|"
                 r"commercial|investment|regeneration|housing development|new homes|apartments?|"
                 r"appoints? .{0,40} (?:chair|chief executive|CEO|director))\b"),
)

SUPPORT_RULES: tuple[tuple[str, str], ...] = (
    ("crime", r"\b(?:police|court|offence|offender|arrest|charged|sentenced|jailed|investigation)\b"),
    ("traffic", r"\b(?:road|motorway|traffic|closure|lane|junction|carriageway)\b"),
    ("transport", r"\b(?:bus|train|tram|rail|station|metrolink|transport)\b"),
    ("politics", r"\b(?:council|councillor|election|mayor|parliament|minister|\bMP\b)\b"),
    ("education", r"\b(?:school|college|pupil|student|teacher|ofsted|GCSE|A[- ]level)\b"),
    ("health", r"\b(?:NHS|hospital|GP\b|doctor|patient|clinic|health service|pharmacy)\b"),
    ("community", r"\b(?:community|charity|volunteer|residents|youth council|support group|homeless)\b"),
    ("events", r"\b(?:festival|concert|gig|exhibition|performance|parade|event|bingo)\b"),
    ("business", r"\b(?:business|company|shop|restaurant|retail|commercial|investment|development)\b"),
    ("environment", r"\b(?:flood|weather|environment|recycling|wildlife|reservoir|pollution|climate)\b"),
    ("sport", r"\b(?:football|rugby|cricket|match|fixture|club|league|cup|player|manager)\b"),
)

VISUAL_FAMILIES: dict[str, tuple[str, ...]] = {
    "health": ("hospital", "infirmary", "ambulance", "nhs", "doctor", "medical", "clinic", "gp-", "gp_", "pharmacy"),
    "crime": ("police", "court", "prison", "jail", "handcuff", "knife", "grooming", "crime-scene", "crime_scene"),
    "education": ("school", "academy", "college", "university", "classroom", "pupil"),
    "traffic": ("roadworks", "road-closure", "road_closure", "traffic", "motorway", "collision", "crash"),
    "sport": ("football", "rugby", "cricket", "hornets", "rochdale-afc", "rochdale_afc", "fixture"),
}

GENERATED_MARKERS = ("generated-card", "area-category-card", "placeholder")
SAFE_REAL_STATUSES = ("source-photo", "commons-photo", "editorial-photo")
UNSAFE_GENERIC_IMG_ONLY_STATUSES = ("source-photo-cached", "cards-library-photo")


def headline_category(article: dict[str, Any]) -> str | None:
    title = text(article, "title")
    for category, pattern in HEADLINE_RULES:
        if hit(pattern, title):
            return category

    brief = text(article, "title", "excerpt", "summary", "description")
    scores: Counter[str] = Counter()
    for category, pattern in SUPPORT_RULES:
        matches = re.findall(pattern, brief, re.I | re.S)
        if matches:
            scores[category] += min(3, len(matches))
    if not scores:
        return None
    category, score = scores.most_common(1)[0]
    return category if score >= 2 else None


def category_reason(article: dict[str, Any], new_category: str) -> str:
    title = clean(article.get("title"))
    if hit(r"\byouth council|youth cabinet|youth parliament\b", title):
        return "youth civic body is a community story, not health/politics by incidental vocabulary"
    return f"headline/standfirst strongly identify {new_category}"


def apply_category(article: dict[str, Any], changes: list[dict[str, Any]]) -> None:
    if clean(article.get("status")).lower() not in {"", "published"}:
        return
    current = clean(article.get("category")).lower() or "news"
    proposed = headline_category(article)
    if proposed is None:
        if current not in ALLOWED_CATEGORIES:
            proposed = "news"
        else:
            return
    if proposed not in ALLOWED_CATEGORIES or proposed == current:
        return

    old_types = list(article.get("types") or [])
    article["category"] = proposed
    if old_types:
        article["types"] = [proposed if clean(v).lower() == current else v for v in old_types]
        if proposed not in [clean(v).lower() for v in article["types"]]:
            article["types"] = [proposed]
    else:
        article["types"] = [proposed]
    changes.append({
        "slug": clean(article.get("slug")),
        "title": clean(article.get("title")),
        "from": current,
        "to": proposed,
        "reason": category_reason(article, proposed),
    })


def local_image_value(article: dict[str, Any]) -> str:
    return clean(article.get("image_url") or article.get("img")).replace("\\", "/")


def image_filename_blob(article: dict[str, Any]) -> str:
    return " ".join([
        local_image_value(article),
        clean(article.get("image_match_title")),
        clean(article.get("source_image_candidate_url")),
    ]).lower()


def generated_image(article: dict[str, Any]) -> bool:
    value = image_filename_blob(article)
    status = clean(article.get("image_status")).lower()
    return any(marker in value or marker in status for marker in GENERATED_MARKERS) or "cards-generated" in status


def source_evidence(article: dict[str, Any]) -> bool:
    canonical = clean(article.get("image_url"))
    if not canonical:
        return False
    status = clean(article.get("image_status")).lower()
    if any(token in status for token in SAFE_REAL_STATUSES):
        return True
    if clean(article.get("source_image_candidate_url")):
        return True
    if article.get("manual_article") is True and "editorial" in clean(article.get("source_kind")).lower():
        return True
    return False


def visual_family_mismatch(article: dict[str, Any]) -> tuple[bool, str]:
    blob = image_filename_blob(article)
    if not blob:
        return False, ""
    category = clean(article.get("category")).lower()
    title = text(article, "title", "excerpt").lower()
    title_support = {
        "health": r"\b(?:hospital|infirmary|ambulance|nhs|doctor|clinic|medical|gp|pharmacy)\b",
        "crime": r"\b(?:police|court|prison|jail|crime|arrest|charged|grooming|stabbing|knife)\b",
        "education": r"\b(?:school|academy|college|university|pupil|teacher)\b",
        "traffic": r"\b(?:roadworks?|road closure|traffic|motorway|collision|crash)\b",
        "sport": r"\b(?:football|rugby|cricket|hornets|rochdale afc|fixture|match)\b",
    }
    for family, tokens in VISUAL_FAMILIES.items():
        present = [token for token in tokens if token in blob]
        if not present or family == category:
            continue
        if hit(title_support[family], title):
            continue
        return True, f"{family} visual ({', '.join(present[:3])}) does not match {category} story"
    return False, ""


def image_issue(article: dict[str, Any]) -> str:
    image_url = clean(article.get("image_url"))
    img = clean(article.get("img"))
    status = clean(article.get("image_status")).lower()

    if not image_url and img:
        return "uncanonical img fallback exists while image_url is empty"
    if not image_url and not img:
        return "story has no image"
    if generated_image(article):
        return ""

    mismatch, reason = visual_family_mismatch(article)
    if mismatch:
        return reason

    if article.get("sensitive_story") is True:
        manual_editorial = (
            article.get("manual_article") is True
            and "editorial" in clean(article.get("source_kind")).lower()
        )
        explicit_source_image = bool(
            clean(article.get("image_url"))
            and clean(article.get("source_image_candidate_url"))
        )
        commons = "commons-photo" in clean(article.get("image_status")).lower()
        if not (manual_editorial or explicit_source_image or commons):
            return "sensitive story image lacks explicit source/editorial provenance"

    if "cards-library-photo" in status:
        try:
            score = int(article.get("image_match_score") or 0)
        except (TypeError, ValueError):
            score = 0
        if score and score < 11000:
            return f"weak filename image match score {score}; neutral card is safer"

    if any(token in status for token in UNSAFE_GENERIC_IMG_ONLY_STATUSES) and not source_evidence(article):
        return "cached/library image lacks canonical/source provenance"

    return ""


def enforce_image(article: dict[str, Any], changes: list[dict[str, Any]]) -> None:
    if clean(article.get("status")).lower() not in {"", "published"}:
        return
    reason = image_issue(article)
    if not reason:
        if clean(article.get("image_url")) and clean(article.get("img")) != clean(article.get("image_url")):
            article["img"] = clean(article.get("image_url"))
        return

    before = {
        "image_url": clean(article.get("image_url")),
        "img": clean(article.get("img")),
        "status": clean(article.get("image_status")),
    }
    set_generated(article, ROOT)
    article["image_placeholder_reason"] = "Editorial integrity fallback: " + reason
    changes.append({
        "slug": clean(article.get("slug")),
        "title": clean(article.get("title")),
        "category": clean(article.get("category")),
        "reason": reason,
        "before": before,
        "after": clean(article.get("image_url")),
    })


def load_articles(path: Path) -> tuple[Any, list[dict[str, Any]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data, data
    if isinstance(data, dict) and isinstance(data.get("articles"), list):
        return data, data["articles"]
    raise ValueError(f"{path} is not an article list/object")


def dump_articles(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def audit(path: Path, mode: str) -> int:
    data, articles = load_articles(path)
    category_changes: list[dict[str, Any]] = []
    image_changes: list[dict[str, Any]] = []

    for article in articles:
        if isinstance(article, dict):
            apply_category(article, category_changes)

    if mode in {"final", "check"}:
        for article in articles:
            if isinstance(article, dict):
                enforce_image(article, image_changes)

    report = {
        "policy": (
            "Headline/topic-first classification; canonical/source-backed images only; "
            "neutral Rochdale Daily card whenever a photo could create a false implication."
        ),
        "mode": mode,
        "article_count": len(articles),
        "published_count": sum(
            1 for a in articles if isinstance(a, dict) and clean(a.get("status")).lower() in {"", "published"}
        ),
        "category_change_count": len(category_changes),
        "image_change_count": len(image_changes),
        "category_changes": category_changes,
        "image_changes": image_changes,
    }

    if mode == "check":
        if category_changes or image_changes:
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1
        print(f"story integrity check passed for {len(articles)} articles")
        return 0

    dump_articles(path, data)
    report_path = ROOT / "reports" / "story_editorial_integrity_audit.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"Audited {len(articles)} stories: "
        f"{len(category_changes)} category corrections, {len(image_changes)} image corrections."
    )
    for item in category_changes[:20]:
        print(f"CATEGORY {item['from']} -> {item['to']}: {item['title']}")
    for item in image_changes[:20]:
        print(f"IMAGE -> generated: {item['title']} ({item['reason']})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--articles", default="articles.json")
    parser.add_argument("--mode", choices=("classify", "final", "check"), default="final")
    args = parser.parse_args()
    return audit((ROOT / args.articles).resolve(), args.mode)


if __name__ == "__main__":
    raise SystemExit(main())
