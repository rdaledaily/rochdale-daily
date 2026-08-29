#!/usr/bin/env python3
"""Whole-archive editorial integrity audit for Rochdale Daily.

The failure mode this protects against is editorially serious: a loose keyword
matcher can turn a youth-council resignation into Health, a Court Chamber tour
into Crime, or a community breakfast club into Sport. This pass therefore uses
human-reviewed overrides for known ambiguous stories and only changes future
stories when the headline itself gives high-confidence evidence.

Image policy is deliberately conservative. A neutral Rochdale Daily headline
card is preferable to a photograph that could falsely imply a hospital visit,
police involvement, a school, a court case, a named person or another factual
connection the story does not establish.

Run modes:
  classify  -- category/type corrections only
  final     -- category corrections plus image safety enforcement and report
  check     -- do not write; fail if a high-confidence issue remains
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from ensure_article_images import set_generated

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_CATEGORIES = {
    "business", "community", "crime", "education", "environment", "events", "health",
    "news", "politics", "sport", "traffic", "transport",
}

# These records were reviewed individually after the first full-archive pass.
# Explicit decisions beat generic keyword rules for ambiguous headlines.
CATEGORY_OVERRIDES: dict[str, str] = {
    "rochdale-valiant-launches-new-media-portal-for-local-news": "news",
    "restoration-of-historic-packer-spout-steps-completed-in-rochdale-town-centre": "news",
    "rochdale-boroughwide-housing-appoints-paul-roberts-as-permanent-chair": "business",
    "daniel-murphy-resigns-as-leader-of-rochdale-youth-council": "community",
    "wellmental-uk-hosts-first-mens-mental-health-fitness-session-in-heywood": "health",
    "norden-cricket-club-festival-brings-community-together-today": "sport",
    "missing-rayah-rochdale-bower-avenue": "news",
    "st-marys-ce-primary-school-rochdale-summer-makeover-watergrove": "education",
    "videos-raise-hygiene-concerns-rajdhani-halal-meats-halifax-road": "business",
    "rochdale-town-hall-historic-court-chamber-guided-tours": "events",
    "heywood-marlborough-canal-street-alley-dumping-vermin": "environment",
    "daniel-meredith-rochdale-hornets-superhero-day-council-partnership": "sport",
    "summit-inn-reopens-new-menu-pub-classics": "business",
    "steven-parker-rochdale-canal-basin-regeneration-vision": "environment",
    "police-increased-patrols-strand-kirkholt-verbal-abuse-begging": "crime",
    "side-by-side-feed-our-minds-souls-rochdale-15-august-2026": "events",
    "norden-residents-no-water-since-friday-united-utilities": "news",
    "feel-good-festival-45-ticket-price-complaints-why-organisers-charge": "news",
    "rochdale-afc-five-vacancies-first-team-academy-womens-2026": "sport",
    "rainbow-health-group-open-day-new-clinic-august-2026": "health",
    "loombrook-meadows-302-new-homes-castleton-barratt": "business",
    "stronger-together-whitworth-lord-lieutenant-visit-packed-cafe": "community",
    "should-gatekeepers-decide-which-local-news-you-get-to-see": "news",
    "rochdale-veterans-breakfast-club-heywood-flying-horse": "community",
    "low-flying-helicopter-heard-across-rochdale-august-2026": "news",
    "81-year-old-man-left-outside-rochdale-infirmary-ten-hours": "health",
    "heat-exposes-challenges-facing-rochdale-workers-and-britains-infrastructure": "environment",
    "litter-concerns-deeplish-rochdale": "environment",
    "anti-social-behaviour-kingsway-rochdale": "community",
    "littleborough-taxi-driver-safety-warning-railway-station": "news",
    "dangerous-driving-milkstone-road-rochdale": "traffic",
    "mayor-praises-merhaba-festival-2026": "events",
    "strand-community-cafe-record-busiest-month-kirkholt": "community",
    "white-ribbon-football-tournament-returns-to-rochdale-for-2026": "sport",
    "police-presence-reported-at-ashworth-reservoir-norden": "news",
    "greenvale-planning-committee-bamford": "news",
    "middleton-protest-organiser-outlines-plans": "news",
    "syke-bowling-club-junior-fun-day": "sport",
}


def clean(value: Any) -> str:
    return str(value or "").strip()


def words(value: Any) -> str:
    return re.sub(r"\s+", " ", clean(value)).strip()


def text(article: dict[str, Any], *fields: str) -> str:
    return " ".join(words(article.get(field)) for field in fields if article.get(field))


def hit(pattern: str, value: str) -> bool:
    return bool(re.search(pattern, value, re.I | re.S))


def headline_category(article: dict[str, Any]) -> str | None:
    slug = clean(article.get("slug")).lower()
    if slug in CATEGORY_OVERRIDES:
        return CATEGORY_OVERRIDES[slug]

    title = text(article, "title")
    if not title:
        return None

    # Safety exceptions: these phrases must not be interpreted literally as a
    # section signal. A missing-person appeal does not establish a crime; a
    # Court Chamber tour is not a court case; police presence alone establishes
    # no offence; protests/planning meetings are general news unless the actual
    # headline establishes a more specific political/criminal event.
    if hit(r"\b(?:missing|police appeal to find|police presence reported|guided court chamber tour|court chamber tours?)\b", title):
        return "events" if hit(r"\b(?:guided|tour)\b", title) else "news"
    if hit(r"\b(?:protest planned|planning meeting|planning decision)\b", title):
        return "news"

    # Explicit criminal-justice facts are allowed to drive Crime. Generic
    # words such as police, court, appeal or investigation are intentionally
    # absent because they do not by themselves establish criminality.
    if hit(
        r"\b(?:murder|manslaughter|rape|rapist|grooming gang|sexual (?:assault|offence|abuse)|"
        r"stabbing|shooting|robbery|burglary|theft|fraud|arrested?|charged|convicted|sentenced|"
        r"jailed|prison|magistrates'? court|crown court|wanted (?:man|woman|person)|drug raid|"
        r"cannabis farm|parole|kidnap|assaulted?)\b",
        title,
    ):
        return "crime"

    # Sport precedes Education/Politics so "Rochdale AFC academy" and
    # "Councillor backs Hornets" stay sports stories rather than being hijacked
    # by the incidental word academy/councillor.
    if hit(
        r"\b(?:rochdale afc|rochdale hornets|football|rugby|cricket|boxing|netball|athletics|"
        r"parkrun|MMA|muay thai|fixture|match|league two|cup tie|goalkeeper|striker|defender|"
        r"midfielder|forward|bowling club|tennis|badminton|basketball)\b",
        title,
    ):
        return "sport"

    # Health precedes Events so a clinic open day remains a health-service
    # story. A generic wellbeing/fitness event is not enough unless mental
    # health/clinical/service wording is explicit.
    if hit(
        r"\b(?:NHS|hospital|infirmary|doctor|GP\b|general practice|clinic|patient|pharmacy|"
        r"vaccination|health service|mental health (?:service|support|session|team|clinic|fitness)|"
        r"wellbeing service)\b",
        title,
    ):
        return "health"

    if hit(
        r"\b(?:school|college|university|ofsted|teacher|headteacher|pupil|student|GCSE|A[- ]level|"
        r"education results?|exam results?)\b",
        title,
    ):
        return "education"

    if hit(
        r"\b(?:roadworks?|road works?|road closure|road closed|lane closure|traffic|collision|crash|"
        r"congestion|diversion|potholes?|speeding|dangerous driving|street racing|M62|A627(?:\(M\))?)\b",
        title,
    ):
        return "traffic"

    if hit(
        r"\b(?:train|railway service|rail service|tram|metrolink|bee network|bus service|buses|"
        r"bus route|timetable|public transport|northern rail|service disruption)\b",
        title,
    ):
        return "transport"

    if hit(
        r"\b(?:flood|flooding|weather warning|weather forecast|heatwave|met office|recycling|litter|"
        r"fly.?tipping|waste|landfill|wildlife|biodiversity|nature reserve|woodland|tree planting|"
        r"tree felling|pollution|air quality|sewage|climate|net zero|moor fire|green belt|canal)\b",
        title,
    ):
        return "environment"

    if hit(
        r"\b(?:festival|concert|gig|exhibition|performance|parade|fair|bingo|open day|community event|"
        r"live music|show at|tour at|fun day)\b",
        title,
    ):
        return "events"

    if hit(r"\b(?:restoration of historic|historic .{0,45} restored|heritage restoration|listed building restoration|historic steps)\b", title):
        return "news"

    if hit(
        r"\b(?:local election|general election|by[- ]election|council leader|council cabinet|council budget|"
        r"council tax|member of parliament|\bMP\b|parliament|minister|manifesto|political party|"
        r"labour party|conservative party|reform uk|liberal democrats?|workers party|mayoral election)\b",
        title,
    ):
        return "politics"

    if hit(
        r"\b(?:youth council|youth cabinet|youth parliament|charity|fundraiser|fundraising|food ?bank|"
        r"volunteer|community group|community centre|community cafe|community café|support group|"
        r"homelessness|rough sleeper|residents'? group|community project|community award|local hero|"
        r"veterans? breakfast club|anti-social behaviour)\b",
        title,
    ):
        return "community"

    if hit(
        r"\b(?:business|company|shop|store|restaurant|pub|takeaway|retail|commercial|investment|"
        r"housing development|new homes|apartments?|appoints? .{0,40} (?:chair|chief executive|CEO|director)|reopens? with new menu)\b",
        title,
    ):
        return "business"

    # No low-confidence body/standfirst vote. Preserve the editor/pipeline's
    # existing category when the headline does not establish a section.
    return None


def category_reason(article: dict[str, Any], new_category: str) -> str:
    slug = clean(article.get("slug")).lower()
    if slug in CATEGORY_OVERRIDES:
        return "human-reviewed archive classification override"
    return f"headline strongly identifies {new_category}"


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
    headline = text(article, "title", "excerpt").lower()
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
        if hit(title_support[family], headline):
            continue
        return True, f"{family} visual ({', '.join(present[:3])}) does not match {category} story"
    return False, ""


def image_issue(article: dict[str, Any]) -> str:
    image_url = clean(article.get("image_url"))
    img = clean(article.get("img"))
    status = clean(article.get("image_status")).lower()

    # Never let a hidden secondary field supply a photo that the canonical
    # image field explicitly declined. This is the exact Daniel Murphy failure.
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
        explicit_source_image = bool(image_url and clean(article.get("source_image_candidate_url")))
        commons = "commons-photo" in status
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
            "Human-reviewed ambiguous-story overrides; headline-only high-confidence classification; "
            "canonical/source-backed images only; neutral Rochdale Daily card whenever a photo could create a false implication."
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
    for item in category_changes[:40]:
        print(f"CATEGORY {item['from']} -> {item['to']}: {item['title']}")
    for item in image_changes[:40]:
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
