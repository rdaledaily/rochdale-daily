"""Balanced story selection and recruitment-content filtering.

This module has no third-party dependencies so GitHub Actions can validate it
before the main scraper runs.
"""

from __future__ import annotations

import html
import re
from collections import Counter, defaultdict, deque
from typing import Any
from urllib.parse import urlparse

PUBLISH_CATEGORIES = (
    "crime",
    "traffic",
    "transport",
    "politics",
    "education",
    "sport",
    "events",
    "business",
    "community",
    "health",
    "environment",
    "news",
)

# Current Rochdale Borough Council wards.
ROCHDALE_WARDS = (
    "Balderstone and Kirkholt",
    "Bamford",
    "Castleton",
    "Central Rochdale",
    "East Middleton",
    "Healey",
    "Hopwood Hall",
    "Kingsway",
    "Littleborough Lakeside",
    "Milkstone and Deeplish",
    "Milnrow and Newhey",
    "Norden",
    "North Heywood",
    "North Middleton",
    "Smallbridge and Firgrove",
    "South Middleton",
    "Spotland and Falinge",
    "Wardle, Shore and West Littleborough",
    "West Heywood",
    "West Middleton",
)

WARD_ALIASES = {
    "Balderstone and Kirkholt": (
        "balderstone and kirkholt",
        "balderstone",
        "kirkholt",
    ),
    "Bamford": ("bamford",),
    "Castleton": ("castleton",),
    "Central Rochdale": (
        "central rochdale",
        "rochdale town centre",
        "town centre rochdale",
        "milkstone road",
    ),
    "East Middleton": ("east middleton",),
    "Healey": ("healey ward", "healey area", "in healey"),
    "Hopwood Hall": ("hopwood hall",),
    "Kingsway": ("kingsway ward", "kingsway business park", "kingsway"),
    "Littleborough Lakeside": (
        "littleborough lakeside",
        "hollingworth lake",
    ),
    "Milkstone and Deeplish": (
        "milkstone and deeplish",
        "milkstone",
        "deeplish",
    ),
    "Milnrow and Newhey": (
        "milnrow and newhey",
        "milnrow",
        "newhey",
    ),
    "Norden": ("norden ward", "norden village", "in norden"),
    "North Heywood": ("north heywood",),
    "North Middleton": ("north middleton",),
    "Smallbridge and Firgrove": (
        "smallbridge and firgrove",
        "smallbridge",
        "firgrove",
    ),
    "South Middleton": ("south middleton",),
    "Spotland and Falinge": (
        "spotland and falinge",
        "spotland",
        "falinge",
    ),
    "Wardle, Shore and West Littleborough": (
        "wardle shore and west littleborough",
        "wardle, shore and west littleborough",
        "west littleborough",
        "shore ward",
        "wardle village",
    ),
    "West Heywood": ("west heywood",),
    "West Middleton": ("west middleton",),
}

AREA_TO_WARD = {
    "balderstone": "Balderstone and Kirkholt",
    "kirkholt": "Balderstone and Kirkholt",
    "bamford": "Bamford",
    "castleton": "Castleton",
    "healey": "Healey",
    "hopwood": "Hopwood Hall",
    "deeplish": "Milkstone and Deeplish",
    "milnrow": "Milnrow and Newhey",
    "newhey": "Milnrow and Newhey",
    "smallbridge": "Smallbridge and Firgrove",
    "firgrove": "Smallbridge and Firgrove",
    "spotland": "Spotland and Falinge",
    "falinge": "Spotland and Falinge",
    "wardle": "Wardle, Shore and West Littleborough",
}

JOB_URL_PARTS = (
    "/jobs",
    "/job/",
    "/careers",
    "/career/",
    "/vacancies",
    "/vacancy/",
    "/recruitment",
    "/work-for-us",
)

