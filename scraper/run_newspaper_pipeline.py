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

import os
import re
from urllib.parse import urlparse

import scraper as core
import run_fast_local_pipeline as base
from live_story_updates import install as install_live_story_updates
from reject_publisher_leaks import main as reject_publisher_leaks
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
        'site:manchesterfire.gov.uk/news (Rochdale OR Heywood OR Middleton OR Littleborough) when:1d',
        "environment",
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
    r"announc(?:e|ed|es|ement|ing)|launch(?:ed|es|ing)?|opened|opening|opens|closed|closing|closure|closes|"
    r"appoint(?:ed|ment|s)?|acquir(?:e|ed|es|ing)|acquisition|sold|merg(?:e|ed|er|ing)|takeover|"
    r"planning application|planning permission|invest(?:ed|ment|ing)|expand(?:s|ed|ing|ion)|"
    r"relocat(?:e|ed|es|ing|ion)|awarded|contract(?:ed|s)?|funding|grant(?:ed)?|"
    r"jobs?|recruit(?:ing|ment)|redundan(?:cy|cies)|job losses|administration|liquidation|bankrupt(?:cy)?|"
    r"recall|warning|fine(?:d)?|prosecut(?:ed|ion)|charged|court|investigation|incident|fire|flood|"
    r"new (?:store|shop|branch|premises|site|office|facility|owner|management)|"
    r"wins? (?:a |the )?(?:contract|award)|ceases? trading|goes? into administration"
    r")\b",
    re.I,
)
LIVE_MATERIAL_RE = re.compile(
    r"\b(?:named|identified|identity|victim|family|tribute|post[- ]mortem|cause of death|"
    r"arrested|charged|bailed|released|remanded|custody|murder|manslaughter|fatal|court|"
    r"hearing|convicted|sentenced|appeal|witness|found|missing|located|reopened|closed)\b",
    re.I,
)
LIVE_NAME_RE = re.compile(r"\b[A-Z][a-z'’-]{2,}\s+[A-Z][a-z'’-]{2,}\b")
LIVE_NUMBER_RE = re.compile(r"\b(?:\d{1,2}[:.]\d{2}|\d{1,2}\s+[A-Z][a-z]+|\d{2,})\b")
LIVE_AUTHORITATIVE_DOMAINS = {
    "gmp.police.uk",
    "rochdale.gov.uk",
    "manchesterfire.gov.uk",
    "greatermanchester-ca.gov.uk",
    "gmca.gov.uk",
    "tfgm.com",
    "news.tfgm.com",
    "nationalhighways.co.uk",
    "northerncarealliance.nhs.uk",
    "penninecare.nhs.uk",
}


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
        return False

    title, body, url = _candidate_editorial_text(candidate)
    text = core.normalise_ws(f"{title} {body}")
    if not text:
        return False

    if NEWS_EVENT_RE.search(text):
        return False

    path = urlparse(url).path or ""
    commercial_hits = len(COMMERCIAL_INTENT_RE.findall(text))
    first_person_service = bool(FIRST_PERSON_SERVICE_RE.search(text))
    service_path = bool(SERVICE_PATH_RE.search(path))
    domain_title = bool(DOMAIN_IN_TITLE_RE.search(title))
    seo_location_title = bool(SEO_LOCATION_TITLE_RE.search(title))

    if seo_location_title:
        return True
    if domain_title and (commercial_hits > 0 or service_path or first_person_service):
        return True
    if commercial_hits >= 2:
        return True
    if service_path and (commercial_hits > 0 or first_person_service):
        return True
    if first_person_service and commercial_hits > 0:
        return True

    return False


def _iter_existing_articles(existing_by_story):
    if isinstance(existing_by_story, dict):
        if "source_url" in existing_by_story or "slug" in existing_by_story:
            yield existing_by_story
        else:
            for value in existing_by_story.values():
                yield from _iter_existing_articles(value)
    elif isinstance(existing_by_story, (list, tuple, set)):
        for value in existing_by_story:
            yield from _iter_existing_articles(value)


def _canonical_url(value: str) -> str:
    try:
        return str(core.canonicalise_url(str(value or "")) or "").rstrip("/")
    except Exception:
        return str(value or "").strip().rstrip("/")


