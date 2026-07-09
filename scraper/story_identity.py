"""Story clustering and de-duplication for Rochdale Daily.

This module deliberately has no third-party dependencies.  It is used twice by
``scraper.py``: first to cluster newly discovered source records, and again to
collapse the existing ``articles.json`` feed with newly rewritten articles.

The matcher uses a strict ordinary threshold plus a guarded "ongoing story"
route.  The guarded route is important for rolling news where publishers use
very different wording for the same underlying development (for example
"repatriate", "deport" and "take back").
"""

from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse, urlunparse

TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
TOKEN_RE = re.compile(r"[a-z0-9]+")
ENTITY_RE = re.compile(
    r"\b(?:[A-Z][a-z][A-Za-z'-]*|[A-Z]{2,})"
    r"(?:\s+(?:[A-Z][a-z][A-Za-z'-]*|[A-Z]{2,})){1,3}\b"
)
PUBLISHER_SUFFIX_RE = re.compile(r"\s+(?:-|–|—|\|)\s+[^-|–—]{2,45}$")

# Precise incident locations are deliberately narrower than the broad article
# ``area`` field.  "Rochdale" alone is not enough to merge two incidents; a
# street, road, named venue or postcode must match.
STREET_LOCATION_RE = re.compile(
    r"\b(?:[A-Z0-9][A-Za-z0-9'’.-]*\s+){1,5}"
    r"(?i:Road|Rd|Street|St|Avenue|Ave|Lane|Ln|Drive|Dr|Close|Way|"
    r"Crescent|Place|Terrace|Gardens|Square|Parade|Boulevard|Grove|"
    r"Court|Hill|Park|Mews)\b"
)
POSTCODE_RE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", re.I)
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|[\r\n]+")

STORY_KEY_VERSION = "v3"
DEFAULT_MATCH_THRESHOLD = 0.72
INCIDENT_FACT_WINDOW_HOURS = 72

LOCALITY_ALIASES = {
    "rochdale": "rochdale",
    "heywood": "heywood",
    "middleton": "middleton",
    "littleborough": "littleborough",
    "milnrow": "milnrow",
    "newhey": "newhey",
    "wardle": "wardle",
    "norden": "norden",
    "castleton": "castleton",
    "kirkholt": "kirkholt",
    "spotland": "spotland",
    "falinge": "falinge",
    "deeplish": "deeplish",
    "whitworth": "whitworth",
}

STOPWORDS = {
    "about", "after", "again", "against", "ahead", "also", "among",
    "another", "around", "because", "before", "being", "between",
    "could", "first", "from", "have", "into", "latest", "local",
    "more", "news", "new", "over", "said", "says", "that", "their",
    "there", "these", "they", "this", "through", "today", "under",
    "update", "updates", "what", "when", "where", "which", "with",
    "would", "will", "likely", "expected", "report", "reports",
    "reported", "reportedly", "breaking", "live", "online", "exclusive",
    "rochdale", "heywood", "middleton", "littleborough", "milnrow",
    "newhey", "wardle", "norden", "castleton", "kirkholt", "spotland",
    "falinge", "deeplish", "greater", "manchester",
}

GENERIC_ENTITIES = {
    "greater manchester",
    "greater manchester police",
    "rochdale daily",
    "rochdale council",
    "rochdale borough council",
    "rochdale afc",
    "rochdale hornets",
    "bee network",
    "national highways",
    "northern care alliance",
    "pennine care",
    "united kingdom",
    "crown oil arena",
    "facebook events",
    "house of commons",
}

# Words which commonly create false two-word "entities" in title case.
ENTITY_VERB_WORDS = {
    "announces", "announced", "backs", "backed", "calls", "called",
    "charges", "charged", "confirms", "confirmed", "declines", "denies",
    "discusses", "faces", "launches", "likely", "opens", "rejects",
    "responds", "says", "signs", "speaks", "wins", "won",
}

AUTHORITATIVE_ACTION_WORDS = {
    "announces", "announced", "confirms", "confirmed", "signs", "signed",
    "launches", "launched", "opens", "opened", "closes", "closed",
    "issues", "issued", "arrests", "arrested", "charges", "charged",
    "wins", "won", "appoints", "appointed", "sentences", "sentenced",
}

FOLLOWUP_WORDS = {
    "interview", "reaction", "discusses", "speaks", "explains", "responds",
    "preview", "gallery", "pictures", "video", "watch", "hear from",
}

CATEGORY_FAMILIES = {
    "traffic": "transport",
    "transport": "transport",
    "crime": "crime",
    "politics": "public-affairs",
    "community": "community",
    "charity": "community",
    "health": "health",
    "education": "education",
    "sport": "sport",
    "events": "events",
    "business": "business",
    "environment": "environment",
    "news": "news",
}

