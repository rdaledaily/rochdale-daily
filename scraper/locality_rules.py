"""Rochdale locality validation.

This module deliberately has no third-party dependencies so it can be tested
before the main scraper imports Feedparser, Playwright, OpenAI or BeautifulSoup.

Scoring model
-------------
Positive evidence:
  +5  trusted first-party Rochdale source
  +5  strong direct term ("rochdale", "rochdale town centre")
  +3  specific multi-word local place ("hollingworth lake", "smithy bridge")
  +2  ambiguous single-word local place WITH geographical context
      ("in Norden", "Wardle village") — for a known Greater Manchester
      publisher, or when stronger evidence already anchors the article
  +1  the same contextual match from an UNKNOWN publisher: a lone
      ambiguous borough name never establishes locality for the open
      long tail ("in Middleton" is what Middleton, Nova Scotia says too),
      but two independent borough names together still can.
An article is local when the score reaches 2.

Negative evidence (new):
  1. Per-term impostors. Every ambiguous single-word locality has namesakes
     elsewhere in the country (Norden in Dorset, Norden Farm in Maidenhead,
     Castleton and Bamford in the Peak District, Meanwood in Leeds, ...).
     When an article mentions the known rival context for a term, that term
     contributes NOTHING — neither to the locality score nor to detect_area().
  2. Rival geography veto. When the ONLY positive evidence is contextual
     ambiguous terms (no trusted source, no "rochdale", no specific
     multi-word local place) AND the article, its source name or its source
     domain mentions clearly non-local geography — a distant county, a major
     city outside Greater Manchester, or a postcode outside the borough's
     OL / M / BL areas — the article is rejected.

A genuine Rochdale mention or a trusted first-party source always outranks
rival geography: "A Rochdale man was jailed at Dorchester Crown Court" is
still local news.
"""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import urlparse

SOURCE_DENY_DOMAINS = {
    "rochdaletimes.co.uk",
    "rochdaleonline.co.uk",
    # SEO advertorial, not journalism ("Middleton residents can access
    # local and emergency plumbing services").
    "manchesterplumbers.com",
    # Property classifieds: a "House Rental Available at 1308 Shirley
    # Street, Middleton" listing (Middleton, US) published as local news.
    "apartments.com",
    # Scraper-spam subdomain that laundered a US "Montgomery County /
    # Middleton arson" story into Google News results.
    "presonus.com",
}
SOURCE_DENY_NAMES = {"rochdale times", "rochdale times paper", "rochdale online"}

TRUSTED_LOCAL_SOURCE_PREFIXES = (
    "Rochdale Borough Council",
    "Rochdale Council",
    "Rochdale AFC",
    "Rochdale Hornets",
    "Rochdale Development Agency",
    "Rochdale Town Hall",
    "Rochdale Police",
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
    "rochvalleyradio.com",
    "actiontogether.org.uk",
    "yourtrustrochdale.co.uk",
    "visitrochdale.com",
    "hopwood.ac.uk",
    "rochdalesfc.ac.uk",
}

# ---------------------------------------------------------------------------
# Known Greater Manchester publishers. Not first-party Rochdale sources, but
# outlets whose "Middleton", "Heywood" or "Norden" reliably means the
# Greater Manchester place. For everyone else — the open long tail arriving
# through Google News with publisher identities like "x.com", "Source" or a
# spam subdomain — an ambiguous single-word borough name alone must never
# establish locality, however geographically it is phrased: "in Middleton"
# is exactly what a Middleton, Nova Scotia story says too.
# ---------------------------------------------------------------------------
KNOWN_GM_PUBLISHER_DOMAINS = {
    "manchestereveningnews.co.uk",
    "bbc.co.uk",
    "bbc.com",
    "gmp.police.uk",
    "manchesterfire.gov.uk",
    "aboutmanchester.co.uk",
    "tfgm.com",
    "greatermanchester-ca.gov.uk",
    "northernrailway.co.uk",
    "nationalhighways.co.uk",
    "unitedutilities.com",
    "northerncarealliance.nhs.uk",
    "penninecare.nhs.uk",
    "rbh.org.uk",
    "rochdaleriverside.com",
    "environment.data.gov.uk",
    "itv.com",
}
KNOWN_GM_PUBLISHER_NAME_PREFIXES = (
    "BBC Manchester",
    "Manchester Evening News",
    "Greater Manchester Police",
    "Greater Manchester Fire",
    "About Manchester",
    "TfGM",
    "Bee Network",
    "GMCA",
    "Northern",
    "National Highways",
    "United Utilities",
    "Environment Agency",
    "Northern Care Alliance",
    "Pennine Care",
    "Rochdale Boroughwide Housing",
    # Google News truncates "Your Trust Rochdale" to "Your Trust".
    "Your Trust",
)