JOB_PATTERNS = (
    r"\bcareer(?:s)?\b",
    r"\bvacanc(?:y|ies)\b",
    r"\brecruit(?:ment|ing|er|ers)\b",
    r"\bnow hiring\b",
    r"\bwe(?:'re| are) hiring\b",
    r"\bhiring now\b",
    r"\bapply now\b",
    r"\bapplications? (?:are )?(?:now )?open\b",
    r"\bjoin (?:our|the) team\b",
    r"\bwork (?:for|with) us\b",
    r"\bemployment opportunit(?:y|ies)\b",
    r"\bjob(?:s)? (?:available|advert|advertisement|opening|openings|"
    r"opportunit(?:y|ies)|listing|listings|role|roles|fair|fairs)\b",
    r"\brole(?:s)? available\b",
    r"\bposition(?:s)? available\b",
    r"\bstaff wanted\b",
    r"\bcandidate(?:s)? required\b",
    r"\bsalary\b",
    r"\bper annum\b",
    r"\bfull[- ]time (?:job|role|position)\b",
    r"\bpart[- ]time (?:job|role|position)\b",
    r"\bpermanent (?:job|role|position)\b",
    r"\btemporary (?:job|role|position)\b",
    r"\bapprenticeship(?:s)?\b",
    r"\binternship(?:s)?\b",
    r"\bgraduate scheme(?:s)?\b",
)

TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


def get_value(item: Any, name: str, default: Any = "") -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def normalise_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = TAG_RE.sub(" ", text)
    return SPACE_RE.sub(" ", text).strip()


def item_text(item: Any) -> str:
    return normalise_text(" ".join(
        str(get_value(item, field, "") or "")
        for field in (
            "source_title",
            "title",
            "source_summary",
            "summary",
            "excerpt",
            "source_body_excerpt",
            "content_html",
            "event_location",
        )
    ))


def item_url(item: Any) -> str:
    return str(
        get_value(item, "source_url", "")
        or get_value(item, "url", "")
        or ""
    )


def is_job_or_career_post(item_or_text: Any, url: str = "") -> bool:
    if isinstance(item_or_text, str):
        text = normalise_text(item_or_text)
        candidate_url = str(url or "")
    else:
        text = item_text(item_or_text)
        candidate_url = item_url(item_or_text)

    path = urlparse(candidate_url).path.lower()
    if any(part in path for part in JOB_URL_PARTS):
        return True

    return any(
        re.search(pattern, text, flags=re.IGNORECASE)
        for pattern in JOB_PATTERNS
    )


def ward_for_item(item: Any) -> str:
    text = item_text(item).lower()
    area = str(get_value(item, "area", "") or "").lower().strip()

    # Prefer explicit full ward language.
    for ward, aliases in WARD_ALIASES.items():
        for alias in sorted(aliases, key=len, reverse=True):
            if re.search(
                rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])",
                text,
            ):
                return ward

    # Only map areas that identify a single ward unambiguously.
    return AREA_TO_WARD.get(area, "")


def source_key(item: Any) -> str:
    source = str(get_value(item, "source_name", "") or "").strip().lower()
    if source:
        return source
    host = (urlparse(item_url(item)).hostname or "").lower()
    return host or "unknown-source"


def category_key(item: Any) -> str:
    category = str(get_value(item, "category", "") or "news").lower()
    return category if category in PUBLISH_CATEGORIES else "news"


def unique_key(item: Any) -> str:
    return str(
        get_value(item, "story_key", "")
        or get_value(item, "source_url", "")
        or get_value(item, "url", "")
        or get_value(item, "source_title", "")
        or get_value(item, "title", "")
    ).lower()


