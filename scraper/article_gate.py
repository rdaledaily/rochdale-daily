"""Article gate: the single normalisation and validation chokepoint.

Every route that produces articles.json — the scraper, the manual
GitHub-editor workflow, merge_feeds conflict resolution — converges here
before pages are built. The gate makes invalid records impossible to
ship instead of relying on each route (or the editor) to get every
field right.

What it enforces:

* Timestamps. `published_at`/`scraped_at` must be full ISO datetimes.
  A missing, unparseable, or date-only (midnight) stamp on a MANUAL
  record is replaced with the moment the record first passed the gate.
  First-sight time is anchored in `ingested_at`, so the fix is
  idempotent: re-running the gate never re-stamps an article.
  Scraper-produced records (`publication_route` set) are never
  re-stamped — their timestamps are the pipeline's responsibility.

* Areas. `area` must be a known borough slug. Aliases are coerced
  (e.g. `rochdale-borough` -> `rochdale`), unknowns fall back to
  `rochdale` with a logged note, so the frontend never renders a raw
  slug like "ROCHDALE-BOROUGH" and area filtering always matches.

* Categories. Must be one of the canonical set; aliases coerced,
  unknowns fall back to `news`. (The gate cannot know a crime-labelled
  story is really an environment story — semantic checks stay in the
  scraper's classifiers — but it guarantees the label is at least a
  real category.)

* Required fields. `slug` derived from the title when missing;
  `status` and `byline` defaulted.

* Hard facts. A record asserting anyone other than the verified
  incumbent as "Rochdale MP" is DROPPED, whatever route it arrived by.
  (Shares the fact table with claim_guard when present.)

Run: python scraper/article_gate.py articles.json
Prints a report of every change; rewrites the file only when needed.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:  # Shared fact table with the rewrite-path guard when it's installed.
    from claim_guard import CONSTITUENCY_MP_FACTS
except ImportError:
    CONSTITUENCY_MP_FACTS = {
        "rochdale": "paul waugh",  # verified 2026-07-11, members.parliament.uk
    }

CANONICAL_CATEGORIES = {
    "business", "community", "crime", "education", "environment", "events",
    "health", "news", "politics", "sport", "traffic", "transport",
}
CATEGORY_ALIASES = {
    "environmental": "environment",
    "sports": "sport",
    "event": "events",
    "whats-on": "events",
    "transportation": "transport",
    "travel": "traffic",
    "local-news": "news",
}

CANONICAL_AREAS = {
    # Townships and towns
    "rochdale", "heywood", "middleton", "milnrow", "newhey", "littleborough",
    "wardle", "smallbridge", "smithy-bridge", "whitworth",
    # Rochdale neighbourhoods
    "castleton", "spotland", "falinge", "deeplish", "balderstone", "firgrove",
    "kirkholt", "norden", "bamford", "shawclough", "healey", "syke",
    "wardleworth", "sudden", "lowerplace", "meanwood", "cutgate",
    # Heywood / Middleton neighbourhoods
    "darnhill", "hopwood", "alkrington", "boarshaw",
}
AREA_ALIASES = {
    "rochdale-borough": "rochdale",
    "rochdale borough": "rochdale",
    "borough": "rochdale",
    "rochdale-town-centre": "rochdale",
    "smithy bridge": "smithy-bridge",
    "cutgate-and-caldershaw": "cutgate",
}
AREA_FALLBACK = "rochdale"

MIDNIGHT = "T00:00:00"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value: str) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "untitled").lower()).strip("-")
    return slug[:80] or "untitled"


def _is_manual(article: dict) -> bool:
    return not article.get("publication_route")


def _fact_table_violation(article: dict) -> str | None:
    text = " ".join(
        str(article.get(field, "")) for field in ("title", "excerpt", "summary", "content_html")
    ).lower()
    for place, incumbent in CONSTITUENCY_MP_FACTS.items():
        for match in re.finditer(
            rf"(?:{re.escape(place)}\s+mp\s+|mp\s+for\s+{re.escape(place)}[,\s]+(?:the\s+)?)"
            rf"([a-z][a-z'\-]+(?:\s+[a-z][a-z'\-]+){{1,2}})",
            text,
        ):
            name = match.group(1).strip()
            if incumbent not in name and name not in incumbent:
                return (
                    f"asserts '{place} MP {name.title()}' but the verified "
                    f"MP for {place.title()} is {incumbent.title()}"
                )
    return None


def normalise_article(article: dict, notes: list[str]) -> dict | None:
    """Return the corrected article, or None if it must be dropped."""
    title = str(article.get("title") or "").strip()
    ident = article.get("slug") or title or article.get("id") or "?"

    violation = _fact_table_violation(article)
    if violation:
        notes.append(f"DROPPED '{ident}': {violation}")
        return None

    if not article.get("slug"):
        article["slug"] = _slugify(title)
        notes.append(f"'{ident}': derived slug '{article['slug']}'")

    article.setdefault("status", "published")
    article.setdefault("byline", "Rochdale Daily Newsdesk")

    # --- timestamps -------------------------------------------------
    first_sight = "ingested_at" not in article
    if first_sight:
        article["ingested_at"] = _now_iso()

    for field in ("published_at", "scraped_at"):
        raw = str(article.get(field) or "")
        parsed = _parse_iso(raw)
        if parsed is None:
            article[field] = article["ingested_at"]
            notes.append(f"'{ident}': {field} was invalid/missing; set to {article[field]}")
        elif first_sight and _is_manual(article) and MIDNIGHT in raw:
            today = article["ingested_at"][:10]
            if raw[:10] == today:
                article[field] = article["ingested_at"]
            else:
                # An older date-only stamp keeps its day (midday, so it
                # sorts plausibly) rather than faking freshness at 'now'.
                article[field] = f"{raw[:10]}T12:00:00Z"
            notes.append(
                f"'{ident}': {field} was a date-only midnight stamp; set to {article[field]}"
            )

    # --- area -------------------------------------------------------
    area = str(article.get("area") or "").strip().lower()
    if area in AREA_ALIASES:
        article["area"] = AREA_ALIASES[area]
        notes.append(f"'{ident}': area '{area}' -> '{article['area']}'")
    elif area not in CANONICAL_AREAS:
        article["area"] = AREA_FALLBACK
        notes.append(f"'{ident}': unknown area '{area}' -> '{AREA_FALLBACK}'")

    # --- category ---------------------------------------------------
    category = str(article.get("category") or "").strip().lower()
    if category in CATEGORY_ALIASES:
        article["category"] = CATEGORY_ALIASES[category]
        notes.append(f"'{ident}': category '{category}' -> '{article['category']}'")
    elif category not in CANONICAL_CATEGORIES:
        article["category"] = "news"
        notes.append(f"'{ident}': unknown category '{category}' -> 'news'")

    # crime implies police_matter bookkeeping stays consistent
    if article.get("category") == "crime" and "police_matter" not in article:
        article["police_matter"] = True
        notes.append(f"'{ident}': set police_matter for crime category")

    return article


def gate_articles(articles: list[dict]) -> tuple[list[dict], list[str]]:
    notes: list[str] = []
    kept: list[dict] = []
    for article in articles:
        result = normalise_article(article, notes)
        if result is not None:
            kept.append(result)
    return kept, notes


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "articles.json")
    original_text = path.read_text(encoding="utf-8")
    articles = json.loads(original_text)
    if not isinstance(articles, list):
        print(f"article_gate: {path} is not a list of articles", file=sys.stderr)
        return 1

    kept, notes = gate_articles(articles)

    for note in notes:
        print(f"article_gate: {note}")
    dropped = len(articles) - len(kept)
    print(
        f"article_gate: {len(kept)} article(s) kept, {dropped} dropped, "
        f"{len(notes)} correction(s)"
    )

    new_text = json.dumps(kept, ensure_ascii=False, indent=2) + "\n"
    if new_text != original_text:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(new_text, encoding="utf-8")
        tmp.replace(path)
        print(f"article_gate: rewrote {path}")
    else:
        print("article_gate: no changes needed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