def source_is_known_gm_publisher(source_name: str = "", source_url: str = "") -> bool:
    domain = domain_of(source_url)
    if domain in KNOWN_GM_PUBLISHER_DOMAINS:
        return True
    # Every school in the borough publishes under *.rochdale.sch.uk
    # (a live Norden environmental story from stedwardsce.rochdale.sch.uk
    # was rejected as an unknown publisher).
    if domain.endswith("rochdale.sch.uk"):
        return True
    name = normalise_text(source_name)
    # Google News often supplies the publisher's bare domain as the entry's
    # source NAME while the URL is a news.google.com redirect, so the name
    # must be checked as a domain too.
    name_as_domain = name.lower().strip().lstrip("www.")
    if name_as_domain in KNOWN_GM_PUBLISHER_DOMAINS or name_as_domain.endswith("rochdale.sch.uk"):
        return True
    return name.startswith(KNOWN_GM_PUBLISHER_NAME_PREFIXES)

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
    # Distinctive multiword borough anchors. "Heywood Old Road in
    # Middleton" is the real A6045 through Middleton, and Meanwood
    # Community Nursery and Primary School is the borough's own school in
    # the Meanwood estate; both were rejected as unanchored ambiguous
    # names when they arrived from unknown publishers.
    "heywood old road",
    "meanwood community nursery",
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

# Borough names with well-known namesake places elsewhere. With geographical
# context these still read as places — but "in Middleton" is also what a
# Middleton, Nova Scotia story says, so for UNKNOWN publishers these terms
# carry half weight and cannot establish locality alone (see
# locality_evidence). Distinctive names such as Heywood, Kirkholt, Falinge
# and Spotland are deliberately absent and keep full weight.
HEAVY_NAMESAKE_TERMS = {
    "middleton", "norden", "bamford", "castleton", "healey", "wardle",
    "hopwood", "meanwood", "birch", "summit", "syke", "sudden",
}

# ---------------------------------------------------------------------------
# Negative evidence: known namesakes of each ambiguous local term.
#
# If any of these context terms appears anywhere in the article (or its source
# name / source domain), the associated local term is treated as referring to
# the OTHER place and is fully disqualified for this article.
#
# Live false positives that motivated this table:
#   - "collision near Norden" published from Swanage News (Norden, Dorset,
#     on the Swanage Railway near Corfe Castle).
#   - "Lightnin' Willie ... at Norden Farm Centre for the Arts" (Maidenhead,
#     Berkshire) — the body even said Maidenhead.
# ---------------------------------------------------------------------------
TERM_IMPOSTOR_CONTEXTS: dict[str, set[str]] = {
    "norden": {
        "swanage", "corfe castle", "purbeck", "wareham", "dorset",
        "swanage railway", "norden farm", "maidenhead", "berkshire",
    },
    "middleton": {
        "teesdale", "county durham", "leeds", "north yorkshire",
        "middleton-on-sea", "middleton stoney", "middleton st george",
        # Middleton, Nova Scotia (Annapolis Valley, on Highway 101 near
        # Kingston NS): a fatal-crash story about its residents published
        # as borough news. Middleton also exists in Idaho and Wisconsin,
        # and a US "Montgomery County / Middleton" arson case reached the
        # live site the same week.
        "nova scotia", "annapolis", "kingston", "ontario",
        "montgomery county", "idaho", "wisconsin",
        # Middleton, Idaho sits in the Treasure Valley; a robbery story
        # naming Boise and Nampa scored contextual Middleton on the live
        # site without ever using the word "Idaho".
        "boise", "nampa", "kuna", "meridian", "caldwell", "treasure valley",
    },
    "castleton": {
        "derbyshire", "hope valley", "peak district", "blue john",
        "buxton", "whitby", "north yorkshire", "vermont",
    },
    "bamford": {
        "derbyshire", "hope valley", "peak district", "bamford edge",
    },
    "healey": {
        # Healey Ford / Healey Brothers: a Ford dealership group in New
        # York's Hudson Valley (Goshen, Poughkeepsie). A Facebook sales
        # post was published as a Rochdale story with the rewrite
        # asserting "a car dealership in Healey".
        "healey ford", "healey brothers", "goshen", "poughkeepsie",
        "hudson valley", "new york",
    },
    "heywood": {"wiltshire", "westbury"},
    "wardle": {"cheshire", "nantwich"},
    "hopwood": {"worcestershire", "hopwood park", "m42"},
    "meanwood": {"leeds"},
    "whitworth": {
        "whitworth art gallery", "whitworth street", "whitworth park",
        "spennymoor", "county durham",
    },
    "littleborough": {"nottinghamshire"},
    "smallbridge": {"suffolk"},
    "birch": {"essex", "colchester"},
}

