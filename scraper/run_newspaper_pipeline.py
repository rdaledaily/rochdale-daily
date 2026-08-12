"""Rochdale Daily newsroom entrypoint.

Extends the existing Rochdale-first pipeline with indexed fallbacks for important
sources whose APIs/RSS feeds can be unavailable. The direct source remains
preferred whenever it works; these searches stop one broken integration from
making the local news desk blind.

The newspaper also applies an editorial-newsworthiness gate before any rewrite
slot is spent. Local SEO/service pages are not news merely because they mention
Rochdale repeatedly. Genuine business developments remain eligible.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

import scraper as core
import run_fast_local_pipeline as base
from search_queries import SearchQuery


EXTRA_FRESH_SEARCHES = [
    SearchQuery(
        "fallback:men-rochdale-today",
        'site:manchestereveningnews.co.uk (Rochdale OR Heywood OR Middleton OR Littleborough) when:1d',
        "news",
    ),
    SearchQuery(
        "fallback:gmp-rochdale-today",
        'site:gmp.police.uk (Rochdale OR Heywood OR Middleton OR Littleborough OR Milnrow) when:1d',
        "crime",
    ),
    SearchQuery(
        "fallback:rochdale-council-today",
        'site:rochdale.gov.uk/news (Rochdale OR Heywood OR Middleton OR Littleborough) when:1d',
        "news",
    ),
    SearchQuery(
        "fallback:tfgm-rochdale-today",
        '(site:news.tfgm.com OR site:tfgm.com) (Rochdale OR Heywood OR Middleton) when:1d',
        "transport",
    ),
    SearchQuery(
        "fallback:fire-rochdale-today",
        'site:manchesterfire.gov.uk (Rochdale OR Heywood OR Middleton OR Littleborough) when:2d',
        "news",
    ),
    SearchQuery(
        "fallback:nca-rochdale-today",
        'site:northerncarealliance.nhs.uk Rochdale when:2d',
        "health",
    ),
    SearchQuery(
        "fallback:local-public-posts-today",
        '("GMPRochdale" OR "Rochdale Borough Council" OR "Bee Network") '
        '(Rochdale OR Heywood OR Middleton OR Littleborough) when:1d',
        "news",
    ),
]


DOMAIN_IN_TITLE_RE = re.compile(
    r"\b(?:www\.)?[a-z0-9][a-z0-9.-]+\.(?:co\.uk|org\.uk|gov\.uk|ac\.uk|com|org|net|uk)\b",
    re.I,
)
SEO_LOCATION_TITLE_RE = re.compile(
    r"\b(?:in|near|across)\s+(?:rochdale|heywood|middleton|littleborough|milnrow|newhey|norden|bamford|castleton|wardle|whitworth)\b.*"
    r"\b(?:www\.)?[a-z0-9][a-z0-9.-]+\.(?:co\.uk|com|net|uk)\b",
    re.I,
)
COMMERCIAL_INTENT_RE = re.compile(
    r"\b(?:"
    r"looking for|our services?|our products?|we offer|we provide|we install|we lay|we supply|we fit|we build|"
    r"we repair|we specialise|we specialize|we serve|serving rochdale|across rochdale we|"
    r"get (?:a|your) (?:free )?quote|request (?:a|your) quote|free quotation|contact us|call us|call today|"
    r"book now|buy now|shop now|order now|request a callback|speak to (?:our|an) (?:team|expert)|"
    r"competitive prices?|affordable prices?|no obligation quote"
    r")\b",
    re.I,
)
FIRST_PERSON_SERVICE_RE = re.compile(
    r"\bwe\s+(?:offer|provide|install|lay|supply|fit|build|repair|replace|specialise|specialize|serve|cover)\b",
    re.I,
)
SERVICE_PATH_RE = re.compile(
    r"/(?:services?|products?|what-we-do|service-areas?|locations?|areas?|"
    r"driveways?|resin-bound(?:-stone)?|roofing|plumbing|landscaping|"
    r"solicitors?|estate-agents?|windows?|doors?|extensions?|paving)(?:/|$)",
    re.I,
)
NEWS_EVENT_RE = re.compile(
    r"\b(?:"
    r"announc(?:e|ed|es|ement|ing)|launch(?:ed|es|ing)?|open(?:ed|ing|s)?|clos(?:e|ed|es|ing|ure)|"
    r"appoint(?:ed|ment|s)?|acquir(?:e|ed|es|ing)|acquisition|sold|sale|merg(?:e|ed|er|ing)|takeover|"
    r"planning application|planning permission|invest(?:ed|ment|ing)|expand(?:s|ed|ing|ion)|"
    r"relocat(?:e|ed|es|ing|ion)|award(?:ed|s)?|contract(?:ed|s)?|funding|grant|"
    r"jobs?|recruit(?:ing|ment)|redundan(?:cy|cies)|job losses|administration|liquidation|bankrupt(?:cy)?|"
    r"recall|warning|fine(?:d)?|prosecut(?:ed|ion)|charged|court|investigation|incident|fire|flood|"
    r"new (?:store|shop|branch|premises|site|office|facility|owner|management)|"
    r"wins? (?:a |the )?(?:contract|award)|ceases? trading|goes? into administration"
    r")\b",
    re.I,
)


def _candidate_editorial_text(candidate) -> tuple[str, str, str]:
    title = core.normalise_ws(str(getattr(candidate, "source_title", "") or ""))
    body = core.normalise_ws(
        " ".join(
            str(getattr(candidate, field, "") or "")
            for field in ("source_summary", "source_body_excerpt")
        )
    )
    url = str(getattr(candidate, "source_url", "") or "")
    return title, body, url


def _looks_like_commercial_landing_page(candidate) -> bool:
    """Reject advertising/SEO service pages while retaining genuine business news."""
    source_kind = str(getattr(candidate, "source_kind", "") or "").casefold()
    if source_kind == "event":
        # A ticketed/commercial event can legitimately belong in What's On.
        return False

    title, body, url = _candidate_editorial_text(candidate)
    text = core.normalise_ws(f"{title} {body}")
    if not text:
        return False

    # A real development wins over commercial vocabulary. For example, a
    # company's own page announcing a Rochdale branch opening is still a story.
    if NEWS_EVENT_RE.search(text):
        return False

    path = urlparse(url).path or ""
    commercial_hits = len(COMMERCIAL_INTENT_RE.findall(text))
    first_person_service = bool(FIRST_PERSON_SERVICE_RE.search(text))
    service_path = bool(SERVICE_PATH_RE.search(path))
    domain_title = bool(DOMAIN_IN_TITLE_RE.search(title))
    seo_location_title = bool(SEO_LOCATION_TITLE_RE.search(title))

    # Strongest signals: the page title itself is an SEO location/service title,
    # or a naked business domain is being used as if it were a news headline.
    if seo_location_title:
        return True
    if domain_title and (commercial_hits > 0 or service_path or first_person_service):
        return True

    # Generic sales copy should not become an article even when Google or another
    # discovery source has indexed it as fresh/local content.
    if commercial_hits >= 2:
        return True
    if service_path and (commercial_hits > 0 or first_person_service):
        return True
    if first_person_service and commercial_hits > 0:
        return True

    return False


def configure_editorial_newsworthiness_gate() -> None:
    """Put a newspaper test in front of AI rewrite and source-led fallback."""
    original = core.candidate_is_rewrite_eligible

    def newsworthy(candidate, existing_by_story):
        if not original(candidate, existing_by_story):
            return False
        if _looks_like_commercial_landing_page(candidate):
            core.log.info(
                "Rejected commercial/SEO page before rewrite: %s | %s",
                getattr(candidate, "source_title", ""),
                getattr(candidate, "source_url", ""),
            )
            return False
        return True

    core.candidate_is_rewrite_eligible = newsworthy


def main() -> int:
    # scraper.py historically forces at least 168 hours even when production
    # asks for a shorter age window. A news desk should search recent material
    # first, so this entrypoint explicitly enforces the configured 72-hour cap.
    core.MAX_NEWS_AGE_HOURS = 72

    existing = {item.query.casefold().strip() for item in base.PRIORITY_SEARCHES}
    for item in EXTRA_FRESH_SEARCHES:
        if item.query.casefold().strip() not in existing:
            base.PRIORITY_SEARCHES.append(item)
            existing.add(item.query.casefold().strip())

    base.configure()
    configure_editorial_newsworthiness_gate()
    return core.main()


if __name__ == "__main__":
    raise SystemExit(main())