def _is_authoritative_live_url(url: str) -> bool:
    host = (urlparse(str(url or "")).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return any(host == domain or host.endswith("." + domain) for domain in LIVE_AUTHORITATIVE_DOMAINS)


def _article_public_text(article: dict) -> str:
    return core.normalise_ws(
        " ".join(
            str(article.get(field) or "")
            for field in ("title", "excerpt", "body", "content_html")
        )
    )


def _same_source_live_update(candidate, existing_by_story) -> bool:
    """Allow a duplicate URL only when an authoritative LIVE source has new facts."""
    title, body, source_url = _candidate_editorial_text(candidate)
    candidate_url = _canonical_url(source_url)
    if not candidate_url or not _is_authoritative_live_url(candidate_url):
        return False

    source_text = core.normalise_ws(f"{title} {body}")
    if len(source_text) < 80:
        return False

    for article in _iter_existing_articles(existing_by_story):
        if not (article.get("live_story") or article.get("is_ongoing")):
            continue
        if _canonical_url(article.get("source_url", "")) != candidate_url:
            continue

        existing_text = _article_public_text(article)
        if not existing_text:
            return True

        existing_lower = existing_text.casefold()

        source_names = {name.casefold() for name in LIVE_NAME_RE.findall(source_text)}
        existing_names = {name.casefold() for name in LIVE_NAME_RE.findall(existing_text)}
        if source_names - existing_names:
            return True

        source_material = {match.group(0).casefold() for match in LIVE_MATERIAL_RE.finditer(source_text)}
        existing_material = {match.group(0).casefold() for match in LIVE_MATERIAL_RE.finditer(existing_text)}
        if source_material - existing_material:
            return True

        source_numbers = {match.group(0).casefold() for match in LIVE_NUMBER_RE.finditer(source_text)}
        existing_numbers = {match.group(0).casefold() for match in LIVE_NUMBER_RE.finditer(existing_text)}
        if source_numbers - existing_numbers:
            return True

        return False

    return False


def configure_editorial_newsworthiness_gate() -> None:
    """Put a newspaper test in front of AI rewrite and any fallback path."""
    original = core.candidate_is_rewrite_eligible

    def newsworthy(candidate, existing_by_story):
        eligible = original(candidate, existing_by_story)
        if not eligible and _same_source_live_update(candidate, existing_by_story):
            core.log.info(
                "LIVE same-source material update bypassed duplicate rejection: %s",
                getattr(candidate, "source_url", ""),
            )
            eligible = True
        if not eligible:
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


def configure_source_resilience(max_age_hours: int) -> None:
    """Keep broken optional integrations from degrading the core newsroom."""
    # GMFRS retired /news-events/news/. Its current official newsroom is /news/.
    # The legacy RSS currently emits malformed XML, so use the authoritative HTML
    # index plus the existing Google News site fallback instead of wasting every
    # run parsing a broken feed.
    core.RSS_SOURCES[:] = [
        source for source in core.RSS_SOURCES
        if source.get("name") != "Greater Manchester Fire and Rescue Service"
    ]
    for source in core.DISCOVERY_PAGES:
        if source.get("name") == "Greater Manchester Fire and Rescue Service":
            source["url"] = "https://manchesterfire.gov.uk/news/"
            source["link_pattern"] = "/news/"
            source["default_category"] = "environment"
            break

    # The half-hour lane already has indexed fallbacks for these organisations.
    # Known-invalid API credentials must not consume its latency budget on every
    # run. The deeper two-hour run keeps testing the integrations and will resume
    # them automatically as soon as the repository secrets/permissions are fixed.
    browser_enabled = os.getenv("BROWSER_RENDER_ENABLED", "true").lower() not in {
        "0", "false", "no", "off"
    }
    if max_age_hours <= 14 and not browser_enabled:
        os.environ["X_BEARER_TOKEN"] = ""
        os.environ["FACEBOOK_PAGE_ACCESS_TOKEN"] = ""
        core.log.info(
            "Fast-news lane: skipping unavailable X/Facebook APIs; indexed fallbacks remain enabled."
        )


def main() -> int:
    # Production policy: ordinary scraped news must be rewritten by OpenAI and
    # pass the newsroom quality/overlap checks. If the rewrite is unavailable
    # or rejected, fail closed rather than publishing source-led copy.
    core.AI_REWRITE_REQUIRED = True

    # Honour the workflow's actual freshness contract. This used to be hard-coded
    # to 72 hours here (and scraper.py also had a seven-day floor), which silently
    # defeated the 14-hour fast-news policy. The permanent archive is unaffected;
    # this value controls discovery eligibility only.
    requested_age = max(1, int(os.getenv("MAX_NEWS_AGE_HOURS", "72")))
    core.MAX_NEWS_AGE_HOURS = requested_age
    configure_source_resilience(requested_age)

    existing = {item.query.casefold().strip() for item in base.PRIORITY_SEARCHES}
    for item in EXTRA_FRESH_SEARCHES:
        if item.query.casefold().strip() not in existing:
            base.PRIORITY_SEARCHES.append(item)
            existing.add(item.query.casefold().strip())

    base.configure()
    # base.configure() may reset core values, so reassert the workflow contract.
    core.MAX_NEWS_AGE_HOURS = requested_age
    configure_editorial_newsworthiness_gate()
    install_live_story_updates()
    result = core.main()
    if result != 0:
        return result

    return reject_publisher_leaks()


if __name__ == "__main__":
    raise SystemExit(main())
