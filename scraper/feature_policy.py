"""Reserve features must never acquire live incident or police appeal treatment."""
from __future__ import annotations
import re
from typing import Any


def is_reserve_feature(article: dict[str, Any]) -> bool:
    return bool(
        article.get("is_evergreen") is True
        or article.get("evergreen_id")
        or str(article.get("publication_route") or "").lower() == "evergreen_fallback"
        or str(article.get("source_kind") or "").lower() == "evergreen"
    )


def is_daily_briefing(article: dict[str, Any]) -> bool:
    """Morning Briefing / Evening Wrap-Up roundups of the paper's own stories.

    Measured 9-27 Oct 2026: 2.6 views per briefing against 11.7 per crime
    story, while each took a top-nine homepage slot from a real story. They
    stay published and in the newsletter; they are held below the top nine
    like sponsored pieces and reserve features."""
    return bool(
        article.get("briefing_slot")
        or str(article.get("publication_route") or "").lower() == "daily-briefing"
    )


TRAFFIC_CATEGORIES = {"traffic"}
TRAFFIC_HEADLINE = re.compile(
    r"\b(?:road\s*works?|road closures?|"
    r"(?:street|lane|road|avenue|drive)s? (?:in \w+ )?(?:to|will) close\b|"
    r"traffic diversions?|temporary traffic lights|lane closures?|resurfacing)\b",
    re.I,
)


PUBLIC_WARNING = re.compile(
    r"\b(?:(?:yellow|amber|red) (?:weather )?warnings?|weather warnings?|met office warnings?|"
    r"(?:snow|ice|wind|rain|fog|thunderstorm|heat|flood) warnings?|flood alerts?|"
    r"power cuts?|blackouts?|power outages?|without power|bomb scares?|"
    r"suspicious (?:package|item|device|object)s?|controlled explosion|bomb disposal|"
    r"evacuat\w*|lock ?downs?|locked down|gas leaks?)\b",
    re.I,
)
NAMED_STORM = re.compile(r"\bStorm [A-Z][a-z]+\b")
COLLISION_CLOSURE = re.compile(
    r"\b(?:crash|collision|accident|lorry fire|overturned)\b.*\b(?:clos\w*|shut|blocked)\b|"
    r"\b(?:closed|shut|blocked)\b.*\b(?:crash|collision|accident)\b",
    re.I,
)


def is_public_warning(article: dict[str, Any]) -> bool:
    """Warnings readers need now: weather warnings and named storms, power
    cuts, collisions that close roads, bomb scares and suspicious packages,
    evacuations, school lockdowns and gas leaks (editor's rule, 9 Nov 2026:
    always position 2 on the front page, under crime). Measured 9 Nov 2026
    against the 1,940-story archive: 8 headlines match, all genuine warnings.
    A warning is never treated as a traffic notice, even when filed as
    traffic. Same test as isPublicWarning in functions/articles/frontpage.json.js."""
    title = str(article.get("title") or "")
    return bool(PUBLIC_WARNING.search(title) or NAMED_STORM.search(title) or COLLISION_CLOSURE.search(title))


def is_traffic_notice(article: dict[str, Any]) -> bool:
    """Roadworks, road closures and diversions (editor's rule, 9 Nov 2026).

    They never take a top-nine homepage position or a place in the Morning
    Briefing. Measured 9 Nov 2026: two 03:21 roadworks notices led the front
    page and the briefing list over seven Remembrance Sunday stories. They stay
    published, in the traffic section and below the top nine. "Shop to close"
    and "school closure" are not traffic: only roads, streets and lanes match.
    Same test as isTrafficNotice in functions/articles/frontpage.json.js."""
    if is_public_warning(article):
        return False
    category = str(article.get("category") or "").strip().lower()
    types = {str(t).strip().lower() for t in (article.get("types") or []) if isinstance(t, str)}
    if category in TRAFFIC_CATEGORIES or types & TRAFFIC_CATEGORIES:
        return True
    return bool(TRAFFIC_HEADLINE.search(str(article.get("title") or "")))


def normalise_feature(article: dict[str, Any]) -> dict[str, Any]:
    """Return a copy; preserve publication dates, sources and original prose."""
    result = dict(article)
    if not is_reserve_feature(result):
        return result
    result["content_kind"] = "feature"
    result["kicker"] = "Feature"
    category = str(result.get("feature_category") or "community").lower()
    if category in {"crime", "news"}:
        category = "community"
    result["category"] = category
    result["types"] = [category]
    result["categories"] = [category]
    result.pop("secondary_category", None)
    result.pop("secondary_categories", None)
    for key in ("is_ongoing", "live_story", "breaking_news", "breaking", "is_breaking", "police_matter", "policeMatter"):
        result[key] = False
    for key in ("ongoing_label", "live_label", "breaking_label"):
        result[key] = ""
    result["live_updates"] = []
    # Remove only pipeline-generated incident scaffolding, never feature prose.
    body = str(result.get("content_html") or "")
    body = re.sub(r'<p class="ongoing-label">.*?</p>', '', body, flags=re.S)
    body = re.sub(r'<section class="live-update-timeline">.*?</section>', '', body, flags=re.S)
    body = re.sub(r'<h2>Update timeline</h2><ul>.*?</ul>', '', body, flags=re.S)
    result["content_html"] = body
    return result
