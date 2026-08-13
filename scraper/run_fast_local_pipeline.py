"""Rochdale-first runtime configuration for the autonomous news pipeline.

This wrapper fixes production issues without duplicating scraper.py:

1. The query matrix was designed for four quarter-hour runs, but production now
   runs at :05 and :35. We merge the two quarter-hour shards belonging to each
   half-hour run, so the complete matrix is covered again.
2. Mixed Greater Manchester publishers were being assigned Rochdale as a
   default area. That allowed Bury/Whitefield/Prestwich candidates to consume
   scarce rewrite slots before the final locality gate rejected them. Mixed
   publishers now have to prove Rochdale locality before rewrite selection.
3. Balanced selection reserves categories, wards and areas in INPUT order. The
   discovery collectors finish concurrently, so that order is not chronological.
   Without an explicit freshness sort, an older candidate can consume a reserved
   rewrite slot ahead of a story published minutes ago. The fast pipeline now
   sorts every selection pool newest-first, with grounded publisher material
   preferred when timestamps are equal.
4. Unresolved Google News wrappers that contain only a headline/short snippet
   cannot pass the grounded editorial rewrite. They are rejected before they can
   consume an OpenAI slot; resolved wrappers and wrappers carrying substantial
   source text remain eligible.
5. Every ordinary scraper story must pass the OpenAI grounded rewrite and the
   source-overlap quality checks before publication. If the API is unavailable
   or the rewrite is rejected, the candidate is skipped. Source-led emergency
   fallbacks are deliberately disabled because they can reproduce publisher or
   social-media wording too closely.

It also adds direct local political-party discovery and always-on high-value
queries for crime, planning, utilities and local political activity.
"""
from __future__ import annotations

from datetime import datetime, timezone

import scraper as core
from search_queries import SearchQuery, build_search_query_specs


MIXED_SOURCE_NAMES = {
    "Roch Valley Radio Local News",
    "Roch Valley Radio Notices",
    "Greater Manchester Police",
    "Greater Manchester Fire and Rescue Service",
    "TfGM Newsroom",
    "TfGM Travel Alerts",
    "Northern News",
    "Northern Service Updates",
    "GMCA News",
    "BBC Manchester",
    "About Manchester",
    "The Independent — Rochdale",
    "Groundwork Greater Manchester",
}

DIRECT_LOCAL_POLITICAL_SOURCES = [
    {
        "name": "Rochdale Labour",
        "url": "https://rochdale.laboursites.org/",
        "default_area": "rochdale",
        "default_category": "politics",
        "trusted_local": True,
        "link_pattern": "/",
    },
    {
        "name": "Rochdale Liberal Democrats",
        "url": "https://www.rochdalelibdems.org.uk/news",
        "default_area": "rochdale",
        "default_category": "politics",
        "trusted_local": True,
        "link_pattern": "/news/|/news/article/",
    },
    {
        "name": "Rochdale Green Party",
        "url": "https://rochdale.greenparty.org.uk/",
        "default_area": "rochdale",
        "default_category": "politics",
        "trusted_local": True,
        "link_pattern": "/",
    },
    {
        "name": "Heywood Middleton North and Rochdale Conservatives",
        "url": "https://www.hmnrconservatives.org.uk/news",
        "default_category": "politics",
        "link_pattern": "/news/",
    },
]

PRIORITY_SEARCHES = [
    SearchQuery("priority:reform-rochdale", 'site:reformparty.uk Rochdale', "politics"),
    SearchQuery("priority:reform-rochdale-local", 'Rochdale "Reform UK" councillor', "politics"),
    SearchQuery("priority:restore-rochdale", 'site:restorebritain.org.uk Rochdale', "politics"),
    SearchQuery("priority:workers-party-rochdale", 'site:workerspartygb.org Rochdale councillor', "politics"),
    SearchQuery("priority:labour-rochdale", 'site:rochdale.laboursites.org Rochdale', "politics"),
    SearchQuery("priority:libdem-rochdale", 'site:rochdalelibdems.org.uk Rochdale', "politics"),
    SearchQuery("priority:green-rochdale", 'site:rochdale.greenparty.org.uk Rochdale', "politics"),
    SearchQuery("priority:conservative-rochdale", 'site:hmnrconservatives.org.uk Rochdale', "politics"),
    SearchQuery(
        "priority:planning-rochdale",
        '(Rochdale OR Heywood OR Middleton OR Littleborough OR Milnrow) '
        '("planning application" OR "planning permission" OR demolition OR development OR HMO)',
        "planning",
    ),
    SearchQuery(
        "priority:planning-council",
        'site:rochdale.gov.uk (planning OR development OR demolition) '
        '(Rochdale OR Heywood OR Middleton OR Littleborough)',
        "planning",
    ),
    SearchQuery(
        "priority:crime-fast",
        'site:gmp.police.uk (Rochdale OR Heywood OR Middleton OR Littleborough OR Milnrow) '
        '(arrest OR appeal OR murder OR robbery OR burglary OR assault OR collision OR missing OR wanted)',
        "crime",
    ),
    SearchQuery(
        "priority:crime-web",
        '(Rochdale OR Heywood OR Middleton OR Littleborough OR Milnrow) '
        '(arrested OR jailed OR charged OR police OR stabbing OR shooting OR collision OR crash)',
        "crime",
    ),
    SearchQuery(
        "priority:water",
        '(Rochdale OR Heywood OR Middleton OR Littleborough OR Milnrow OR Newhey) '
        '("water off" OR "no water" OR "burst main" OR "low pressure" OR "United Utilities")',
        "news",
    ),
    SearchQuery(
        "priority:power",
        '(Rochdale OR Heywood OR Middleton OR Littleborough OR Milnrow OR Newhey) '
        '("power cut" OR outage OR electricity OR "Electricity North West")',
        "news",
    ),
    SearchQuery(
        "priority:roads",
        '(Rochdale OR Heywood OR Middleton OR Littleborough OR Milnrow OR Newhey) '
        '(collision OR crash OR "road closed" OR "road closure" OR incident)',
        "traffic",
    ),
    SearchQuery(
        "priority:environment",
        '(Rochdale OR Heywood OR Middleton OR Littleborough OR Milnrow OR Newhey) '
        '(pollution OR landfill OR flooding OR river OR reservoir OR sewage OR wildlife OR environment)',
        "environment",
    ),
]


