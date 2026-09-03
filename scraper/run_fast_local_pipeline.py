"""Rochdale-first runtime configuration for the autonomous news pipeline.

The production goal is a borough-wide newsroom, not a narrow fast-scrape lane.
Every run therefore reserves discovery capacity for every configured news beat
and every official Rochdale ward, supplements that with high-value searches,
keeps useful leads between runs, rejects obvious non-news sources before they
consume rewrite capacity, and still applies the strict locality/editorial gates
before publication.
"""
from __future__ import annotations

from dataclasses import fields as dataclass_fields
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
from urllib.parse import urlparse

import scraper as core
from search_queries import (
    CATEGORY_QUERIES,
    ROCHDALE_WARDS as SEARCH_WARDS,
    SearchQuery,
    build_search_query_specs,
    ward_query,
)


MIXED_SOURCE_NAMES = {
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
        "environment",  # planning folds into environment (3 Sep 2026)
    ),
    SearchQuery(
        "priority:planning-council",
        'site:rochdale.gov.uk (planning OR development OR demolition) '
        '(Rochdale OR Heywood OR Middleton OR Littleborough)',
        "environment",  # planning folds into environment (3 Sep 2026)
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

RESERVOIR_FILE = Path(core.ROOT) / "newsroom_candidates.json"
RESERVOIR_HOURS = max(24, int(os.getenv("CANDIDATE_RESERVOIR_HOURS", "96")))
CANDIDATE_FIELD_NAMES = {item.name for item in dataclass_fields(core.Candidate)}

LOW_VALUE_SOURCE_DOMAINS = {
    "1xbet.com",
    "flashscore.co.uk",
    "jobijoba.co.uk",
    "jobs24.co.uk",
    "simplyhired.co.uk",
    "simplyhired.com",
}
LOW_VALUE_SOURCE_NAMES = (
    "1xbet",
    "flashscore",
    "jobijoba",
    "jobs24",
    "simplyhired",
    "eat jobs",
)
NON_NEWS_PATH_RE = re.compile(
    r"/(?:contact-us|noindex|privacy|terms|cookies?|police-custody-suites|"
    r"sessions/fitness-classes|live-departures)(?:/|$)",
    re.I,
)
NON_NEWS_TITLE_RE = re.compile(
    r"\b(?:contact details|contact information|how to contact|opening times|"
    r"privacy policy|cookie policy|terms and conditions|live departures|"
    r"fitness classes?|custody centre information)\b",
    re.I,
)
NEWS_ACTION_RE = re.compile(
    r"\b(?:announc|launch|open(?:ed|ing|s)?|clos(?:ed|ing|ure|es)|appoint|"
    r"resign|arrest|charg|jailed|sentenc|appeal|missing|found|collision|crash|"
    r"fire|flood|warning|investigat|prosecut|award|funding|grant|planning|"
    r"approved|refused|vote|election|strike|protest|disruption|cancel)\w*\b",
    re.I,
)


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


def _append_unique(target: list[SearchQuery], seen: set[str], spec: SearchQuery) -> None:
    key = spec.query.casefold().strip()
    if not key or key in seen:
        return
    seen.add(key)
    target.append(spec)


def configure_sources() -> None:
    """Use local sources broadly but require mixed-region publishers to prove locality."""
    # This ticket seller is not a newsroom source. Dedicated event ingestion remains
    # available elsewhere; it must not consume ordinary news discovery/rewrite slots.
    core.DISCOVERY_PAGES[:] = [
        source for source in core.DISCOVERY_PAGES
        if source.get("name") != "What's Occurrin' Events"
    ]

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


def configure_runtime_depth() -> None:
    """Keep the fast lane fast, but not so shallow that it misses the news."""
    core.REQUEST_TIMEOUT = max(int(core.REQUEST_TIMEOUT), 8)
    core.DISCOVERY_LINKS_PER_SOURCE = max(int(core.DISCOVERY_LINKS_PER_SOURCE), 24)
    core.RSS_ITEMS_PER_SOURCE = max(int(core.RSS_ITEMS_PER_SOURCE), 75)
    core.DISCOVERY_PAGE_LIMIT = max(int(core.DISCOVERY_PAGE_LIMIT), 2)
    core.MIN_BALANCED_SELECTION_LIMIT = max(int(core.MIN_BALANCED_SELECTION_LIMIT), 40)
    if hasattr(core, "SLOW_DOMAIN_FAILURE_THRESHOLD"):
        core.SLOW_DOMAIN_FAILURE_THRESHOLD = max(int(core.SLOW_DOMAIN_FAILURE_THRESHOLD), 2)
    if hasattr(core, "SLOW_DOMAIN_BENCH_HOURS"):
        core.SLOW_DOMAIN_BENCH_HOURS = min(int(core.SLOW_DOMAIN_BENCH_HOURS), 6)


def configure_source_quality_gate() -> None:
    """Stop betting, jobs and scoreboards from masquerading as journalism."""
    original = core.source_is_denied

    def denied(source_name: str = "", source_url: str = "") -> bool:
        host = (urlparse(str(source_url or "")).hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        if any(host == domain or host.endswith("." + domain) for domain in LOW_VALUE_SOURCE_DOMAINS):
            return True
        lowered_name = core.normalise_ws(source_name).casefold()
        if any(marker in lowered_name for marker in LOW_VALUE_SOURCE_NAMES):
            return True
        return original(source_name, source_url)

    core.source_is_denied = denied


def configure_searches(now: datetime | None = None) -> None:
    """Guarantee borough breadth inside the 68-query Google News safety ceiling.

    The previous half-hour wrapper concatenated two quarter-hour shards and then
    truncated the combined list to 68. In practice the priority/always-on front
    of the list consumed the budget and the second shard -- including many ward
    and category searches -- never ran. The new plan reserves slots explicitly:
    every configured category, every official ward, then all high-value searches.
    Remaining capacity rotates through the deeper topic/source/councillor matrix.
    """
    current = now or datetime.now(timezone.utc)
    combined: list[SearchQuery] = []
    seen: set[str] = set()

    # First-class newsroom coverage: never allow priorities to crowd these out.
    for category, query in CATEGORY_QUERIES:
        _append_unique(combined, seen, SearchQuery(f"category:{category}", query, category))
    for ward in SEARCH_WARDS:
        _append_unique(combined, seen, ward_query(ward))

    # Breaking/high-value desk searches, including EXTRA_FRESH_SEARCHES appended
    # by run_newspaper_pipeline.py before configure() is called.
    for spec in PRIORITY_SEARCHES:
        _append_unique(combined, seen, spec)

    # Fill the remaining safe capacity from both logical quarter-hour shards so
    # detailed topics, named places, councillors and source-specific queries keep
    # rotating without sacrificing the guaranteed borough matrix above.
    synthetic_minutes = (5, 20) if current.minute < 30 else (35, 50)
    for minute in synthetic_minutes:
        synthetic = current.replace(minute=minute, second=0, microsecond=0)
        for spec in build_search_query_specs(max_queries=68, now=synthetic):
            _append_unique(combined, seen, spec)

    core.SEARCH_QUERY_SPECS = combined[:68]
    core.SEARCH_GROUPS = [spec.query for spec in core.SEARCH_QUERY_SPECS]
    core.log.info(
        "Borough search plan: %d queries; guaranteed categories=%d wards=%d; priority=%d",
        len(core.SEARCH_QUERY_SPECS),
        len(CATEGORY_QUERIES),
        len(SEARCH_WARDS),
        len(PRIORITY_SEARCHES),
    )


def _candidate_to_record(candidate) -> dict:
    return {
        name: getattr(candidate, name)
        for name in CANDIDATE_FIELD_NAMES
    }


def _candidate_from_record(record: dict):
    if not isinstance(record, dict):
        return None
    kwargs = {name: record.get(name) for name in CANDIDATE_FIELD_NAMES if name in record}
    try:
        return core.Candidate(**kwargs)
    except (TypeError, ValueError):
        return None


def _candidate_identity(candidate) -> str:
    url = core.canonicalise_url(str(getattr(candidate, "source_url", "") or ""))
    if url:
        return url
    return "|".join(
        (
            core.normalise_ws(getattr(candidate, "source_name", "")).casefold(),
            core.normalise_ws(getattr(candidate, "source_title", "")).casefold(),
            str(getattr(candidate, "source_published_at", "") or ""),
        )
    )


def _candidate_richness(candidate) -> tuple[int, datetime]:
    text = core.normalise_ws(
        f"{getattr(candidate, 'source_summary', '')} {getattr(candidate, 'source_body_excerpt', '')}"
    )
    published = core.parse_datetime(getattr(candidate, "source_published_at", ""))
    return len(text), published or datetime.min.replace(tzinfo=timezone.utc)


def _reservoir_candidate_allowed(candidate) -> bool:
    if str(getattr(candidate, "source_kind", "") or "") == "event":
        return False
    if core.source_is_denied(
        str(getattr(candidate, "source_name", "") or ""),
        str(getattr(candidate, "source_url", "") or ""),
    ):
        return False
    published = core.parse_datetime(getattr(candidate, "source_published_at", ""))
    if published is None:
        return False
    age = datetime.now(timezone.utc) - published
    return timedelta(minutes=-30) <= age <= timedelta(hours=RESERVOIR_HOURS)


def _load_reservoir() -> list:
    if not RESERVOIR_FILE.exists():
        return []
    try:
        payload = json.loads(RESERVOIR_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    records = payload.get("candidates", []) if isinstance(payload, dict) else payload
    candidates = []
    for record in records if isinstance(records, list) else []:
        candidate = _candidate_from_record(record)
        if candidate is not None and _reservoir_candidate_allowed(candidate):
            candidates.append(candidate)
    return candidates


def _save_reservoir(candidates: list) -> None:
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "retention_hours": RESERVOIR_HOURS,
        "count": len(candidates),
        "candidates": [_candidate_to_record(candidate) for candidate in candidates],
    }
    temporary = RESERVOIR_FILE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(RESERVOIR_FILE)


def configure_candidate_reservoir() -> None:
    """Keep discovered leads until processed or stale instead of losing them per run."""
    original = core.deduplicate_and_cross_reference

    def with_reservoir(current_candidates):
        previous = _load_reservoir()
        # Deep/browser runs get another chance to resolve wrappers first seen by
        # fast runs. Fast runs retain them for the next resolver rather than
        # throwing the lead away because its snippet is too short.
        if previous and bool(getattr(core, "BROWSER_RENDER_ENABLED", False)):
            try:
                core.apply_google_news_resolution(previous)
            except Exception as exc:
                core.log.debug("Reservoir wrapper resolution failed: %s", exc)

        merged: dict[str, object] = {}
        for candidate in [*previous, *list(current_candidates)]:
            if not _reservoir_candidate_allowed(candidate):
                continue
            key = _candidate_identity(candidate)
            if not key:
                continue
            prior = merged.get(key)
            if prior is None or _candidate_richness(candidate) >= _candidate_richness(prior):
                merged[key] = candidate

        durable = sorted(merged.values(), key=_selection_rank, reverse=True)
        _save_reservoir(durable)

        # The durable file can retain 96h for deep recovery, while each run only
        # sends candidates through today's configured freshness window (14h in
        # the fast lane). This cannot reintroduce stale homepage material.
        active = [
            candidate for candidate in durable
            if core.is_fresh(core.parse_datetime(getattr(candidate, "source_published_at", "")))
        ]
        core.log.info(
            "Candidate reservoir: %d retained, %d eligible in this run's %dh window",
            len(durable),
            len(active),
            int(core.MAX_NEWS_AGE_HOURS),
        )
        return original(active)

    core.deduplicate_and_cross_reference = with_reservoir


def _looks_like_static_non_news(candidate) -> bool:
    title = core.normalise_ws(str(getattr(candidate, "source_title", "") or ""))
    text = _candidate_text(candidate)
    path = urlparse(str(getattr(candidate, "source_url", "") or "")).path or ""
    if NEWS_ACTION_RE.search(text):
        return False
    return bool(NON_NEWS_PATH_RE.search(path) or NON_NEWS_TITLE_RE.search(title))


def configure_pre_rewrite_locality_gate() -> None:
    """Reject rival geography, static service pages and unusable wrappers before AI spend."""
    original = core.candidate_is_rewrite_eligible

    def rochdale_first(candidate, existing_by_story):
        text = _candidate_text(candidate)
        if _looks_like_static_non_news(candidate):
            core.log.info(
                "Rejected static/non-news page before rewrite: %s | %s",
                getattr(candidate, "source_title", ""),
                getattr(candidate, "source_url", ""),
            )
            return False
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
    configure_source_quality_gate()
    configure_sources()
    configure_runtime_depth()
    configure_searches()
    configure_candidate_reservoir()
    configure_pre_rewrite_locality_gate()
    configure_fresh_selection()


if __name__ == "__main__":
    configure()
    raise SystemExit(core.main())