HARD_NEWS_FAMILIES = {"crime", "news", "public-affairs"}

# The replacements below are concepts, not headline-specific exceptions.  They
# let semantically equivalent wording converge before token comparison.
PHRASE_ALIASES: tuple[tuple[re.Pattern[str], str], ...] = (
    # Family-role and emergency wording equivalence.  These are used for
    # matching only; the published wording is never rewritten by this module.
    (re.compile(r"\b(?:mum|mom|mummy|mommy)\b", re.I), " mother "),
    (re.compile(r"\b(?:dad|daddy)\b", re.I), " father "),
    (re.compile(r"\b(?:blaze|blazes)\b", re.I), " fire "),
    (re.compile(r"\bbreak[- ]?in(?:s)?\b", re.I), " burglary "),
    (re.compile(r"\bmugg(?:ed|ing|ings)\b", re.I), " robbery "),
    (
        re.compile(r"\bgrooming[- ]gang\s+(?:ring)?leader\b", re.I),
        " groominggang gangleader ",
    ),
    (re.compile(r"\bgrooming[- ]gangs?\b", re.I), " groominggang "),
    (re.compile(r"\b(?:gang\s+)?ringleader\b|\bgang\s+leader\b", re.I), " gangleader "),
    (re.compile(r"\battempted\s+murder\b", re.I), " attemptedmurder "),
    (re.compile(r"\btrain\s+stabbing\b", re.I), " trainstabbing "),
    (re.compile(r"\bknife\s+attack\b", re.I), " knifeattack "),
    (re.compile(r"\broad\s+traffic\s+(?:collision|crash)\b", re.I), " collision "),
    (
        re.compile(
            r"\b(?:take|takes|taking|accept|accepts|accepted|send|sends|sending)\s+"
            r"(?:(?:him|her|them|the|a|an)\s+)?back\b",
            re.I,
        ),
        " deport ",
    ),
    (re.compile(r"\brepatriat(?:e|es|ed|ing|ion|ions)\b", re.I), " deport "),
    (re.compile(r"\bdeport(?:ation|ations|ed|ing|s)?\b", re.I), " deport "),
    (
        re.compile(
            r"\b(?:refus(?:e|es|ed|ing|al)|reject(?:s|ed|ing|ion)?|"
            r"declin(?:e|es|ed|ing)|won[’']?t|will\s+not)\b",
            re.I,
        ),
        " reject ",
    ),
    (
        re.compile(
            r"\b(?:law|laws|legislation|legal)\s+"
            r"(?:is\s+|to\s+be\s+|could\s+be\s+|will\s+be\s+)?"
            r"(?:chang(?:e|es|ed|ing)|amend(?:ed|ment|ments|ing)?)\b",
            re.I,
        ),
        " lawchange ",
    ),
    (
        re.compile(
            r"\b(?:chang(?:e|es|ed|ing)|amend(?:ed|ment|ments|ing)?)\s+"
            r"(?:the\s+)?(?:law|laws|legislation)\b",
            re.I,
        ),
        " lawchange ",
    ),
)

TOKEN_ALIASES = {
    "arrested": "arrest", "arrests": "arrest", "arresting": "arrest",
    "charged": "charge", "charges": "charge", "charging": "charge",
    "convicted": "convict", "conviction": "convict", "convictions": "convict",
    "sentenced": "sentence", "sentences": "sentence", "sentencing": "sentence",
    "stabbed": "stabbing", "stabs": "stabbing",
    "shot": "shooting", "shoots": "shooting",
    "assaulted": "assault", "assaults": "assault", "attacked": "assault",
    "attacks": "assault", "beaten": "assault", "battered": "assault",
    "robbed": "robbery", "robs": "robbery",
    "burgled": "burglary", "burglaries": "burglary",
    "stolen": "theft", "stole": "theft", "steals": "theft",
    "killed": "kill", "kills": "kill",
    "murdered": "murder", "murders": "murder",
    "died": "death", "dies": "death", "dead": "death",
    "collided": "collision", "crashed": "collision", "crashes": "collision",
    "blaze": "fire", "blazes": "fire", "fires": "fire",
    "hospitalized": "hospitalised", "hospitalization": "hospitalised",
    "closed": "closure", "closes": "closure",
    "opened": "open", "opens": "open",
    "signed": "sign", "signing": "sign", "signs": "sign",
    "appointed": "appoint", "appoints": "appoint",
    "resigned": "resign", "resigns": "resign",
    "released": "release", "releases": "release",
}

ACTION_CONCEPTS = {
    "announce", "appoint", "arrest", "assault", "ban", "burglary", "charge",
    "closure", "collision", "convict", "death", "deport", "deny", "fire",
    "fraud", "investigate", "kill", "kidnap", "lawchange", "murder", "open",
    "reject", "release", "resign", "robbery", "sentence", "shooting", "sign",
    "stabbing", "theft", "trial", "vandalism", "win",
}