# ---------------------------------------------------------------------------
# Negative evidence: clearly non-local geography.
#
# Deliberately conservative. It contains distant counties and major cities,
# NOT Greater Manchester boroughs, Lancashire (Whitworth sits in Rossendale)
# or generic words. It only ever vetoes an article whose sole positive
# evidence is an ambiguous single-word term; it can never override a genuine
# "rochdale" mention, a specific multi-word local place or a trusted source.
#
# Single-word rival terms are themselves ambiguous ("Devon" is a first name,
# "Kent" a surname, "Hull" a noun), so in article text they only count when
# they carry geographic context of their own ("in Devon", "Wardle, Cheshire").
# A rival term in the SOURCE name or domain ("Swanage News", "Leeds Homes")
# always counts directly. "Reading" is intentionally absent: it is far more
# often the gerund than the town, and even a context check cannot separate
# "participate in reading activities" from "in Reading".
# ---------------------------------------------------------------------------
RIVAL_GEOGRAPHY_TERMS = {
    # Counties well away from the borough.
    "dorset", "berkshire", "wiltshire", "hampshire", "surrey", "sussex",
    "kent", "essex", "norfolk", "suffolk", "cornwall", "devon", "somerset",
    "derbyshire", "leicestershire", "northamptonshire", "oxfordshire",
    "buckinghamshire", "hertfordshire", "cambridgeshire", "lincolnshire",
    "worcestershire", "gloucestershire", "shropshire", "warwickshire",
    "county durham", "northumberland", "cumbria", "teesdale",
    # Major cities and towns outside Greater Manchester, plus the towns tied
    # to the impostor table above.
    "london", "birmingham", "leeds", "sheffield", "liverpool", "bristol",
    "nottingham", "leicester", "coventry", "newcastle upon tyne",
    "sunderland", "plymouth", "southampton", "portsmouth", "brighton",
    "york", "hull", "cardiff", "swansea", "glasgow", "edinburgh",
    "aberdeen", "dundee", "belfast", "dublin",
    "maidenhead", "swanage", "wareham", "poole", "bournemouth",
    "dorchester", "corfe castle", "purbeck", "buxton", "matlock",
    "hope valley", "peak district", "milton keynes", "slough",
    # United States and other countries. A live example: a Castleton,
    # Vermont community Facebook page supplied wrestling clinics and pet
    # adoptions that published as Castleton, Rochdale. Single-word states
    # still require place context ("in Vermont", "Castleton, Vermont"), so
    # states that double as common personal names (Georgia, Virginia,
    # Washington, Jersey) are deliberately excluded.
    "vermont", "texas", "california", "florida", "ohio", "michigan",
    "arizona", "colorado", "oregon", "montana", "utah", "nevada", "idaho",
    "kansas", "iowa", "maine", "alaska", "hawaii", "nebraska", "wyoming",
    "oklahoma", "kentucky", "tennessee", "missouri", "arkansas",
    "louisiana", "alabama", "mississippi", "delaware", "connecticut",
    "massachusetts", "pennsylvania", "wisconsin", "minnesota", "illinois",
    "indiana", "maryland", "new jersey", "new mexico", "new hampshire",
    "new york", "north carolina", "south carolina", "north dakota",
    "south dakota", "rhode island", "west virginia", "ncaa",
    "united states", "usa", "canada", "australia", "new zealand",
    # Canadian provinces (a Middleton, Nova Scotia fatal-crash story
    # published as borough news), plus North American geography markers
    # that never describe the borough: numbered highways and US-style
    # counties. Multi-word terms count on any mention.
    "nova scotia", "annapolis valley", "new brunswick", "newfoundland",
    "british columbia", "saskatchewan", "manitoba", "alberta", "ontario",
    "quebec", "highway 101", "montgomery county",
}

