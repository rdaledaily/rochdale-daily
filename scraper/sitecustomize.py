"""Entity-aware Wikimedia Commons query rewriting for image backfill.

Python imports ``sitecustomize`` automatically at startup (unless invoked with
``-S``). The image backfill script imports ``urlencode`` afterwards, so this
hook improves its Commons terms without changing unrelated requests.
"""
from __future__ import annotations

import re
from typing import Any
import urllib.parse

_ORIGINAL_URLENCODE = urllib.parse.urlencode

_BOUNDARY_WORDS = {
    "after", "amid", "announces", "backs", "before", "begins", "calls",
    "closed", "closes", "due", "faces", "following", "for", "from", "gets",
    "given", "hosts", "launches", "named", "opens", "plans", "returns",
    "set", "takes", "to", "tour", "under", "warns", "wins", "with",
}
_CONNECTORS = {"and", "of", "the", "for", "at", "in", "on", "de", "la"}
_LOCAL_AREAS = {
    "rochdale", "heywood", "middleton", "littleborough", "milnrow", "newhey",
    "wardle", "norden", "castleton", "kirkholt", "spotland", "falinge",
    "deeplish", "bamford", "smallbridge", "firgrove", "whitworth",
}


def _entity_phrase(query: str) -> str:
    """Return the strongest likely person, organisation or venue phrase."""
    text = re.sub(
        r"\s+(?:" + "|".join(sorted(_LOCAL_AREAS, key=len, reverse=True)) + r")\s*$",
        "",
        query.strip(),
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\b20\d{2}\b", "", text)
    text = text.split(" - ", 1)[0].strip(" :-–—")
    tokens = re.findall(r"[A-Za-z0-9&'’-]+", text)
    if not tokens:
        return ""

    phrase: list[str] = []
    for token in tokens:
        lower = token.lower()
        if phrase and lower in _BOUNDARY_WORDS:
            break
        looks_named = token[:1].isupper() or token.isupper() or lower in _CONNECTORS
        if not looks_named:
            if phrase:
                break
            continue
        phrase.append(token)
        if len(phrase) >= 6:
            break

    meaningful = [word for word in phrase if word.lower() not in _CONNECTORS]
    if len(meaningful) < 2:
        return ""
    return " ".join(phrase).strip()


def _rewrite_commons_query(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    if value.get("action") != "query" or value.get("generator") != "search":
        return value
    if str(value.get("gsrnamespace", "")) != "6":
        return value

    original = str(value.get("gsrsearch") or "").strip()
    entity = _entity_phrase(original)
    if not entity:
        return value

    rewritten = dict(value)
    rewritten["gsrsearch"] = f'"{entity}" {original}'
    return rewritten


def urlencode(query: Any, doseq: bool = False, safe: str = "", encoding: str | None = None,
              errors: str | None = None, quote_via=urllib.parse.quote_plus) -> str:
    return _ORIGINAL_URLENCODE(
        _rewrite_commons_query(query),
        doseq=doseq,
        safe=safe,
        encoding=encoding,
        errors=errors,
        quote_via=quote_via,
    )


urllib.parse.urlencode = urlencode