# A shared incident concept is required by the structured incident matcher.
# This covers both crimes and non-criminal emergencies such as fires.
INCIDENT_CONCEPTS = {
    "arson", "assault", "attemptedmurder", "burglary", "collision", "death",
    "fire", "fraud", "kidnap", "kill", "knifeattack", "murder", "robbery",
    "shooting", "stabbing", "theft", "trainstabbing", "vandalism",
}

VICTIM_OUTCOME_MARKERS = {
    "assault", "attack", "death", "die", "died", "escape", "escaped",
    "escaping", "fire", "found dead", "hospital", "hospitalised", "hurt",
    "injured", "kill", "killed", "murder", "rescued",
    "robbed", "shot", "stabbing", "stabbed", "treated", "victim",
}

PERPETRATOR_MARKERS = {
    "accused", "arrest", "arrested", "attacker", "charged", "convict",
    "convicted", "jailed", "offender", "perpetrator", "police seek",
    "sentenced", "suspect", "wanted",
}

ETHNICITY_ALIASES = {
    "british pakistani": "pakistani",
    "pakistani": "pakistani",
    "british indian": "indian",
    "indian": "indian",
    "british bangladeshi": "bangladeshi",
    "bangladeshi": "bangladeshi",
    "british chinese": "chinese",
    "chinese": "chinese",
    "british asian": "asian",
    "south asian": "south-asian",
    "east asian": "east-asian",
    "asian": "asian",
    "black": "black",
    "black british": "black",
    "white": "white",
    "white british": "white",
    "mixed race": "mixed",
    "mixed-race": "mixed",
    "middle eastern": "middle-eastern",
    "arab": "arab",
}

STREET_SUFFIX_ALIASES = {
    "rd": "road", "st": "street", "ave": "avenue", "ln": "lane",
    "dr": "drive",
}

# Compound concepts are strong enough to support an ongoing-story match when
# at least one other guarded signal is present.  Two shared compounds are a
# particularly strong subject identity.
STRONG_SUBJECT_CONCEPTS = {
    "groominggang", "gangleader", "attemptedmurder", "trainstabbing",
    "knifeattack",
}

GENERIC_SUBJECT_WORDS = {
    "authority", "authorities", "boss", "case", "court", "council",
    "country", "government", "leader", "man", "men", "minister", "mp",
    "official", "officials", "people", "person", "police", "public",
    "resident", "residents", "service", "services", "story", "woman", "women",
    "mother", "father", "child", "children", "girl", "boy", "victim",
}



def get_value(item: Any, name: str, default: Any = "") -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def normalise_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = TAG_RE.sub(" ", text)
    return SPACE_RE.sub(" ", text).strip()


def strip_publisher_suffix(value: Any) -> str:
    title = normalise_text(value)
    return PUBLISHER_SUFFIX_RE.sub("", title).strip()


