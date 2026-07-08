"""Story clustering and de-duplication for Rochdale Daily.

No third-party dependencies are used, so this module can be regression-tested
before the main scraper imports Feedparser, Playwright, OpenAI or BeautifulSoup.
"""

from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse, urlunparse

TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
WORD_RE = re.compile(r"[a-z0-9]+")
ENTITY_RE = re.compile(
    r"\b(?:[A-Z][a-z][A-Za-z'-]*|[A-Z]{2,})"
    r"(?:\s+(?:[A-Z][a-z][A-Za-z'-]*|[A-Z]{2,})){1,3}\b"
)

STOPWORDS = {
    "about", "after", "again", "against", "ahead", "also", "among",
    "another", "around", "because", "before", "being", "between",
    "could", "first", "from", "have", "into", "latest", "local",
    "more", "news", "new", "over", "said", "says", "that", "their",
    "there", "these", "they", "this", "through", "today", "under",
    "update", "what", "when", "where", "which", "with", "would",
    "rochdale", "heywood", "middleton", "littleborough", "milnrow",
    "newhey", "wardle", "norden", "castleton", "kirkholt", "spotland",
    "falinge", "deeplish", "greater", "manchester",
}

GENERIC_ENTITIES = {
    "greater manchester",
    "greater manchester police",
    "rochdale daily",
    "rochdale council",
    "rochdale borough council",
    "rochdale afc",
    "rochdale hornets",
    "bee network",
    "national highways",
    "northern care alliance",
    "pennine care",
    "united kingdom",
    "crown oil arena",
    "facebook events",
}

AUTHORITATIVE_ACTION_WORDS = {
    "announces", "announced", "confirms", "confirmed", "signs", "signed",
    "launches", "launched", "opens", "opened", "closes", "closed",
    "issues", "issued", "arrests", "arrested", "charges", "charged",
    "wins", "won", "appoints", "appointed",
}

FOLLOWUP_WORDS = {
    "interview", "reaction", "discusses", "speaks", "explains", "responds",
    "preview", "gallery", "pictures", "video", "watch", "hear from",
}

CATEGORY_FAMILIES = {
    "traffic": "transport",
    "transport": "transport",
    "crime": "crime",
    "politics": "public-affairs",
    "community": "community",
    "charity": "community",
    "health": "health",
    "education": "education",
    "sport": "sport",
    "events": "events",
    "business": "business",
    "environment": "environment",
    "news": "news",
}


def get_value(item: Any, name: str, default: Any = "") -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def normalise_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = TAG_RE.sub(" ", text)
    return SPACE_RE.sub(" ", text).strip()


def canonicalise_url(url: str) -> str:
    parsed = urlparse(str(url or ""))
    query_parts = []
    for part in parsed.query.split("&"):
        lower = part.lower()
        if part and not lower.startswith(
            ("utm_", "fbclid=", "gclid=", "at_medium=", "at_campaign=")
        ):
            query_parts.append(part)
    return urlunparse((
        parsed.scheme or "https",
        parsed.netloc.lower(),
        parsed.path.rstrip("/"),
        "",
        "&".join(query_parts),
        "",
    ))


def combined_text(item: Any) -> str:
    return normalise_text(" ".join(
        str(get_value(item, field, "") or "")
        for field in (
            "source_title", "title", "source_summary", "summary", "excerpt",
            "source_body_excerpt", "content_html", "event_location",
        )
    ))


def date_key(item: Any) -> str:
    raw = (
        get_value(item, "event_start_at", "")
        or get_value(item, "published_at", "")
        or get_value(item, "source_published_at", "")
    )
    try:
        value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).date().isoformat()
    except (TypeError, ValueError):
        return ""


def category_family(item: Any) -> str:
    category = str(
        get_value(item, "category", "")
        or (
            (get_value(item, "types", []) or ["news"])[0]
            if isinstance(get_value(item, "types", []), list)
            else "news"
        )
        or "news"
    ).lower()
    return CATEGORY_FAMILIES.get(category, category)


def area_key(item: Any) -> str:
    return str(get_value(item, "area", "") or "rochdale").lower()


def content_tokens(item: Any) -> set[str]:
    return {
        token for token in WORD_RE.findall(combined_text(item).lower())
        if len(token) >= 4 and token not in STOPWORDS
    }


def title_tokens(item: Any) -> set[str]:
    title = normalise_text(
        get_value(item, "source_title", "") or get_value(item, "title", "")
    )
    return {
        token for token in WORD_RE.findall(title.lower())
        if len(token) >= 3 and token not in STOPWORDS
    }


def named_entities(item: Any) -> set[str]:
    entities: set[str] = set()
    for match in ENTITY_RE.findall(combined_text(item)):
        entity = normalise_text(match).lower()
        if entity in GENERIC_ENTITIES:
            continue
        if any(generic == entity for generic in GENERIC_ENTITIES):
            continue
        words = entity.split()
        if len(words) < 2:
            continue
        # Reject phrases made solely from locality/generic tokens.
        if all(word in STOPWORDS for word in words):
            continue
        entities.add(entity)
    return entities


def primary_entity(item: Any) -> str:
    entities = named_entities(item)
    if not entities:
        return ""

    text = combined_text(item).lower()
    ranked = sorted(
        entities,
        key=lambda entity: (
            text.count(entity),
            len(entity.split()),
            len(entity),
            entity,
        ),
        reverse=True,
    )
    return ranked[0]