# Postcode areas that cover the borough of Rochdale and its immediate edges:
# OL (Rochdale, Littleborough, Milnrow, Heywood OL10...), M (Middleton M24),
# BL (the Heywood / Bury boundary). Any other UK postcode area found in the
# text counts as rival geography.
LOCAL_POSTCODE_AREAS = {"OL", "M", "BL"}
POSTCODE_RE = re.compile(r"\b([A-Z]{1,2})\d{1,2}[A-Z]?\s+\d[A-Z]{2}\b")

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

# Matches a capitalised "Firstname Surname" pair anywhere in the text, e.g.
# "Kate Middleton", "David Wardle", "Bill Heywood". Used to detect that an
# ambiguous place term is actually being used as somebody's surname in this
# article, so a later bare mention of the same word ("... message from
# Middleton ...") is not mistaken for a second, independent place reference.
FULL_NAME_RE = re.compile(r"\b[A-Z][a-zA-Z'-]+\s+([A-Z][a-zA-Z'-]+)\b")


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
    # Aggregator links (Google News redirects) hide the real domain in the
    # URL, but the source NAME often carries it — check both.
    return (
        domain in SOURCE_DENY_DOMAINS
        or any(denied in name for denied in SOURCE_DENY_NAMES)
        or any(denied in name for denied in SOURCE_DENY_DOMAINS)
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


def mentioned_as_surname(text: str, term: str) -> bool:
    """True if `term` appears anywhere as the surname half of a capitalised
    "Firstname Surname" pair (e.g. "Kate Middleton", "David Wardle").

    Once an ambiguous local word has been introduced as somebody's surname
    anywhere in an article, later bare mentions of that same word ("a message
    from Middleton", "Wardle's comments") almost always refer back to that
    person, not to the place. Articles are checked as a whole, not sentence
    by sentence, since surnames are commonly introduced once in full and then
    referred to by surname alone for the rest of the piece.
    """
    for match in FULL_NAME_RE.finditer(text):
        surname = match.group(1).lower()
        # Strip a trailing possessive ('s or 's) so "Middleton's" matches
        # the bare term "middleton" rather than being compared as one word.
        surname = re.sub(r"[\u2019']s$", "", surname)
        if surname == term:
            return True
    return False


def term_is_impostor(text: str, term: str) -> bool:
    """True if the article's own wording shows that `term` refers to a
    namesake elsewhere in the country rather than the Rochdale-borough place.

    "Norden Farm Centre for the Arts", "Castleton in the Peak District" and
    "Meanwood, Leeds" are all real cases this catches. The check runs against
    the combined text of the article plus its source name and source domain,
    so an item syndicated from "Swanage News" disqualifies Norden even when
    the article body itself never names Dorset.
    """
    contexts = TERM_IMPOSTOR_CONTEXTS.get(term)
    if not contexts:
        return False
    return any(contains_term(text, context) for context in contexts)


def rival_term_used_as_place(text: str, term: str) -> bool:
    """True when a rival term appears in `text` as a place, not as a name.

    Multi-word rivals ("corfe castle", "peak district") are specific enough
    to count on any mention. Single-word rivals double as first names and
    surnames ("Devon Simmonds-Caines", "Clark Kent"), so they need the same
    kind of geographic context the local terms need: a place preposition
    ("in Devon", "near Nantwich") or a preceding comma in a place list
    ("Meanwood, Leeds", "Heywood, Wiltshire").
    """
    if " " in term:
        return contains_term(text, term)
    escaped_term = term_pattern(term)
    prefixes = "|".join(
        re.escape(prefix) for prefix in sorted(PLACE_PREFIXES, key=len, reverse=True)
    )
    patterns = (
        rf"\b(?:{prefixes})\s+(?:the\s+)?{escaped_term}",
        rf",\s*{escaped_term}",
    )
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def rival_geography_evidence(text: str, source_text: str = "") -> list[str]:
    """Return evidence strings for clearly non-local geography.

    Three kinds of signal: rival place names used as places in the article
    text, rival place names anywhere in the source name or domain, and UK
    postcodes outside the borough's OL / M / BL areas. The caller decides
    whether this evidence matters; it only ever vetoes weak
    (ambiguous-term-only) matches.
    """
    evidence: list[str] = []
    for term in sorted(RIVAL_GEOGRAPHY_TERMS, key=len, reverse=True):
        if rival_term_used_as_place(text, term):
            evidence.append(f"rival-place:{term}")
        elif source_text and contains_term(source_text, term):
            evidence.append(f"rival-source:{term}")
    for match in POSTCODE_RE.finditer(text):
        if match.group(1).upper() not in LOCAL_POSTCODE_AREAS:
            evidence.append(f"rival-postcode:{match.group(0)}")
    return evidence


def has_geographical_context(text: str, term: str) -> bool:
    if term in CONTEXT_REQUIRED_TERMS and mentioned_as_surname(text, term):
        return False

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
    # Impostor and rival checks also see the source name and domain, so a
    # "Swanage News" byline counts against an otherwise bare "near Norden".
    scan_text = " ".join(
        part
        for part in (plain, normalise_text(source_name), domain_of(source_url))
        if part
    )
    evidence: list[str] = []
    score = 0
    anchored = False  # True once evidence stronger than an ambiguous term exists.

    if source_is_denied(source_name, source_url):
        return {"local": False, "score": 0, "evidence": ["denied-source"]}

    if source_is_trusted_local(source_name, source_url):
        score += 5
        anchored = True
        evidence.append("trusted-local-source")

    for term in STRONG_DIRECT_TERMS:
        if contains_term(plain, term):
            score += 5
            anchored = True
            evidence.append(f"strong-place:{term}")

    for term in sorted(DIRECT_MULTIWORD_TERMS, key=len, reverse=True):
        if contains_term(plain, term):
            score += 3
            anchored = True
            evidence.append(f"specific-place:{term}")

    # Structural rule: a HEAVY-NAMESAKE borough name alone never
    # establishes locality for an unknown publisher. "In Middleton" is
    # exactly what a Middleton, Nova Scotia crash report says; "from
    # Middleton" is what a Wisconsin obituary says. For known Greater
    # Manchester publishers, or when stronger evidence already anchors the
    # article, these terms keep their full weight; for the open long tail
    # each scores 1, so a lone heavy-namesake name cannot reach the
    # threshold, while two independent borough names together still can.
    # Distinctive names (Heywood, Kirkholt, Falinge, Spotland...) keep
    # full weight from any publisher: their namesakes are rare, and the
    # per-term impostor tables cover the known ones.
    known_gm = source_is_known_gm_publisher(source_name, source_url)
    for term in sorted(CONTEXT_REQUIRED_TERMS, key=len, reverse=True):
        if not has_geographical_context(plain, term):
            continue
        if term_is_impostor(scan_text, term):
            evidence.append(f"impostor:{term}")
            continue
        if term in HEAVY_NAMESAKE_TERMS and not (anchored or known_gm):
            score += 1
        else:
            score += 2
        evidence.append(f"contextual-place:{term}")

    source_text = " ".join(
        part for part in (normalise_text(source_name), domain_of(source_url)) if part
    )
    rivals = rival_geography_evidence(plain, source_text)
    if rivals and not anchored:
        # The only positive evidence is ambiguous single-word terms, and the
        # article names somewhere else entirely. Treat it as non-local.
        evidence.extend(rivals)
        return {"local": False, "score": 0, "evidence": evidence}

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
    become a location merely because the caller supplied "rochdale", and a
    namesake elsewhere (Norden Farm in Maidenhead, Castleton in Derbyshire)
    must never be tagged as the borough's area of the same name.
    """
    plain = normalise_text(text)
    scan_text = " ".join(
        part
        for part in (plain, normalise_text(source_name), domain_of(source_url))
        if part
    )

    # Specific area matching first.
    for area, terms in AREA_KEYWORDS.items():
        if area == "rochdale":
            continue
        for term in sorted(terms, key=len, reverse=True):
            if term_is_impostor(scan_text, term):
                continue
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


def has_disqualifying_evidence(
    text: str,
    source_name: str = "",
    source_url: str = "",
) -> bool:
    """True when the article shows impostor or rival-geography evidence.

    Weak acceptance paths elsewhere in the pipeline (traffic-desk copy, a
    borough place name appearing in finished text) must never override this:
    the wrong-town articles that motivated the negative-evidence rules all
    mention a borough place name precisely BECAUSE the namesake fooled the
    system. Anchored articles (a genuine Rochdale mention, a specific
    multi-word local place, a trusted source) never report rival evidence,
    so they are never disqualified here.
    """
    evidence = locality_evidence(text, source_name, source_url)["evidence"]
    return any(item.startswith(("impostor:", "rival-", "denied-source")) for item in evidence)


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
