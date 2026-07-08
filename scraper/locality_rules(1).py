"""Rochdale locality validation.

This module deliberately has no third-party dependencies so it can be tested
before the main scraper imports Feedparser, Playwright, OpenAI or BeautifulSoup.
"""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import urlparse

SOURCE_DENY_DOMAINS = {"rochdaletimes.co.uk"}
SOURCE_DENY_NAMES = {"rochdale times", "rochdale times paper"}

TRUSTED_LOCAL_SOURCE_PREFIXES = (
    "Rochdale Borough Council",
    "Rochdale Council",
    "Rochdale AFC",
    "Rochdale Hornets",
    "Rochdale Development Agency",
    "Rochdale Town Hall",
    "Rochdale Police",
    "Rochdale Online",
    "Roch Valley Radio",
    "Action Together Rochdale",
    "Your Trust Rochdale",
    "Visit Rochdale",
    "Northern Care Alliance Rochdale",
    "Hopwood Hall College",
    "Rochdale Sixth Form College",
    "Facebook Events — Rochdale",
)

TRUSTED_LOCAL_DOMAINS = {
    "rochdale.gov.uk",
    "rochdaleafc.co.uk",
    "rochdalehornets.co.uk",
    "rochdaletownhall.co.uk",
    "rochdaleonline.co.uk",
    "rochvalleyradio.com",
    "actiontogether.org.uk",
    "yourtrustrochdale.co.uk",
    "visitrochdale.com",
    "hopwood.ac.uk",
    "rochdalesfc.ac.uk",
}

# Langley is intentionally absent. It is not accepted as a standalone area.
AREA_KEYWORDS = {
    "darnhill": {"darnhill"},
    "hopwood": {"hopwood"},
    "alkrington": {"alkrington"},
    "boarshaw": {"boarshaw"},
    "newhey": {"newhey"},
    "smithy_bridge": {"smithy bridge"},
    "wardle": {"wardle"},
    "smallbridge": {"smallbridge"},
    "norden": {"norden"},
    "bamford": {"bamford"},
    "cutgate": {"cutgate", "caldershaw"},
    "kirkholt": {"kirkholt"},
    "castleton": {"castleton"},
    "spotland": {"spotland"},
    "falinge": {"falinge"},
    "deeplish": {"deeplish"},
    "balderstone": {"balderstone"},
    "firgrove": {"firgrove"},
    "shawclough": {"shawclough"},
    "healey": {"healey"},
    "syke": {"syke"},
    "wardleworth": {"wardleworth"},
    "sudden": {"sudden"},
    "lowerplace": {"lowerplace"},
    "meanwood": {"meanwood"},
    "littleborough": {"littleborough", "hollingworth lake", "summit"},
    "milnrow": {"milnrow", "slattocks"},
    "heywood": {"heywood"},
    "middleton": {"middleton"},
    "whitworth": {"whitworth"},
    "rochdale": {"rochdale", "rochdale town centre", "town centre"},
}

LOCAL_TERMS = {
    term for terms in AREA_KEYWORDS.values() for term in terms
} | {
    "belfield",
    "buersil",
    "cloverhall",
    "mandale park",
    "birch",
}

# Only Rochdale is strong enough to count without context.
STRONG_DIRECT_TERMS = {"rochdale", "rochdale town centre"}

# Multi-word local names are generally specific enough to count directly.
DIRECT_MULTIWORD_TERMS = {
    term for term in LOCAL_TERMS if " " in term
} - {"town centre"}

# Every single-word locality can also be a surname, business name, artist name,
# ordinary word or a place elsewhere. It therefore needs geographical context.
CONTEXT_REQUIRED_TERMS = {
    term for term in LOCAL_TERMS if " " not in term
} - {"rochdale"}

PLACE_PREFIXES = (
    "in",
    "at",
    "near",
    "around",
    "across",
    "from",
    "within",
    "throughout",
    "towards",
    "toward",
    "outside",
    "serving",
    "based in",
    "located in",
    "residents of",
    "people in",
    "businesses in",
    "schools in",
    "school in",
    "police in",
    "firefighters in",
    "travelling to",
    "roads in",
    "homes in",
    "families in",
)

PLACE_SUFFIXES = (
    "town",
    "town centre",
    "area",
    "ward",
    "estate",
    "village",
    "residents",
    "resident",
    "community",
    "council",
    "borough",
    "school",
    "college",
    "library",
    "road",
    "street",
    "lane",
    "avenue",
    "park",
    "station",
    "market",
    "police",
    "fire station",
    "hospital",
    "clinic",
    "businesses",
    "business",
    "shops",
    "shop",
    "pub",
    "club",
    "team",
    "events",
    "traffic",
    "services",
    "neighbourhood",
    "man",
    "woman",
    "family",
    "families",
    "councillor",
    "flooding",
    "flood alert",
    "roadworks",
)

TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


def normalise_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = TAG_RE.sub(" ", text)
    return SPACE_RE.sub(" ", text).strip()


def domain_of(url: str) -> str:
    host = (urlparse(str(url or "")).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def source_is_denied(source_name: str = "", source_url: str = "") -> bool:
    name = normalise_text(source_name).lower()
    domain = domain_of(source_url)
    return domain in SOURCE_DENY_DOMAINS or any(
        denied in name for denied in SOURCE_DENY_NAMES
    )


def source_is_trusted_local(source_name: str = "", source_url: str = "") -> bool:
    if source_is_denied(source_name, source_url):
        return False
    name = normalise_text(source_name)
    return name.startswith(TRUSTED_LOCAL_SOURCE_PREFIXES) or (
        domain_of(source_url) in TRUSTED_LOCAL_DOMAINS
    )


def term_pattern(term: str) -> str:
    return rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])"


def contains_term(text: str, term: str) -> bool:
    return bool(re.search(term_pattern(term), text, flags=re.IGNORECASE))


def has_geographical_context(text: str, term: str) -> bool:
    escaped_term = term_pattern(term)
    prefixes = "|".join(
        re.escape(prefix) for prefix in sorted(PLACE_PREFIXES, key=len, reverse=True)
    )
    suffixes = "|".join(
        re.escape(suffix) for suffix in sorted(PLACE_SUFFIXES, key=len, reverse=True)
    )

    patterns = (
        rf"\b(?:{prefixes})\s+(?:the\s+)?{escaped_term}",
        rf"{escaped_term}(?:'s)?\s+(?:{suffixes})\b",
        rf"{escaped_term}\s*,\s*(?:Rochdale|Greater Manchester)\b",
        rf"{escaped_term}.{{0,80}}\b(?:OL|M)\d{{1,2}}\s*\d[A-Z]{{2}}\b",
    )
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def locality_evidence(
    text: str,
    source_name: str = "",
    source_url: str = "",
) -> dict[str, Any]:
    plain = normalise_text(text)
    evidence: list[str] = []
    score = 0

    if source_is_denied(source_name, source_url):
        return {"local": False, "score": 0, "evidence": ["denied-source"]}

    if source_is_trusted_local(source_name, source_url):
        score += 5
        evidence.append("trusted-local-source")

    for term in STRONG_DIRECT_TERMS:
        if contains_term(plain, term):
            score += 5
            evidence.append(f"strong-place:{term}")

    for term in sorted(DIRECT_MULTIWORD_TERMS, key=len, reverse=True):
        if contains_term(plain, term):
            score += 3
            evidence.append(f"specific-place:{term}")

    for term in sorted(CONTEXT_REQUIRED_TERMS, key=len, reverse=True):
        if has_geographical_context(plain, term):
            score += 2
            evidence.append(f"contextual-place:{term}")

    return {
        "local": score >= 2,
        "score": score,
        "evidence": evidence,
    }


def is_local(text: str, source_name: str = "", source_url: str = "") -> bool:
    return bool(locality_evidence(text, source_name, source_url)["local"])


def detect_area(
    text: str,
    fallback: str = "",
    source_name: str = "",
    source_url: str = "",
) -> str:
    """Return a proven Rochdale-area location, otherwise an empty string.

    A caller-provided fallback is accepted only for a verified first-party
    Rochdale source. A surname such as Middleton, Wardle or Heywood must never
    become a location merely because the caller supplied "rochdale".
    """
    plain = normalise_text(text)

    # Specific area matching first.
    for area, terms in AREA_KEYWORDS.items():
        if area == "rochdale":
            continue
        for term in sorted(terms, key=len, reverse=True):
            if " " in term:
                if contains_term(plain, term):
                    return area
            elif has_geographical_context(plain, term):
                return area

    if contains_term(plain, "rochdale"):
        return "rochdale"

    if fallback and source_is_trusted_local(source_name, source_url):
        return fallback

    return ""


def article_is_local(article: dict[str, Any]) -> bool:
    text = " ".join(
        str(article.get(field) or "")
        for field in (
            "title",
            "excerpt",
            "summary",
            "content_html",
            "event_location",
        )
    )
    return is_local(
        text,
        str(article.get("source_name") or ""),
        str(article.get("source_url") or ""),
    )
