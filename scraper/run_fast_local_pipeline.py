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
5. OpenAI is preferred but is no longer a single point of failure. If the API
   key is absent, the request fails, or the model cannot produce a passing draft,
   a conservative attributed source-led brief is built only from collected facts.
   A valid local story therefore cannot disappear solely because AI is down.

It also adds direct local political-party discovery and always-on high-value
queries for crime, planning, utilities and local political activity.
"""
from __future__ import annotations

from datetime import datetime, timezone
import html
import re

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


def _source_led_sentences(candidate) -> list[str]:
    """Return a small set of factual source sentences for emergency publication."""
    text = core.normalise_ws(
        f"{candidate.source_summary or ''} {candidate.source_body_excerpt or ''}"
    )
    if not text:
        return []
    chunks = re.split(r"(?<=[.!?])\s+", text)
    kept: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        sentence = core.normalise_ws(chunk).strip(" -–—")
        if len(sentence.split()) < 8:
            continue
        if len(sentence) > 320:
            sentence = sentence[:317].rsplit(" ", 1)[0] + "…"
        key = re.sub(r"\W+", " ", sentence.casefold()).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        kept.append(sentence)
        if len(kept) >= 5:
            break
    return kept


def _source_led_fallback(candidate):
    """Build a conservative attributed brief without inventing any new facts."""
    sentences = _source_led_sentences(candidate)
    if not sentences:
        return None

    source_name = core.normalise_ws(candidate.source_name) or "the identified source"
    title = core.strip_markdown(candidate.source_title or "Local update in the Rochdale borough")[:155]
    if len(title.split()) < 5:
        title = f"Rochdale update: {title}"[:155]

    # Keep the source's factual meaning visible while making attribution explicit.
    paragraphs: list[str] = []
    for idx, sentence in enumerate(sentences):
        if idx == 0:
            paragraphs.append(f"According to {source_name}, {sentence[0].lower() + sentence[1:] if len(sentence) > 1 else sentence}")
        else:
            paragraphs.append(sentence)

    # The public feed requires enough substance to be useful. If the collector only
    # recovered one or two long source sentences, split them conservatively rather
    # than inventing filler or dropping the story.
    while len(paragraphs) < 3:
        longest_idx = max(range(len(paragraphs)), key=lambda i: len(paragraphs[i]))
        current = paragraphs[longest_idx]
        split_at = current.rfind(", ", 80)
        if split_at < 80 or split_at > len(current) - 50:
            break
        first = current[:split_at].rstrip(", ") + "."
        second = current[split_at + 2:].strip()
        if second:
            second = second[0].upper() + second[1:]
            paragraphs[longest_idx:longest_idx + 1] = [first, second]
        else:
            break

    public_text = core.normalise_ws(" ".join(paragraphs))
    if len(public_text.split()) < 50:
        return None

    excerpt = core.normalise_ws(" ".join(sentences[:2]))[:360]
    evidence = core.normalise_ws(f"{title} {excerpt} {public_text}")
    category = core.editorial_category(evidence, candidate.category or "news")
    if category not in core.PUBLISHED_CATEGORIES:
        category = "news"
    area = candidate.area if candidate.area in core.AREA_KEYWORDS else "rochdale"

    sensitive = core.is_sensitive(evidence, category)
    if sensitive:
        title = core.redact_private_location(title)
        excerpt = core.redact_private_location(excerpt)
        paragraphs = [core.redact_private_location(p) for p in paragraphs]

    image_url, image_credit, image_credit_url, original_image_url = core.source_image(
        candidate, category, title
    )
    source_urls = [candidate.source_url] + [
        item["url"] for item in candidate.related_sources[:11] if item.get("url")
    ]
    source_names = [candidate.source_name] + [
        item["name"] for item in candidate.related_sources[:11] if item.get("name")
    ]

    return {
        "id": core.stable_id(candidate.source_url),
        "story_key": candidate.story_key or core.build_story_key(candidate),
        "title": title,
        "slug": core.make_slug(title),
        "excerpt": excerpt,
        "content_html": "".join(f"<p>{html.escape(p)}</p>" for p in paragraphs),
        "area": area,
        "category": category,
        "types": [category],
        "published_at": candidate.source_published_at,
        "scraped_at": core.iso_utc(core.utc_now()),
        "image_url": image_url,
        "image_credit": image_credit,
        "image_credit_url": image_credit_url,
        "source_image_candidate_url": original_image_url,
        "source_image_reuse_status": (
            "publisher-image-cached-and-credited" if image_credit_url
            else "curated-library-photo" if image_url.startswith("assets/img/cards/")
            else "category-fallback"
        ),
        "event_start_at": candidate.event_start_at,
        "event_end_at": candidate.event_end_at,
        "event_location": candidate.event_location,
        "source_kind": candidate.source_kind,
        "source_name": candidate.source_name,
        "source_url": candidate.source_url,
        "source_names": source_names,
        "source_urls": source_urls,
        "source_count": len(source_urls),
        "social_context_used": False,
        "social_reaction_count": 0,
        "official_social_update_count": 0,
        "social_platforms": [],
        "social_context_note": "",
        "sensitive_story": sensitive,
        "police_matter": category == "crime",
        "requires_approval": False,
        "legal_disclaimer": core.default_legal_disclaimer(sensitive),
        "right_to_reply": f"Anyone directly affected may request a correction or right of reply by emailing {core.RIGHT_TO_REPLY_EMAIL}.",
        "byline": "Rochdale Daily Newsdesk",
        "status": "published",
        "publication_route": "source-led-fallback",
        "rewrite_quality_checked": False,
        "editorial_style_version": core.STYLE_VERSION,
        "style_rewrite_status": "source-led-emergency-fallback",
        "discovery_query_label": candidate.discovery_query_label,
        "searched_location_slug": candidate.searched_location_slug,
        "searched_location_name": candidate.searched_location_name,
    }


def configure_source_led_fallback() -> None:
    """Never turn a valid selected story into zero output just because AI is down."""
    original = core.rewrite_candidate

    def resilient_rewrite(candidate, client):
        article = original(candidate, client)
        if article is not None:
            return article
        fallback = _source_led_fallback(candidate)
        if fallback is not None:
            core.log.warning(
                "Publishing grounded source-led fallback for %s because AI rewrite was unavailable or rejected.",
                candidate.source_url,
            )
        return fallback

    core.rewrite_candidate = resilient_rewrite


def configure() -> None:
    configure_sources()
    configure_searches()
    configure_pre_rewrite_locality_gate()
    configure_fresh_selection()
    configure_source_led_fallback()


if __name__ == "__main__":
    configure()
    raise SystemExit(core.main())
