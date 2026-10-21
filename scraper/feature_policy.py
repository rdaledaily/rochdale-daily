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
