"""Shared editorial and community-safety blocklist.

story_blocklist.json is the single source of truth for stories the editor
has manually removed. Matching an entry here means a story must never appear
in articles.json, articles/frontpage.json, or as a published article page,
including after push-race merges and after the scraper re-collects the same
story from a different source URL.

This module also applies a temporary community-safety publication block to
stories containing terminology associated with Islam, the Muslim community,
Islamic institutions, religious practices, religious celebrations, or the
Islamic way of life.

This protective measure is intended to reduce the risk of people, families,
places of worship, schools, charities, businesses, and community organisations
being identified or targeted during a period of heightened racism and hostility.

The protective terminology check applies to article titles and candidate-stage
text. It includes direct terms, common spelling variants, religious titles,
places, practices, celebrations, institutions, and related phrases.

Schema for story_blocklist.json (all keys optional):

  {
    "title_patterns": ["henry nowak"],   # lowercase substring match on title
    "source_urls":    ["https://..."],    # canonicalised exact match
    "slugs":          ["some-page-slug"]  # exact slug match, lowercase
  }

frontpage_pipeline.py keeps its own equivalent loader for backwards
compatibility. Its implementation should use the same community-safety
terminology and matching semantics as this module.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit


BLOCKLIST_PATH = Path(
    os.getenv("STORY_BLOCKLIST_JSON", "story_blocklist.json")
)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_APOSTROPHE_RE = re.compile(r"[\u2018\u2019\u02bc`´]")


# Temporary community-safety publication block.
#
# Entries must be lowercase. Matching is performed after normalising
# punctuation, apostrophes, whitespace, and common spelling variations.
ISLAMIC_SAFETY_TERMS = frozenset(
    {
        # Faith and identity
        "islam",
        "islamic",
        "muslim",
        "muslims",
        "muslim faith",
        "islamic faith",
        "islamic religion",
        "islamic culture",
        "muslim culture",
        "islamic way of life",
        "muslim way of life",
        "the faith of islam",

        # Places of worship
        "mosque",
        "mosques",
        "masjid",
        "masjids",
        "jamia mosque",
        "central mosque",
        "prayer hall",
        "muslim prayer hall",

        # Religious leaders and scholars
        "imam",
        "imams",
        "mufti",
        "muftis",
        "sheikh",
        "sheikhs",
        "shaykh",
        "shaykhs",
        "maulana",
        "maulanas",
        "moulana",
        "moulvi",
        "alim",
        "aalim",
        "islamic scholar",
        "muslim scholar",

        # Conversion and reversion
        "convert",
        "converts",
        "converted",
        "converting",
        "conversion",
        "revert",
        "reverts",
        "reverted",
        "reverting",
        "reversion",
        "convert to islam",
        "converts to islam",
        "converted to islam",
        "converting to islam",
        "conversion to islam",
        "revert to islam",
        "reverts to islam",
        "reverted to islam",
        "reverting to islam",
        "reversion to islam",
        "embrace islam",
        "embraces islam",
        "embraced islam",
        "accept islam",
        "accepts islam",
        "accepted islam",
        "becomes muslim",
        "became muslim",

        # Scripture and religious texts
        "qur'an",
        "quran",
        "koran",
        "holy qur'an",
        "holy quran",
        "qur'anic",
        "quranic",
        "surah",
        "surahs",
        "ayah",
        "ayahs",
        "ayat",
        "hadith",
        "hadiths",
        "sunnah",
        "tafsir",
        "tafsir class",

        # Holy places and pilgrimage
        "mecca",
        "makkah",
        "medina",
        "madinah",
        "kaaba",
        "ka'bah",
        "hajj",
        "umrah",
        "pilgrimage to mecca",
        "pilgrimage to makkah",
        "pilgrimage to medina",
        "pilgrimage to madinah",

        # Celebrations and religious periods
        "eid",
        "eid mubarak",
        "eid al-fitr",
        "eid ul-fitr",
        "eid al fitr",
        "eid ul fitr",
        "eid al-adha",
        "eid ul-adha",
        "eid al adha",
        "eid ul adha",
        "ramadan",
        "ramadhan",
        "ramazan",
        "laylat al-qadr",
        "laylatul qadr",
        "night of power",
        "islamic new year",
        "hijri new year",
        "mawlid",
        "milad",
        "milad un nabi",
        "ashura",

        # Prayer and worship
        "prayer",
        "prayers",
        "islamic prayer",
        "muslim prayer",
        "salah",
        "salat",
        "namaz",
        "jummah",
        "jumu'ah",
        "juma",
        "friday prayer",
        "friday prayers",
        "taraweeh",
        "tarawih",
        "dua",
        "du'a",
        "dhikr",
        "zikr",
        "wudu",
        "wudhu",
        "ablution",
        "adhan",
        "azan",
        "call to prayer",
        "qibla",
        "shahada",
        "khutbah",
        "khutba",

        # Charity and religious obligations
        "zakat",
        "zakaat",
        "sadaqah",
        "sadaqa",
        "fitrah",
        "fitra",
        "fidya",
        "kaffarah",
        "islamic charity",
        "muslim charity",
        "ramadan appeal",
        "eid appeal",
        "zakat appeal",

        # Food and dietary practices
        "halal",
        "halal food",
        "halal meat",
        "iftar",
        "suhoor",
        "suhur",
        "sehri",
        "fasting",
        "ramadan fast",
        "breaking the fast",

        # Clothing and appearance
        "hijab",
        "hijabs",
        "hijabi",
        "niqab",
        "niqabs",
        "burqa",
        "burqas",
        "abaya",
        "abayas",
        "thobe",
        "thobes",
        "jubba",
        "jilbab",
        "kufi",
        "taqiyah",
        "headscarf",

        # Schools, education, and institutions
        "islamic school",
        "islamic schools",
        "muslim school",
        "muslim schools",
        "madrasa",
        "madrasah",
        "madrasas",
        "madaris",
        "quran school",
        "qur'an school",
        "quran class",
        "qur'an class",
        "islamic studies",
        "islamic education",
        "islamic centre",
        "islamic center",
        "islamic centres",
        "islamic centers",
        "muslim centre",
        "muslim center",
        "muslim centres",
        "muslim centers",
        "islamic institute",
        "islamic academy",
        "islamic foundation",
        "islamic association",
        "muslim association",
        "islamic society",
        "muslim society",
        "islamic charity",
        "muslim charity",
        "islamic organisation",
        "islamic organization",
        "muslim organisation",
        "muslim organization",
        "islamic community",
        "muslim community",
        "islamic communities",
        "muslim communities",
        "islamic community centre",
        "islamic community center",

        # Beliefs, concepts, and commonly used terminology
        "allah",
        "prophet muhammad",
        "prophet mohammed",
        "prophet muhammed",
        "muhammad",
        "mohammed",
        "muhammed",
        "pbuh",
        "peace be upon him",
        "deen",
        "din",
        "iman",
        "ummah",
        "sharia",
        "shariah",
        "fiqh",
        "aqidah",
        "aqeedah",
        "tawhid",
        "tawheed",
        "inshallah",
        "insha'allah",
        "in sha allah",
        "mashallah",
        "masha'allah",
        "ma sha allah",
        "alhamdulillah",
        "subhanallah",
        "assalamu alaikum",
        "as-salamu alaykum",
        "salaam alaikum",
        "jazakallah",
        "jazak allah",
        "bismillah",
        "astaghfirullah",
    }
)


def _plain(value: Any) -> str:
    """Remove HTML tags and collapse repeated whitespace."""
    return _WS_RE.sub(
        " ",
        _TAG_RE.sub(" ", str(value or "")),
    ).strip()


def _normalise_for_matching(value: Any) -> str:
    """Return lowercase text suitable for consistent phrase matching."""
    text = _plain(value).lower()
    text = _APOSTROPHE_RE.sub("'", text)

    # Hyphens are converted to spaces so forms such as eid-al-fitr and
    # eid al fitr are treated consistently.
    text = text.replace("-", " ")

    # Preserve apostrophes used in words such as Qur'an and Jumu'ah,
    # while replacing other punctuation with spaces.
    text = re.sub(r"[^\w\s']", " ", text, flags=re.UNICODE)
    text = text.replace("_", " ")
    text = _WS_RE.sub(" ", text)

    return text.strip(" '")


def _normalised_variants(value: Any) -> set[str]:
    """Produce useful matching variants for apostrophe spellings."""
    normalised = _normalise_for_matching(value)
    if not normalised:
        return set()

    return {
        normalised,
        normalised.replace("'", ""),
        normalised.replace("'", " "),
    }


def _contains_phrase(text: Any, phrase: str) -> bool:
    """Return True when a phrase occurs with word-aware boundaries."""
    text_variants = _normalised_variants(text)
    phrase_variants = _normalised_variants(phrase)

    for normalised_text in text_variants:
        for normalised_phrase in phrase_variants:
            if not normalised_phrase:
                continue

            pattern = (
                r"(?<!\w)"
                + re.escape(normalised_phrase)
                + r"(?!\w)"
            )

            if re.search(pattern, normalised_text, flags=re.IGNORECASE):
                return True

    return False


def contains_islamic_safety_term(*values: Any) -> bool:
    """Return True when any supplied value contains protected terminology."""
    combined = " ".join(_plain(value) for value in values if value)

    if not combined:
        return False

    return any(
        _contains_phrase(combined, term)
        for term in ISLAMIC_SAFETY_TERMS
    )


def matching_islamic_safety_terms(*values: Any) -> list[str]:
    """Return the safety terms found in the supplied values."""
    combined = " ".join(_plain(value) for value in values if value)

    if not combined:
        return []

    return sorted(
        term
        for term in ISLAMIC_SAFETY_TERMS
        if _contains_phrase(combined, term)
    )


def canonical_url(url: str) -> str:
    """Return a stable canonical URL for exact source matching."""
    text = str(url or "").strip()

    if not text:
        return ""

    try:
        parts = urlsplit(text)
    except ValueError:
        return text.lower()

    host = (parts.hostname or "").lower()

    if host.startswith("www."):
        host = host[4:]

    path = parts.path.rstrip("/")

    return urlunsplit(
        (
            parts.scheme.lower() or "https",
            host,
            path,
            "",
            "",
        )
    )


def _clean_string_list(values: Any) -> list[str]:
    """Normalise a JSON list to non-empty lowercase strings."""
    if not isinstance(values, list):
        return []

    return [
        str(value).lower().strip()
        for value in values
        if value and str(value).strip()
    ]


def load_blocklist(path: Path | None = None) -> dict[str, list[str]]:
    """Load the manually maintained editorial blocklist."""
    target = path or BLOCKLIST_PATH

    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}

    if not isinstance(payload, dict):
        payload = {}

    return {
        "title_patterns": _clean_string_list(
            payload.get("title_patterns", [])
        ),
        "source_urls": [
            canonical_url(str(value))
            for value in payload.get("source_urls", [])
            if value and canonical_url(str(value))
        ],
        "slugs": _clean_string_list(
            payload.get("slugs", [])
        ),
    }


def save_blocklist(
    blocklist: dict[str, list[str]],
    path: Path | None = None,
) -> None:
    """Save the manual editorial blocklist in a stable format."""
    target = path or BLOCKLIST_PATH

    payload = {
        "title_patterns": sorted(
            set(
                _clean_string_list(
                    blocklist.get("title_patterns", [])
                )
            )
        ),
        "source_urls": sorted(
            {
                canonical_url(str(value))
                for value in blocklist.get("source_urls", [])
                if value and canonical_url(str(value))
            }
        ),
        "slugs": sorted(
            set(
                _clean_string_list(
                    blocklist.get("slugs", [])
                )
            )
        ),
    }

    target.parent.mkdir(parents=True, exist_ok=True)

    target.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _article_text_values(article: dict[str, Any]) -> Iterable[Any]:
    """Yield article fields checked by the community-safety filter."""
    yield article.get("title")
    yield article.get("headline")
    yield article.get("summary")
    yield article.get("description")
    yield article.get("excerpt")
    yield article.get("body")
    yield article.get("content")
    yield article.get("category")
    yield article.get("event_location")

    tags = article.get("tags")

    if isinstance(tags, list):
        yield from tags
    elif tags:
        yield tags


def is_blocked_article(
    article: dict[str, Any],
    blocklist: dict[str, list[str]],
) -> bool:
    """Return True when an article must not be published.

    The article is blocked when it:

    1. Contains community-safety terminology associated with Islam;
    2. Matches an exact manually blocked slug;
    3. Matches a manually blocked primary or merged source URL; or
    4. Matches a manually blocked title pattern.
    """
    # Backward compatibility: older callers pass a bare list (historically a
    # list of blocked slugs) instead of the current
    # {"slugs": [...], "source_urls": [...], "title_patterns": [...]} shape.
    # Coerce it here so blocklist.get(...) below never raises on a plain
    # list. This does not change what gets blocked for any current caller —
    # load_blocklist() already returns the dict shape.
    if isinstance(blocklist, list):
        blocklist = {"slugs": blocklist}

    if contains_islamic_safety_term(*_article_text_values(article)):
        return True

    title = _plain(article.get("title")).lower()
    slug = str(article.get("slug") or "").lower().strip()

    blocked_slugs = set(blocklist.get("slugs", []))

    if slug and slug in blocked_slugs:
        return True

    blocked_urls = set(blocklist.get("source_urls", []))

    if blocked_urls:
        candidate_urls = {
            canonical_url(
                str(article.get("source_url") or "")
            )
        }

        source_urls = article.get("source_urls") or []

        if isinstance(source_urls, (list, tuple, set)):
            for url in source_urls:
                candidate_urls.add(canonical_url(str(url)))
        elif source_urls:
            candidate_urls.add(canonical_url(str(source_urls)))

        candidate_urls.discard("")

        if candidate_urls & blocked_urls:
            return True

    return any(
        pattern and pattern in title
        for pattern in blocklist.get("title_patterns", [])
    )


def is_blocked_text(
    title: str,
    source_url: str,
    blocklist: dict[str, list[str]],
    *,
    summary: str = "",
    body: str = "",
) -> bool:
    """Candidate-stage publication check for the scraper.

    The optional summary and body parameters allow the scraper to run the
    protective check again after fetching the full source page.
    """
    if isinstance(blocklist, list):
        blocklist = {"slugs": blocklist}

    if contains_islamic_safety_term(title, summary, body):
        return True

    lowered = _plain(title).lower()

    if any(
        pattern and pattern in lowered
        for pattern in blocklist.get("title_patterns", [])
    ):
        return True

    canonical = canonical_url(source_url)

    return (
        bool(canonical)
        and canonical in set(blocklist.get("source_urls", []))
    )