def balanced_select(
    items: list[Any],
    limit: int,
    max_per_source: int = 4,
    max_per_category: int = 8,
) -> tuple[list[Any], dict[str, Any]]:
    """Select a diverse set without inventing coverage.

    Pass 1 reserves one slot per category represented in the candidate pool.
    Pass 2 reserves one slot per official ward represented in the pool.
    Pass 3 rotates across sources. Remaining slots are filled by rank order.

    Quotas are availability-based: an absent ward/category is reported rather
    than fabricated.
    """
    limit = max(0, int(limit))
    if limit == 0:
        return [], {
            "available_categories": [],
            "selected_categories": [],
            "available_wards": [],
            "selected_wards": [],
            "uncovered_categories": [],
            "uncovered_wards": [],
            "selected_by_source": {},
        }

    filtered = [item for item in items if not is_job_or_career_post(item)]

    selected: list[Any] = []
    selected_keys: set[str] = set()
    source_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    ward_counts: Counter[str] = Counter()

    available_categories = {
        category_key(item) for item in filtered
    }
    available_wards = {
        ward for item in filtered if (ward := ward_for_item(item))
    }

    def can_add(
        item: Any,
        *,
        relax_source: bool = False,
        relax_category: bool = False,
    ) -> bool:
        key = unique_key(item)
        source = source_key(item)
        category = category_key(item)

        if not key or key in selected_keys:
            return False
        if not relax_source and source_counts[source] >= max_per_source:
            return False
        if not relax_category and category_counts[category] >= max_per_category:
            return False
        return len(selected) < limit

    def add(
        item: Any,
        *,
        relax_source: bool = False,
        relax_category: bool = False,
    ) -> bool:
        if not can_add(
            item,
            relax_source=relax_source,
            relax_category=relax_category,
        ):
            return False

        key = unique_key(item)
        source = source_key(item)
        category = category_key(item)
        ward = ward_for_item(item)

        selected.append(item)
        selected_keys.add(key)
        source_counts[source] += 1
        category_counts[category] += 1
        if ward:
            ward_counts[ward] += 1
        return True

    # One item for every represented category.
    for category in PUBLISH_CATEGORIES:
        if category not in available_categories or len(selected) >= limit:
            continue
        for item in filtered:
            if category_key(item) == category and add(item):
                break

    # One item for every represented official ward.
    for ward in ROCHDALE_WARDS:
        if ward not in available_wards or ward_counts[ward] or len(selected) >= limit:
            continue
        for item in filtered:
            if ward_for_item(item) == ward and add(item):
                break

    # If source caps blocked a represented category or ward, relax the source
    # cap only for that missing coverage requirement.
    for category in PUBLISH_CATEGORIES:
        if (
            category in available_categories
            and category_counts[category] == 0
            and len(selected) < limit
        ):
            for item in filtered:
                if category_key(item) == category and add(
                    item,
                    relax_source=True,
                ):
                    break

    for ward in ROCHDALE_WARDS:
        if (
            ward in available_wards
            and ward_counts[ward] == 0
            and len(selected) < limit
        ):
            for item in filtered:
                if ward_for_item(item) == ward and add(
                    item,
                    relax_source=True,
                ):
                    break

    # Rotate across sources rather than exhausting one source first.
    source_queues: dict[str, deque[Any]] = defaultdict(deque)
    for item in filtered:
        if unique_key(item) not in selected_keys:
            source_queues[source_key(item)].append(item)

    source_order = deque(sorted(
        source_queues,
        key=lambda source: (
            source_counts[source],
            source,
        ),
    ))

    stalled_rounds = 0
    while source_order and len(selected) < limit:
        source = source_order.popleft()
        queue = source_queues[source]
        added_this_turn = False

        while queue:
            item = queue.popleft()
            if add(item):
                added_this_turn = True
                break

        if queue:
            source_order.append(source)

        if added_this_turn:
            stalled_rounds = 0
        else:
            stalled_rounds += 1
            if stalled_rounds > len(source_order) + 1:
                break

    # Fill any remaining places while retaining the category cap.
    if len(selected) < limit:
        for item in filtered:
            if len(selected) >= limit:
                break
            add(item, relax_source=True)

    diagnostics = {
        "available_categories": sorted(available_categories),
        "selected_categories": sorted(
            category for category, count in category_counts.items() if count
        ),
        "available_wards": sorted(available_wards),
        "selected_wards": sorted(
            ward for ward, count in ward_counts.items() if count
        ),
        "uncovered_categories": sorted(
            available_categories - set(category_counts)
        ),
        "uncovered_wards": sorted(
            available_wards - set(ward_counts)
        ),
        "selected_by_category": dict(sorted(category_counts.items())),
        "selected_by_ward": dict(sorted(ward_counts.items())),
        "selected_by_source": dict(sorted(source_counts.items())),
    }
    return selected, diagnostics
