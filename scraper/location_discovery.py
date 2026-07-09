"""Location-by-location search matrix for Rochdale Daily.

This module only creates discovery queries. A matching search term is never
proof that an article is local; every result must still pass the separate
locality validation stage before it can be rewritten or published.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

try:
    # Works when imported as part of the scraper package.
    from .locations import LOCATIONS, LocationProfile, get_location
except ImportError:
    # Works when files are run directly from the scraper directory.
    from locations import LOCATIONS, LocationProfile, get_location


CATEGORY_TERMS: dict[str, tuple[str, ...]] = {
    "crime": (
        "police",
        "arrest",
        "arrested",
        "charged",
        "court",
        "murder",
        "manslaughter",
        "assault",
        "robbery",
        "burglary",
        "theft",
        "fraud",
        "arson",
        "wanted",
        "appeal",
        "missing",
        '"public disorder"',
    ),
    "traffic": (
        "collision",
        "crash",
        '"road closure"',
        "roadworks",
        "pothole",
        "potholes",
        "speeding",
        "traffic",
        "motorway",
        "M62",
    ),
    "transport": (
        "bus",
        "buses",
        "tram",
        "Metrolink",
        "train",
        "rail",
        "Northern",
        '"Bee Network"',
        "disruption",
        "cancellation",
    ),
    "politics": (
        "council",
        "councillor",
        "election",
        "vote",
        "voted",
        "motion",
        "committee",
        "MP",
        "Parliament",
        "campaign",
    ),
    "community": (
        "charity",
        "fundraiser",
        "fundraising",
        "volunteer",
        "donation",
        '"community group"',
        "residents",
        "protest",
        "support",
    ),
    "events": (
        "event",
        "festival",
        "fair",
        "concert",
        "exhibition",
        "workshop",
        '"coffee morning"',
        "tickets",
        '"what\'s on"',
    ),
    "business": (
        "business",
        "shop",
        "restaurant",
        "takeaway",
        "opening",
        "closure",
        "jobs",
        "investment",
        "regeneration",
        "development",
    ),
    "education": (
        "school",
        "academy",
        "college",
        "nursery",
        "pupils",
        "students",
        "headteacher",
        "Ofsted",
        "SATs",
        '"A-level"',
    ),
    "health": (
        "NHS",
        "hospital",
        "clinic",
        "GP",
        "doctor",
        "health",
        '"mental health"',
        "care",
        "pharmacy",
    ),
    "sport": (
        "football",
        "rugby",
        "cricket",
        "boxing",
        "MMA",
        "netball",
        "athletics",
        "parkrun",
        "sport",
        "club",
        "match",
    ),
    "planning": (
        '"planning application"',
        "housing",
        "development",
        "demolition",
        "HMO",
        "licensing",
        '"change of use"',
        "construction",
    ),
    "environment": (
        "flood",
        "flooding",
        "weather",
        "pollution",
        "canal",
        "reservoir",
        "river",
        "park",
        "wildlife",
        "environment",
    ),
}


@dataclass(frozen=True)
class LocationDiscoveryQuery:
    """One independent location/category search."""

    label: str
    query: str
    category: str
    location_slug: str
    location_name: str


def _location_expression(profile: LocationProfile) -> str:
    """Create a search expression while reducing ambiguous place matches."""
    if profile.slug == "rochdale":
        terms = [f'"{term}"' for term in profile.query_terms]
    elif profile.slug == "whitworth":
        # Whitworth is immediately outside the borough but is part of the
        # publication's intended local coverage area.
        terms = [
            '"Whitworth" Rossendale',
            '"Whitworth" Rochdale',
        ]
    else:
        # Adding Rochdale here improves discovery precision, but locality is
        # still proved later from the article itself rather than from this
        # query string.
        terms = [f'"{term}" Rochdale' for term in profile.query_terms]

    return f"({' OR '.join(terms)})"


def _category_expression(category: str) -> str:
    try:
        terms = CATEGORY_TERMS[category]
    except KeyError as exc:
        valid = ", ".join(sorted(CATEGORY_TERMS))
        raise ValueError(
            f"Unknown category {category!r}. Expected one of: {valid}"
        ) from exc
    return f"({' OR '.join(terms)})"


def build_location_queries(
    location_slug: str | None = None,
    categories: Iterable[str] | None = None,
) -> list[LocationDiscoveryQuery]:
    """Build independent searches for every requested location and category.

    Supplying ``location_slug`` returns only that location's searches. This is
    what a future GitHub Actions matrix job will use, so a failed Healey run
    cannot prevent Newhey, Norden or another location from producing results.
    """
    profiles: tuple[LocationProfile, ...]
    if location_slug:
        profiles = (get_location(location_slug),)
    else:
        profiles = LOCATIONS

    selected_categories = tuple(categories or CATEGORY_TERMS.keys())
    queries: list[LocationDiscoveryQuery] = []

    for profile in profiles:
        location_expression = _location_expression(profile)
        for category in selected_categories:
            category_key = str(category).strip().lower()
            category_expression = _category_expression(category_key)
            queries.append(
                LocationDiscoveryQuery(
                    label=f"location:{profile.slug}:{category_key}",
                    query=f"{location_expression} {category_expression}",
                    category=category_key,
                    location_slug=profile.slug,
                    location_name=profile.name,
                )
            )

    return queries


def build_location_query_strings(
    location_slug: str | None = None,
    categories: Iterable[str] | None = None,
) -> list[str]:
    """Return only query strings for callers that do not need metadata."""
    return [
        item.query
        for item in build_location_queries(
            location_slug=location_slug,
            categories=categories,
        )
    ]


if __name__ == "__main__":
    # Simple manual check: running this file prints Newhey's category matrix.
    for item in build_location_queries("newhey"):
        print(f"{item.label}: {item.query}")
