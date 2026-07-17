
"""Article gate: the single normalisation and validation chokepoint.

Every route that produces articles.json should pass through this gate before
pages are built. The gate normalises records, protects stable publication
metadata, enforces explicit takedowns, and rejects records that are unsafe or
too incomplete to publish.

Key rules:

* Permanent publication date:
  - first_published_at is the earliest legitimate publication timestamp.
  - published_at is kept aligned to that stable original publication time.
  - last_updated_at records later changes without making a story look new.
  - scraped_at records the latest collection time.
  - ingested_at records when the article first entered this archive.

* Areas:
  - canonical Rochdale coverage slugs are enforced.
  - aliases are normalised.
  - Whitworth remains explicitly included in editorial coverage.

* Categories:
  - aliases are normalised to the canonical category set.
  - unknown values fall back to news.

* Required content:
  - records need a meaningful title and article body/summary.
  - slug, status and byline are normalised.

* Hard facts:
  - clearly current claims naming the wrong Rochdale MP are rejected.
  - historical/former-MP references are not treated as current claims.

* Takedowns:
  - records matching story_blocklist.py are dropped at this final chokepoint.

Run:
    python scraper/article_gate.py articles.json
"""
from __future__ import annotations

import copy
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from claim_guard import CONSTITUENCY_MP_FACTS
except ImportError:
    CONSTITUENCY_MP_FACTS = {
        "rochdale": "paul waugh",
    }

try:
    from story_blocklist import is_blocked_article, load_blocklist
except ImportError:
    def load_blocklist() -> Any:
        return []

    def is_blocked_article(article: dict[str, Any], blocklist: Any) -> bool:
        return False


CANONICAL_CATEGORIES = {
    "business",
    "community",
    "crime",
    "education",
    "environment",
    "events",
    "health",
    "news",
    "politics",
    "sport",
    "traffic",
    "transport",
}

CATEGORY_ALIASES = {
    "environmental": "environment",
    "sports": "sport",
    "event": "events",
    "whats-on": "events",
    "what's-on": "events",
    "transportation": "transport",
    "travel": "traffic",
    "local-news": "news",
}

CANONICAL_AREAS = {
    # Rochdale Borough towns and neighbourhoods.
    "rochdale",
    "heywood",
    "middleton",
    "milnrow",
    "newhey",
    "littleborough",
    "wardle",
    "smallbridge",
    "smithy-bridge",
    # Explicitly included neighbouring community in editorial coverage.
    "whitworth",
    # Rochdale neighbourhoods.
    "castleton",
    "spotland",
    "falinge",
    "deeplish",
    "balderstone",
    "firgrove",
    "kirkholt",
    "norden",
    "bamford",
    "shawclough",
    "healey",
    "syke",
    "wardleworth",
    "sudden",
    "lowerplace",
    "meanwood",
    "cutgate",
    # Heywood / Middleton neighbourhoods.
    "darnhill",
    "hopwood",
    "alkrington",
    "boarshaw",
}

AREA_ALIASES = {
    "rochdale-borough": "rochdale",
    "rochdale borough": "rochdale",
    "borough": "rochdale",
    "rochdale-town-centre": "rochdale",
    "rochdale town centre": "rochdale",
    "smithy bridge": "smithy-bridge",
    "cutgate-and-caldershaw": "cutgate",
    "little borough": "littleborough",
}

AREA_FALLBACK = "rochdale"
DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:T00:00:00(?:Z|[+-]00:00)?)?$")
HTML_TAG_RE = re.compile(r"<[^>]+>")
CURRENT_MP_RE_TEMPLATE = (
    r"(?<!former\s)(?<!ex-)(?<!previous\s)"
    r"(?:{place}\s+mp\s+|mp\s+for\s+{place}[,\s]+(?:the\s+)?)"
    r"([a-z][a-z'\-]+(?:\s+[a-z][a-z'\-]+){{1,2}})"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _earliest_iso(*values: object) -> str | None:
    parsed = [dt for value in values if (dt := _parse_iso(value)) is not None]
    return _format_iso(min(parsed)) if parsed else None


def _latest_iso(*values: object) -> str | None:
    parsed = [dt for value in values if (dt := _parse_iso(value)) is not None]
    return _format_iso(max(parsed)) if parsed else None


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    return slug[:80]


def _is_manual(article: dict[str, Any]) -> bool:
    return not bool(article.get("publication_route"))


def _normalise_manual_timestamp(raw: object, ingested_at: str) -> str:
    text = str(raw or "").strip()
    parsed = _parse_iso(text)
    if parsed is None:
        return ingested_at

    if DATE_ONLY_RE.match(text):
        day = parsed.strftime("%Y-%m-%d")
        if day == ingested_at[:10]:
            return ingested_at
        return f"{day}T12:00:00Z"

    return _format_iso(parsed)


def _meaningful_text(article: dict[str, Any]) -> str:
    body = HTML_TAG_RE.sub(" ", str(article.get("content_html") or ""))
    values = [
        str(article.get("excerpt") or ""),
        str(article.get("summary") or ""),
        body,
    ]
    return re.sub(r"\s+", " ", " ".join(values)).strip()


def _fact_table_violation(article: dict[str, Any]) -> str | None:
    text = " ".join(
        str(article.get(field, ""))
        for field in ("title", "excerpt", "summary", "content_html")
    ).lower()

    for place, incumbent in CONSTITUENCY_MP_FACTS.items():
        pattern = CURRENT_MP_RE_TEMPLATE.format(place=re.escape(place))
        for match in re.finditer(pattern, text):
            name = match.group(1).strip()
            if incumbent not in name and name not in incumbent:
                return (
                    f"asserts '{place.title()} MP {name.title()}' but the verified "
                    f"current MP for {place.title()} is {incumbent.title()}"
                )
    return None


def _normalise_timestamps(
    article: dict[str, Any],
    ident: str,
    notes: list[str],
) -> None:
    now = _now_iso()

    ingested = _parse_iso(article.get("ingested_at"))
    if ingested is None:
        article["ingested_at"] = now
        notes.append(f"'{ident}': set missing/invalid ingested_at")
    else:
        article["ingested_at"] = _format_iso(ingested)

    is_manual = _is_manual(article)

    if is_manual:
        candidates = {
            "first_published_at": _normalise_manual_timestamp(
                article.get("first_published_at"), article["ingested_at"]
            ),
            "published_at": _normalise_manual_timestamp(
                article.get("published_at"), article["ingested_at"]
            ),
            "scraped_at": _normalise_manual_timestamp(
                article.get("scraped_at"), article["ingested_at"]
            ),
        }
    else:
        candidates = {}
        for field in ("first_published_at", "published_at", "scraped_at"):
            parsed = _parse_iso(article.get(field))
            if parsed is not None:
                candidates[field] = _format_iso(parsed)

    stable_publication = _earliest_iso(
        candidates.get("first_published_at"),
        candidates.get("published_at"),
        article.get("first_published_at"),
        article.get("published_at"),
        article["ingested_at"] if is_manual else None,
    )
    if is_manual:
        # Manual date-only or midnight timestamps have already been normalised
        # above. Do not compare them with the original raw midnight values,
        # otherwise the earlier 00:00 value wins and undoes the noon fix.
        stable_publication = _earliest_iso(
            candidates.get("first_published_at"),
            candidates.get("published_at"),
            article["ingested_at"],
        )
    else:
        stable_publication = _earliest_iso(
            candidates.get("first_published_at"),
            candidates.get("published_at"),
            article.get("first_published_at"),
            article.get("published_at"),
        )

    if stable_publication is None:
        # Scraper records should normally supply a publication timestamp.