def canonicalise_url(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if not parsed.netloc and not parsed.path:
        return ""

    query_parts = []
    for part in parsed.query.split("&"):
        lower = part.lower()
        if part and not lower.startswith(
            ("utm_", "fbclid=", "gclid=", "at_medium=", "at_campaign=")
        ):
            query_parts.append(part)

    return urlunparse((
        parsed.scheme or "https",
        parsed.netloc.lower(),
        parsed.path.rstrip("/"),
        "",
        "&".join(query_parts),
        "",
    ))


def text_fields(item: Any, *, title_only: bool = False) -> list[str]:
    fields = ("source_title", "title") if title_only else (
        "source_title", "title", "source_summary", "summary", "excerpt",
        "source_body_excerpt", "content_html", "event_location",
    )
    values = []
    for field in fields:
        value = get_value(item, field, "")
        if value:
            values.append(normalise_text(value))
    return values


def combined_text(item: Any) -> str:
    return normalise_text(" ".join(text_fields(item)))


def _apply_phrase_aliases(text: str) -> str:
    value = html.unescape(text).replace("’", "'")
    for pattern, replacement in PHRASE_ALIASES:
        value = pattern.sub(replacement, value)
    return value.lower()


def _canonical_token(token: str) -> str:
    token = TOKEN_ALIASES.get(token, token)
    if token in STOPWORDS:
        return ""
    # Very light plural normalisation.  Avoid broad stemming because names and
    # street names are important to local-news identity.
    if len(token) > 5 and token.endswith("ies"):
        token = token[:-3] + "y"
    elif len(token) > 5 and token.endswith("s") and not token.endswith("ss"):
        token = token[:-1]
    return TOKEN_ALIASES.get(token, token)


def concept_sequence_from_text(text: str) -> list[str]:
    aliased = _apply_phrase_aliases(text)
    output: list[str] = []
    for raw in TOKEN_RE.findall(aliased):
        token = _canonical_token(raw)
        if len(token) >= 3 and token:
            output.append(token)
    return output


def title_concept_sequence(item: Any) -> list[str]:
    title = strip_publisher_suffix(
        get_value(item, "source_title", "") or get_value(item, "title", "")
    )
    return concept_sequence_from_text(title)


def title_tokens(item: Any) -> set[str]:
    return set(title_concept_sequence(item))


def content_tokens(item: Any) -> set[str]:
    tokens: set[str] = set()
    for text in text_fields(item):
        tokens.update(concept_sequence_from_text(text))
    return tokens


def title_bigrams(item: Any) -> set[str]:
    sequence = title_concept_sequence(item)
    return {
        f"{left}:{right}"
        for left, right in zip(sequence, sequence[1:])
        if left != right
    }


def action_tokens(item: Any) -> set[str]:
    return content_tokens(item) & ACTION_CONCEPTS


def incident_tokens(item: Any) -> set[str]:
    """Return canonical crime/emergency concepts explicitly present."""
    return content_tokens(item) & INCIDENT_CONCEPTS


def _semantic_sentences(item: Any) -> list[str]:
    sentences: list[str] = []
    for field_text in text_fields(item):
        for sentence in SENTENCE_RE.split(normalise_text(field_text)):
            semantic = _apply_phrase_aliases(sentence).strip().lower()
            if semantic:
                sentences.append(semantic)
    return sentences


def _contains_marker(text: str, markers: set[str]) -> bool:
    return any(marker in text for marker in markers)


def _mask_obvious_perpetrators(text: str) -> str:
    descriptor = r"(?:man|male|woman|female|boy|girl)"
    marker = (
        r"(?:accused|arrested|attacker|charged|convicted|jailed|offender|"
        r"perpetrator|sentenced|suspect|wanted)"
    )
    text = re.sub(
        rf"\b{descriptor}\b\s+(?:was\s+|has\s+been\s+)?{marker}\b",
        " ",
        text,
    )
    text = re.sub(
        rf"\b{marker}\b.{{0,24}}\b{descriptor}\b",
        " ",
        text,
    )
    return text


def victim_genders(item: Any) -> set[str]:
    """Extract explicitly described victim genders without inferring identity.

    Family-role semantics are normalised first, so ``mum`` and ``mother`` both
    become a female-victim signal when they occur with an injury/outcome term.
    """
    genders: set[str] = set()
    female_terms = (
        "mother", "woman", "women", "female", "girl", "daughter", "wife",
        "grandmother",
    )
    male_terms = (
        "father", "man", "men", "male", "boy", "son", "husband",
        "grandfather",
    )

    for sentence in _semantic_sentences(item):
        if not _contains_marker(sentence, VICTIM_OUTCOME_MARKERS):
            continue
        candidate = _mask_obvious_perpetrators(sentence)
        if any(re.search(rf"\b{re.escape(term)}\b", candidate) for term in female_terms):
            genders.add("female")
        if any(re.search(rf"\b{re.escape(term)}\b", candidate) for term in male_terms):
            genders.add("male")
    return genders


def _perpetrator_windows(item: Any) -> list[str]:
    windows: list[str] = []
    for sentence in _semantic_sentences(item):
        for marker in PERPETRATOR_MARKERS:
            start = sentence.find(marker)
            if start < 0:
                continue
            windows.append(sentence[max(0, start - 100): start + len(marker) + 100])
    return windows


def perpetrator_genders(item: Any) -> set[str]:
    genders: set[str] = set()
    for window in _perpetrator_windows(item):
        if re.search(r"\b(?:man|male|boy)\b", window):
            genders.add("male")
        if re.search(r"\b(?:woman|female|girl)\b", window):
            genders.add("female")
    return genders


def perpetrator_ethnicities(item: Any) -> set[str]:
    """Return only explicit ethnicity descriptors; never infer from names."""
    ethnicities: set[str] = set()
    for window in _perpetrator_windows(item):
        for phrase, canonical in ETHNICITY_ALIASES.items():
            if re.search(rf"\b{re.escape(phrase)}\b", window):
                ethnicities.add(canonical)
    return ethnicities


def _normalise_location(value: Any) -> str:
    words = TOKEN_RE.findall(normalise_text(value).lower())
    if not words:
        return ""
    words[-1] = STREET_SUFFIX_ALIASES.get(words[-1], words[-1])
    return " ".join(words)


def precise_locations(item: Any) -> set[str]:
    """Extract street/venue/postcode locations, excluding broad town areas."""
    locations: set[str] = set()
    generic = {
        "rochdale", "rochdale area", "rochdale borough", "greater manchester",
        "heywood", "middleton", "littleborough", "milnrow", "newhey",
        "wardle", "norden", "castleton", "kirkholt", "spotland", "falinge",
        "deeplish",
    }

    for field_text in text_fields(item):
        for match in STREET_LOCATION_RE.findall(field_text):
            location = _normalise_location(match)
            if location and location not in generic:
                locations.add(location)
        for match in POSTCODE_RE.findall(field_text):
            locations.add(SPACE_RE.sub("", match).lower())

    event_location = normalise_text(get_value(item, "event_location", ""))
    if event_location:
        for match in STREET_LOCATION_RE.findall(event_location):
            location = _normalise_location(match)
            if location and location not in generic:
                locations.add(location)
        normalised_event = _normalise_location(event_location)
        if (
            normalised_event
            and normalised_event not in generic
            and len(normalised_event.split()) >= 2
        ):
            locations.add(normalised_event)

    return locations


def incident_locations(item: Any) -> set[str]:
    """Return all explicit incident locations, from streets down to locality.

    A matching named street/postcode remains the strongest signal, but a shared
    explicit locality such as ``Littleborough`` also counts as the same location
    for the user's structured incident rule.  The value must be present in the
    record or its text; a missing area is never silently treated as Rochdale.
    """
    locations = set(precise_locations(item))

    explicit_area = _normalise_location(get_value(item, "area", ""))
    if explicit_area in LOCALITY_ALIASES:
        locations.add(LOCALITY_ALIASES[explicit_area])

    event_location = _normalise_location(get_value(item, "event_location", ""))
    if event_location in LOCALITY_ALIASES:
        locations.add(LOCALITY_ALIASES[event_location])

    haystack = combined_text(item).lower()
    for phrase, canonical in LOCALITY_ALIASES.items():
        if re.search(rf"\b{re.escape(phrase)}\b", haystack):
            locations.add(canonical)

    return locations


def incident_fact_match(left: Any, right: Any) -> bool:
    """Match reports using the user's explicit incident-fact rules.

    Rules:
    * same location + same incident/crime + same victim gender; or
    * same location + same incident/crime + same perpetrator gender and same
      explicitly stated ethnicity.

    ``mum`` and ``mother`` are treated as the same female-victim concept, while
    ``blaze`` and ``fire`` are treated as the same incident concept.  Reports
    must be within 72 hours.  Ethnicity is only read from explicit article text
    and is never inferred from a person's name or image.
    """
    left_date, right_date = _parsed_datetime(left), _parsed_datetime(right)
    if left_date is None or right_date is None:
        return False
    if abs((left_date - right_date).total_seconds()) > INCIDENT_FACT_WINDOW_HOURS * 3600:
        return False

    left_precise = precise_locations(left)
    right_precise = precise_locations(right)
    if left_precise and right_precise:
        # When both reports name a street, venue or postcode, the precise
        # location must match; a shared broad area must not override a conflict.
        shared_locations = left_precise & right_precise
    else:
        shared_locations = incident_locations(left) & incident_locations(right)
    if not shared_locations:
        return False

    shared_incidents = incident_tokens(left) & incident_tokens(right)
    if not shared_incidents:
        return False

    if victim_genders(left) & victim_genders(right):
        return True

    same_perpetrator_gender = perpetrator_genders(left) & perpetrator_genders(right)
    same_explicit_ethnicity = (
        perpetrator_ethnicities(left) & perpetrator_ethnicities(right)
    )
    if same_perpetrator_gender and same_explicit_ethnicity:
        return True

    return False


def subject_tokens(item: Any) -> set[str]:
    tokens = title_tokens(item)
    return {
        token for token in tokens
        if token not in ACTION_CONCEPTS
        and token not in GENERIC_SUBJECT_WORDS
        and token not in STOPWORDS
    }


def named_entities(item: Any) -> set[str]:
    entities: set[str] = set()
    # Analyse fields separately so the end of a headline cannot join the start
    # of an excerpt into a fake entity such as "Leader Pakistan".
    for field_text in text_fields(item):
        for match in ENTITY_RE.findall(field_text):
            entity = normalise_text(match).lower()
            words = entity.split()
            if entity in GENERIC_ENTITIES or len(words) < 2:
                continue
            if all(word in STOPWORDS for word in words):
                continue
            if any(word in ENTITY_VERB_WORDS for word in words):
                continue
            entities.add(entity)
    return entities


def primary_entity(item: Any) -> str:
    entities = named_entities(item)
    if not entities:
        return ""
    text = combined_text(item).lower()
    ranked = sorted(
        entities,
        key=lambda entity: (
            text.count(entity),
            len(entity.split()),
            len(entity),
            entity,
        ),
        reverse=True,
    )
    return ranked[0]


def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _parsed_datetime(item: Any) -> datetime | None:
    raw = (
        get_value(item, "event_start_at", "")
        or get_value(item, "published_at", "")
        or get_value(item, "source_published_at", "")
    )
    try:
        value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def date_key(item: Any) -> str:
    value = _parsed_datetime(item)
    return value.date().isoformat() if value else ""


def hours_apart(left: Any, right: Any) -> float:
    first, second = _parsed_datetime(left), _parsed_datetime(right)
    if first is None or second is None:
        return 0.0
    return abs((first - second).total_seconds()) / 3600


def category_family(item: Any) -> str:
    category = str(
        get_value(item, "category", "")
        or (
            (get_value(item, "types", []) or ["news"])[0]
            if isinstance(get_value(item, "types", []), list)
            else "news"
        )
        or "news"
    ).lower()
    return CATEGORY_FAMILIES.get(category, category)


def family_key(item: Any) -> str:
    family = category_family(item)
    return "hard-news" if family in HARD_NEWS_FAMILIES else family


def categories_compatible(left: Any, right: Any) -> bool:
    left_family = category_family(left)
    right_family = category_family(right)
    return (
        left_family == right_family
        or {left_family, right_family} <= HARD_NEWS_FAMILIES
    )


def area_key(item: Any) -> str:
    return str(get_value(item, "area", "") or "rochdale").lower()


def areas_compatible(left: Any, right: Any) -> bool:
    left_area, right_area = area_key(left), area_key(right)
    return left_area == right_area or "rochdale" in {left_area, right_area}


def story_window_hours(left: Any, right: Any) -> float:
    families = {category_family(left), category_family(right)}
    if families <= HARD_NEWS_FAMILIES:
        return 14 * 24
    if families == {"events"}:
        return 60 * 24
    if families <= {"transport"}:
        return 48
    if families <= {"sport"}:
        return 7 * 24
    return 7 * 24


def _shared_person_or_named_entity(left: Any, right: Any) -> bool:
    shared = named_entities(left) & named_entities(right)
    return bool(shared)


def ongoing_story_match(left: Any, right: Any) -> bool:
    """Guarded low-threshold route for differently worded updates.

    It never runs across incompatible sections, distant dates or unrelated
    areas.  It then requires either a shared named entity or a strong compound
    subject plus corroborating subject/action overlap.
    """
    if not categories_compatible(left, right):
        return False
    if not areas_compatible(left, right):
        return False
    if hours_apart(left, right) > story_window_hours(left, right):
        return False

    # Structured incident facts override a weak headline similarity score.
    # This is what combines, for example, "mum" and "mother" reports about
    # the same fire on the same named road.
    if incident_fact_match(left, right):
        return True

    left_title, right_title = title_tokens(left), title_tokens(right)
    shared_title = left_title & right_title
    title_score = jaccard(left_title, right_title)

    left_subject, right_subject = subject_tokens(left), subject_tokens(right)
    shared_subject = left_subject & right_subject
    shared_strong = shared_subject & STRONG_SUBJECT_CONCEPTS
    shared_actions = action_tokens(left) & action_tokens(right)
    shared_bigrams = title_bigrams(left) & title_bigrams(right)

    if _shared_person_or_named_entity(left, right):
        if shared_actions or len(shared_title) >= 2 or title_score >= 0.22:
            return True

    # Two exact compound subjects identify the same underlying case even when
    # one source concentrates on a law change and another on a foreign state's
    # refusal.  This is the route used by the grooming-gang deportation cluster.
    if len(shared_strong) >= 2:
        return True

    if shared_strong and len(shared_subject) >= 2 and (
        shared_actions or len(shared_title) >= 3 or shared_bigrams
    ):
        return True

    if len(shared_title) >= 4 and title_score >= 0.42:
        return True

    smaller = min(len(left_title), len(right_title))
    if smaller >= 5 and len(shared_title) / smaller >= 0.72:
        return True

    return False


def story_similarity(left: Any, right: Any) -> float:
    left_url = canonicalise_url(
        get_value(left, "source_url", "") or get_value(left, "url", "")
    )
    right_url = canonicalise_url(
        get_value(right, "source_url", "") or get_value(right, "url", "")
    )
    if left_url and right_url and left_url == right_url:
        return 1.0

    if not categories_compatible(left, right):
        return 0.0
    if not areas_compatible(left, right):
        return 0.0
    if hours_apart(left, right) > story_window_hours(left, right):
        return 0.0

    score = 0.0

    left_entities = named_entities(left)
    right_entities = named_entities(right)
    shared_entities = left_entities & right_entities
    if shared_entities:
        score += 0.34
        score += min(0.12, 0.04 * (len(shared_entities) - 1))

    left_title, right_title = title_tokens(left), title_tokens(right)
    title_score = jaccard(left_title, right_title)
    score += title_score * 0.45

    left_content, right_content = content_tokens(left), content_tokens(right)
    content_score = jaccard(left_content, right_content)
    score += min(0.22, content_score * 0.32)

    left_subject, right_subject = subject_tokens(left), subject_tokens(right)
    shared_subject = left_subject & right_subject
    if shared_subject:
        score += min(0.24, 0.08 * len(shared_subject))
    if shared_subject & STRONG_SUBJECT_CONCEPTS:
        score += 0.12

    shared_actions = action_tokens(left) & action_tokens(right)
    if shared_actions:
        score += min(0.12, 0.06 * len(shared_actions))

    if title_bigrams(left) & title_bigrams(right):
        score += 0.08

    if area_key(left) == area_key(right):
        score += 0.05

    left_source = str(get_value(left, "source_name", "")).lower()
    right_source = str(get_value(right, "source_name", "")).lower()
    if left_source and left_source == right_source:
        score += 0.05

    left_event = str(get_value(left, "event_start_at", "") or "")
    right_event = str(get_value(right, "event_start_at", "") or "")
    if left_event and right_event and date_key(left) == date_key(right):
        score += 0.42

    if ongoing_story_match(left, right):
        score = max(score, 0.78)

    return min(score, 1.0)


def same_story(left: Any, right: Any) -> bool:
    return story_similarity(left, right) >= DEFAULT_MATCH_THRESHOLD


def authority_score(item: Any) -> float:
    title = strip_publisher_suffix(
        get_value(item, "source_title", "") or get_value(item, "title", "")
    ).lower()
    body_length = len(combined_text(item))
    score = min(body_length / 3000, 1.0)

    if any(word in title for word in AUTHORITATIVE_ACTION_WORDS):
        score += 0.7
    if any(word in title for word in FOLLOWUP_WORDS):
        score -= 0.35

    source = str(get_value(item, "source_name", "")).lower()
    if any(marker in source for marker in (
        "council", "police", "gmp", "fire", "nhs", "tfgm",
        "rochdale afc", "rochdale hornets", "environment agency",
    )):
        score += 0.35

    return score


def _date_bucket(item: Any) -> str:
    value = _parsed_datetime(item)
    if not value:
        return "undated"
    family = category_family(item)
    if family == "events":
        return value.date().isoformat()
    if family in HARD_NEWS_FAMILIES:
        iso_year, iso_week, _ = value.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    return value.date().isoformat()


def _story_subject_parts(item: Any) -> list[str]:
    subjects = subject_tokens(item)
    strong = sorted(subjects & STRONG_SUBJECT_CONCEPTS)
    if strong:
        # Compound case identifiers should dominate volatile action wording.
        return strong[:3]

    entity = primary_entity(item)
    if entity:
        return [entity]

    ranked = sorted(subjects, key=lambda token: (-len(token), token))
    if ranked:
        return ranked[:4]

    fallback = sorted(title_tokens(item) - ACTION_CONCEPTS)
    return fallback[:4]


def build_story_key(item: Any) -> str:
    """Build a fresh semantic key.

    Legacy ``story_key`` values are intentionally ignored.  Recomputing them on
    every run is what allows an existing feed containing several old duplicate
    keys to heal itself after this module is deployed.
    """
    family = family_key(item)
    area = area_key(item)
    bucket = _date_bucket(item)
    subject_parts = _story_subject_parts(item)
    subject = "|".join(subject_parts) or canonicalise_url(
        get_value(item, "source_url", "")
    )
    raw = f"{STORY_KEY_VERSION}|{family}|{area}|{bucket}|{subject}".lower()
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    return f"{family}-{STORY_KEY_VERSION}-{digest}"


def source_pairs(item: Any) -> list[tuple[str, str]]:
    names = get_value(item, "source_names", []) or []
    urls = get_value(item, "source_urls", []) or []
    pairs: list[tuple[str, str]] = []

    primary_name = str(get_value(item, "source_name", "") or "")
    primary_url = str(get_value(item, "source_url", "") or "")
    if primary_url:
        pairs.append((primary_name, primary_url))

    if isinstance(urls, list):
        for index, url in enumerate(urls):
            if not url:
                continue
            name = names[index] if isinstance(names, list) and index < len(names) else ""
            pairs.append((str(name or ""), str(url)))

    seen: set[str] = set()
    unique: list[tuple[str, str]] = []
    for name, url in pairs:
        canonical = canonicalise_url(url)
        if not canonical or canonical in seen:
            continue
        seen.add(canonical)
        unique.append((name, url))
    return unique


def _record_datetime(item: dict[str, Any], *fields: str) -> datetime | None:
    for field in fields:
        raw = item.get(field)
        if not raw:
            continue
        try:
            value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        except (TypeError, ValueError):
            continue
    return None


def _iso_or_empty(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _choose_preferred_record(
    left: dict[str, Any], right: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    left_authority, right_authority = authority_score(left), authority_score(right)
    left_date = _record_datetime(left, "published_at", "source_published_at")
    right_date = _record_datetime(right, "published_at", "source_published_at")

    # Prefer a genuinely newer update unless it is substantially weaker than
    # the existing article.  This keeps the ongoing story current without
    # replacing a sourced full article with a thin aggregator fallback.
    if left_date and right_date:
        if right_date > left_date and right_authority >= left_authority - 0.35:
            return right, left
        if left_date > right_date and left_authority >= right_authority - 0.35:
            return left, right

    if right_authority > left_authority:
        return right, left
    return left, right


def merge_article_records(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    preferred, other = _choose_preferred_record(left, right)
    merged = dict(preferred)

    # Preserve the already-published canonical URL/id where possible, while
    # allowing the headline and body to be refreshed from a newer update.
    for field in ("id", "slug"):
        if left.get(field):
            merged[field] = left[field]

    if merged.get("title"):
        merged["title"] = strip_publisher_suffix(merged["title"])

    pairs = source_pairs(preferred) + source_pairs(other)
    seen: set[str] = set()
    unique_pairs: list[tuple[str, str]] = []
    for name, url in pairs:
        canonical = canonicalise_url(url)
        if not canonical or canonical in seen:
            continue
        seen.add(canonical)
        unique_pairs.append((name, url))

    merged["source_names"] = [name for name, _ in unique_pairs]
    merged["source_urls"] = [url for _, url in unique_pairs]
    merged["source_count"] = len(unique_pairs)

    preferred_url = str(preferred.get("source_url") or "")
    preferred_canonical = canonicalise_url(preferred_url)
    primary_pair = next(
        (
            pair for pair in unique_pairs
            if canonicalise_url(pair[1]) == preferred_canonical
        ),
        unique_pairs[0] if unique_pairs else ("", ""),
    )
    if primary_pair[1]:
        merged["source_name"], merged["source_url"] = primary_pair

    dates = [
        value for value in (
            _record_datetime(left, "first_published_at", "published_at"),
            _record_datetime(right, "first_published_at", "published_at"),
        )
        if value is not None
    ]
    latest_dates = [
        value for value in (
            _record_datetime(left, "published_at"),
            _record_datetime(right, "published_at"),
        )
        if value is not None
    ]
    update_dates = [
        value for value in (
            _record_datetime(left, "last_updated_at", "scraped_at", "published_at"),
            _record_datetime(right, "last_updated_at", "scraped_at", "published_at"),
        )
        if value is not None
    ]

    if dates:
        merged["first_published_at"] = _iso_or_empty(min(dates))
    if latest_dates:
        merged["published_at"] = _iso_or_empty(max(latest_dates))
    if update_dates:
        merged["last_updated_at"] = _iso_or_empty(max(update_dates))

    is_ongoing = len(unique_pairs) > 1 or bool(
        left.get("is_ongoing") or right.get("is_ongoing")
    )
    merged["is_ongoing"] = is_ongoing
    merged["ongoing_label"] = "ONGOING" if is_ongoing else ""
    merged["update_count"] = max(
        len(unique_pairs),
        int(left.get("update_count") or 1),
        int(right.get("update_count") or 1),
    )

    if (
        str(left.get("category") or "").lower() == "crime"
        or str(right.get("category") or "").lower() == "crime"
        or left.get("police_matter")
        or right.get("police_matter")
    ):
        merged["category"] = "crime"
        merged["types"] = ["crime"]
        merged["police_matter"] = True
        merged["requires_approval"] = False

    # Recompute after category and preferred content have been settled.
    merged["story_key"] = build_story_key(merged)
    return merged


def dedupe_article_records(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse records using connected components rather than one representative.

    Connected components make clustering transitive: if A matches B and B
    matches C, all three are combined even when A and C use very different
    wording.  The feed is small enough that the O(n²) comparison is harmless.
    """
    records = [dict(item) for item in items]
    for record in records:
        record["story_key"] = build_story_key(record)

    count = len(records)
    parent = list(range(count))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left_index: int, right_index: int) -> None:
        left_root, right_root = find(left_index), find(right_index)
        if left_root != right_root:
            parent[right_root] = left_root

    for left_index in range(count):
        for right_index in range(left_index + 1, count):
            left = records[left_index]
            right = records[right_index]
            if (
                left["story_key"] == right["story_key"]
                or same_story(left, right)
            ):
                union(left_index, right_index)

    groups: dict[int, list[int]] = {}
    for index in range(count):
        groups.setdefault(find(index), []).append(index)

    output: list[dict[str, Any]] = []
    for indices in groups.values():
        merged = records[indices[0]]
        for index in indices[1:]:
            merged = merge_article_records(merged, records[index])
        merged["story_key"] = build_story_key(merged)
        output.append(merged)

    return output