def _candidate_text(candidate) -> str:
    return " ".join(
        str(getattr(candidate, field, "") or "")
        for field in (
            "source_title",
            "source_summary",
            "source_body_excerpt",
            "event_location",
            "source_name",
            "source_url",
        )
    )


def _selection_rank(item) -> tuple[datetime, int, int]:
    """Newest first; prefer grounded publisher material on equal timestamps."""
    published = core.parse_datetime(getattr(item, "source_published_at", ""))
    if published is None:
        published = datetime.min.replace(tzinfo=timezone.utc)

    source_url = str(getattr(item, "source_url", "") or "")
    resolved = 0 if core.is_google_wrapper(source_url) else 1
    source_text = core.normalise_ws(
        " ".join(
            str(getattr(item, field, "") or "")
            for field in ("source_summary", "source_body_excerpt")
        )
    )
    return published, resolved, min(len(source_text), 5000)


def configure_sources() -> None:
    """Make mixed-region sources prove locality and add local party pages."""
    for source in core.DISCOVERY_PAGES:
        if source.get("name") in MIXED_SOURCE_NAMES:
            source.pop("trusted_local", None)
            source["default_area"] = ""

    existing_names = {str(source.get("name") or "") for source in core.DISCOVERY_PAGES}
    for source in DIRECT_LOCAL_POLITICAL_SOURCES:
        if source["name"] not in existing_names:
            core.DISCOVERY_PAGES.append(dict(source))

    core.DISCOVERY_LISTING_OVERRIDES["Roch Valley Radio Local News"] = [
        "https://www.rochvalleyradio.com/news/local-news/"
    ]


def configure_searches(now: datetime | None = None) -> None:
    """Cover both missing quarter-hour shards in each production half-hour."""
    current = now or datetime.now(timezone.utc)
    synthetic_minutes = (5, 20) if current.minute < 30 else (35, 50)

    combined: list[SearchQuery] = list(PRIORITY_SEARCHES)
    seen = {item.query.casefold().strip() for item in combined}
    for minute in synthetic_minutes:
        synthetic = current.replace(minute=minute, second=0, microsecond=0)
        for spec in build_search_query_specs(max_queries=68, now=synthetic):
            key = spec.query.casefold().strip()
            if key in seen:
                continue
            seen.add(key)
            combined.append(spec)

    core.SEARCH_QUERY_SPECS = combined[:68]
    core.SEARCH_GROUPS = [spec.query for spec in core.SEARCH_QUERY_SPECS]


def configure_pre_rewrite_locality_gate() -> None:
    """Reject explicit rival geography and unusable wrappers before AI spend."""
    original = core.candidate_is_rewrite_eligible

    def rochdale_first(candidate, existing_by_story):
        text = _candidate_text(candidate)
        if core.has_disqualifying_evidence(text, candidate.source_name, candidate.source_url):
            return False

        if candidate.source_name in MIXED_SOURCE_NAMES:
            probe = {
                "title": candidate.source_title,
                "excerpt": candidate.source_summary,
                "summary": candidate.source_summary,
                "content_html": candidate.source_body_excerpt,
                "event_location": candidate.event_location,
                "source_name": candidate.source_name,
                "source_url": candidate.source_url,
                "area": "",
            }
            if not core.article_is_local(probe) and not core.rochdale_traffic_area(text):
                if not core.BOROUGH_FINISHED_LOCATION_RE.search(core.normalise_ws(text)):
                    return False

        if core.is_google_wrapper(str(candidate.source_url or "")):
            substance = core.normalise_ws(
                f"{candidate.source_summary or ''} {candidate.source_body_excerpt or ''}"
            )
            if len(substance) < 500:
                return False

        return original(candidate, existing_by_story)

    core.candidate_is_rewrite_eligible = rochdale_first


def configure_fresh_selection() -> None:
    """Make every balanced-selection reservation choose the freshest candidate."""
    original = core.balanced_select

    def freshest_first(items, *args, **kwargs):
        ordered = sorted(list(items), key=_selection_rank, reverse=True)
        return original(ordered, *args, **kwargs)

    core.balanced_select = freshest_first


def configure() -> None:
    configure_sources()
    configure_searches()
    configure_pre_rewrite_locality_gate()
    configure_fresh_selection()


if __name__ == "__main__":
    configure()
    raise SystemExit(core.main())
