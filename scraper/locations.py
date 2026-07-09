"""Single source of truth for Rochdale Daily location-by-location discovery.

A search query matching a location name is discovery evidence only. It is never
sufficient proof that an article is local. Locality must later be confirmed from
article text, source identity, postcode, police force, council, road, venue or
another unambiguous Rochdale-area anchor.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LocationProfile:
    slug: str
    name: str
    query_terms: tuple[str, ...]
    local_anchors: tuple[str, ...]
    reject_terms: tuple[str, ...] = ()


BOROUGH_ANCHORS = (
    "Rochdale",
    "Rochdale borough",
    "Borough of Rochdale",
    "Greater Manchester",
    "Rochdale Borough Council",
    "Rochdale Council",
    "Greater Manchester Police",
    "GMP",
)


def _anchors(*extra: str) -> tuple[str, ...]:
    return BOROUGH_ANCHORS + tuple(extra)


LOCATIONS: tuple[LocationProfile, ...] = (
    LocationProfile(
        slug="rochdale",
        name="Rochdale",
        query_terms=("Rochdale", "Rochdale town centre"),
        local_anchors=_anchors("OL11", "OL12", "OL16"),
    ),
    LocationProfile(
        slug="heywood",
        name="Heywood",
        query_terms=("Heywood",),
        local_anchors=_anchors("OL10", "Rochdale borough"),
        reject_terms=("Heywood, Norfolk", "Heywood, Wiltshire"),
    ),
    LocationProfile(
        slug="middleton",
        name="Middleton",
        query_terms=("Middleton", "Middleton town centre"),
        local_anchors=_anchors("M24", "Rochdale borough"),
        reject_terms=(
            "Kate Middleton",
            "Princess of Wales",
            "Middleton, Leeds",
            "Middleton, Derbyshire",
        ),
    ),
    LocationProfile(
        slug="littleborough",
        name="Littleborough",
        query_terms=("Littleborough", "Hollingworth Lake", "Smithy Bridge"),
        local_anchors=_anchors("OL15", "Hollingworth Lake", "Smithy Bridge"),
    ),
    LocationProfile(
        slug="milnrow",
        name="Milnrow",
        query_terms=("Milnrow", "Slattocks"),
        local_anchors=_anchors("OL16", "Milnrow", "Slattocks"),
    ),
    LocationProfile(
        slug="newhey",
        name="Newhey",
        query_terms=("Newhey",),
        local_anchors=_anchors("OL16", "Milnrow and Newhey"),
    ),
    LocationProfile(
        slug="norden",
        name="Norden",
        query_terms=("Norden",),
        local_anchors=_anchors("OL11", "Norden, Rochdale", "Norden ward"),
        reject_terms=(
            "Norden, Swanage",
            "Swanage",
            "Dorset",
            "Dorset Police",
            "BH19",
            "Stevenage",
            "Hertfordshire",
            "Hertfordshire Constabulary",
            "SG1",
        ),
    ),
    LocationProfile(
        slug="healey",
        name="Healey",
        query_terms=("Healey", "Healey Dell"),
        local_anchors=_anchors("OL12", "Healey Dell", "Healey ward"),
    ),
    LocationProfile(
        slug="bamford",
        name="Bamford",
        query_terms=("Bamford",),
        local_anchors=_anchors("OL11", "Bamford, Rochdale", "Bamford ward"),
        reject_terms=("Bamford, Derbyshire", "Hope Valley"),
    ),
    LocationProfile(
        slug="castleton",
        name="Castleton",
        query_terms=("Castleton",),
        local_anchors=_anchors("OL11", "Castleton, Rochdale", "Castleton railway station"),
        reject_terms=("Castleton, Derbyshire", "Peak District", "Castleton, North Yorkshire"),
    ),
    LocationProfile(
        slug="kirkholt",
        name="Kirkholt",
        query_terms=("Kirkholt",),
        local_anchors=_anchors("OL11", "Kirkholt estate", "Balderstone and Kirkholt"),
    ),
    LocationProfile(
        slug="kingsway",
        name="Kingsway",
        query_terms=("Kingsway Rochdale", "Kingsway Business Park"),
        local_anchors=_anchors("OL16", "Kingsway Business Park", "Kingsway ward"),
    ),
    LocationProfile(
        slug="smallbridge",
        name="Smallbridge",
        query_terms=("Smallbridge",),
        local_anchors=_anchors("OL12", "Smallbridge and Firgrove"),
    ),
    LocationProfile(
        slug="wardle",
        name="Wardle",
        query_terms=("Wardle Rochdale", "Wardle village"),
        local_anchors=_anchors("OL12", "Wardle, Rochdale", "Wardle village"),
        reject_terms=("Wardle Academy",),
    ),
    LocationProfile(
        slug="spotland",
        name="Spotland",
        query_terms=("Spotland", "Spotland and Falinge"),
        local_anchors=_anchors("OL11", "Spotland Stadium", "Crown Oil Arena"),
    ),
    LocationProfile(
        slug="falinge",
        name="Falinge",
        query_terms=("Falinge", "Spotland and Falinge"),
        local_anchors=_anchors("OL12", "Falinge Park", "Spotland and Falinge"),
    ),
    LocationProfile(
        slug="deeplish",
        name="Deeplish",
        query_terms=("Deeplish", "Milkstone and Deeplish"),
        local_anchors=_anchors("OL11", "Milkstone and Deeplish"),
    ),
    LocationProfile(
        slug="balderstone",
        name="Balderstone",
        query_terms=("Balderstone Rochdale", "Balderstone and Kirkholt"),
        local_anchors=_anchors("OL11", "Balderstone and Kirkholt"),
        reject_terms=("Balderstone, Lancashire",),
    ),
    LocationProfile(
        slug="firgrove",
        name="Firgrove",
        query_terms=("Firgrove Rochdale", "Smallbridge and Firgrove"),
        local_anchors=_anchors("OL16", "Firgrove Playing Fields", "Smallbridge and Firgrove"),
    ),
    LocationProfile(
        slug="whitworth",
        name="Whitworth",
        query_terms=("Whitworth Rossendale", "Whitworth Rochdale"),
        local_anchors=(
            "Whitworth",
            "Rossendale",
            "Lancashire",
            "OL12",
            "Rochdale",
            "Greater Manchester",
        ),
        reject_terms=("Whitworth University", "Whitworth Art Gallery"),
    ),
)


LOCATION_BY_SLUG = {profile.slug: profile for profile in LOCATIONS}


def get_location(slug: str) -> LocationProfile:
    """Return a configured location or raise a clear error."""
    key = str(slug or "").strip().lower()
    try:
        return LOCATION_BY_SLUG[key]
    except KeyError as exc:
        valid = ", ".join(sorted(LOCATION_BY_SLUG))
        raise ValueError(f"Unknown location {slug!r}. Expected one of: {valid}") from exc