def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def hours_apart(left: Any, right: Any) -> float:
    def parsed(item: Any) -> datetime | None:
        raw = (
            get_value(item, "event_start_at", "")
            or get_value(item, "published_at", "")
            or get_value(item, "source_published_at", "")
        )
        try:
            value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        except (TypeError, ValueError):
            return None

    first, second = parsed(left), parsed(right)
    if first is None or second is None:
        return 0.0
    return abs((first - second).total_seconds()) / 3600


def story_similarity(left: Any, right: Any) -> float:
    left_url = canonicalise_url(
        get_value(left, "source_url", "") or get_value(left, "url", "")
    )
    right_url = canonicalise_url(
        get_value(right, "source_url", "") or get_value(right, "url", "")
    )
    if left_url and left_url == right_url:
        return 1.0

    left_family = category_family(left)
    right_family = category_family(right)
    compatible = (
        left_family == right_family
        or "news" in {left_family, right_family}
    )
    if not compatible:
        return 0.0

    if hours_apart(left, right) > 48:
        return 0.0

    score = 0.0

    left_entities = named_entities(left)
    right_entities = named_entities(right)
    shared_entities = left_entities & right_entities
    if shared_entities:
        score += 0.68

    title_score = jaccard(title_tokens(left), title_tokens(right))
    score += title_score * 0.45

    shared_content = content_tokens(left) & content_tokens(right)
    if len(shared_content) >= 5:
        score += 0.25
    elif len(shared_content) >= 3:
        score += 0.16
    elif len(shared_content) >= 2:
        score += 0.08

    if area_key(left) == area_key(right):
        score += 0.05

    left_source = str(get_value(left, "source_name", "")).lower()
    right_source = str(get_value(right, "source_name", "")).lower()
    if left_source and left_source == right_source:
        score += 0.08

    left_event = str(get_value(left, "event_start_at", "") or "")
    right_event = str(get_value(right, "event_start_at", "") or "")
    if left_event and right_event and date_key(left) == date_key(right):
        score += 0.45

    return min(score, 1.0)


def same_story(left: Any, right: Any) -> bool:
    return story_similarity(left, right) >= 0.72


def authority_score(item: Any) -> float:
    title = normalise_text(
        get_value(item, "source_title", "") or get_value(item, "title", "")
    ).lower()
    body_length = len(combined_text(item))
    score = min(body_length / 3000, 1.0)

    if any(word in title for word in AUTHORITATIVE_ACTION_WORDS):
        score += 0.7
    if any(word in title for word in FOLLOWUP_WORDS):
        score -= 0.35

    source = str(get_value(item, "source_name", "")).lower()
    if any(marker in source for marker in (
        "council", "police", "gmp", "fire", "nhs", "tfgm",
        "rochdale afc", "rochdale hornets", "environment agency",
    )):
        score += 0.35

    return score


def build_story_key(item: Any) -> str:
    existing = str(get_value(item, "story_key", "") or "").strip()
    if existing:
        return existing

    family = category_family(item)
    area = area_key(item)
    day = date_key(item)
    entity = primary_entity(item)

    if entity:
        subject = entity
    else:
        tokens = sorted(content_tokens(item))[:6]
        subject = "-".join(tokens) or canonicalise_url(
            get_value(item, "source_url", "")
        )

    raw = f"{family}|{area}|{day}|{subject}".lower()
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    return f"{family}-{digest}"


def source_pairs(item: Any) -> list[tuple[str, str]]:
    names = get_value(item, "source_names", []) or []
    urls = get_value(item, "source_urls", []) or []
    pairs: list[tuple[str, str]] = []

    primary_name = str(get_value(item, "source_name", "") or "")
    primary_url = str(get_value(item, "source_url", "") or "")
    if primary_url:
        pairs.append((primary_name, primary_url))

    if isinstance(urls, list):
        for index, url in enumerate(urls):
            if not url:
                continue
            name = names[index] if isinstance(names, list) and index < len(names) else ""
            pairs.append((str(name or ""), str(url)))

    seen = set()
    unique = []
    for name, url in pairs:
        canonical = canonicalise_url(url)
        if not canonical or canonical in seen:
            continue
        seen.add(canonical)
        unique.append((name, url))
    return unique


def merge_article_records(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    preferred, other = (
        (left, right)
        if authority_score(left) >= authority_score(right)
        else (right, left)
    )
    merged = dict(preferred)

    pairs = source_pairs(left) + source_pairs(right)
    seen = set()
    unique_pairs = []
    for name, url in pairs:
        canonical = canonicalise_url(url)
        if not canonical or canonical in seen:
            continue
        seen.add(canonical)
        unique_pairs.append((name, url))

    merged["source_names"] = [name for name, _ in unique_pairs]
    merged["source_urls"] = [url for _, url in unique_pairs]
    merged["source_count"] = len(unique_pairs)
    merged["story_key"] = build_story_key(preferred)

    if unique_pairs:
        merged["source_name"] = unique_pairs[0][0]
        merged["source_url"] = unique_pairs[0][1]

    # Keep the newest timestamp while retaining the more authoritative copy.
    timestamps = [
        str(left.get("published_at") or ""),
        str(right.get("published_at") or ""),
    ]
    merged["published_at"] = max(timestamps)

    return merged


def dedupe_article_records(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clusters: list[dict[str, Any]] = []

    for item in items:
        item = dict(item)
        item["story_key"] = build_story_key(item)

        matched_index = None
        for index, existing in enumerate(clusters):
            if (
                item["story_key"] == existing.get("story_key")
                or same_story(item, existing)
            ):
                matched_index = index
                break

        if matched_index is None:
            clusters.append(item)
        else:
            clusters[matched_index] = merge_article_records(
                clusters[matched_index], item
            )

    return clusters
