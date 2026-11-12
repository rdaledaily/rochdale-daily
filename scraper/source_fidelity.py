"""Deterministic source-fidelity checks for automated rewrites.

Written 12 Nov 2026 after "Man arrested for possessing imitation firearm at
Rochdale Armistice Day event" published with a sentence no source contained:
GMP "reiterated that the safety of the public is their priority". The rewrite
gate only checked that the draft shared a few words with the source, so an
invented police statement passed. The independent fact review flagged the
story but, as with every arrest story, only as "needs human approval", and that
verdict does not block publication.

These checks need no model. Each one asks a narrow question the source text
can answer:

  numbers       every figure in the draft (ages, counts, money, times) is in
                the source
  quotations    every direct quotation in the draft is in the source, word for
                word
  attributions  every sentence that puts words in a person's or body's mouth
                ("police said", "a spokesperson confirmed") is built from the
                source's own content words

A failure is an integrity failure: the rewrite loop sends it back to the
writer to repair, and if the writer cannot, the story does not publish.
"""
from __future__ import annotations

import html
import re
import unicodedata

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100,
}
_DECADE_WORDS = {
    "teens": 10, "twenties": 20, "thirties": 30, "forties": 40, "fifties": 50,
    "sixties": 60, "seventies": 70, "eighties": 80, "nineties": 90,
}
_MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|"
    "november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
)

# Words that carry no fact of their own in an attribution sentence.
_ATTRIBUTION_FILLER = {
    "said", "says", "saying", "confirmed", "confirm", "confirms", "stated",
    "states", "added", "adds", "told", "explained", "reiterated", "stressed",
    "emphasised", "emphasized", "insisted", "noted", "according", "spokesperson",
    "spokesman", "spokeswoman", "statement", "police", "officers", "officer",
    "greater", "manchester", "force", "council", "they", "their", "them", "that",
    "this", "there", "which", "would", "could", "also", "have", "been", "were",
    "with", "from", "into", "about", "after", "before", "while", "when", "what",
    "will", "remains", "remain", "continue", "continues", "continuing", "being",
    "further", "those", "these", "other", "such", "some", "more", "than", "only",
    "very", "just", "over", "under", "said:", "gmp", "rochdale", "borough",
    "public", "member", "members", "people", "matter", "incident",
}

_ATTRIBUTION_RE = re.compile(
    r"\b(?:said|says|confirmed|stated|added|told|explained|reiterated|stressed|"
    r"emphasi[sz]ed|insisted|noted|according to)\b",
    re.I,
)

_QUOTE_RE = re.compile(r"[\"“”]([^\"“”]{8,}?)[\"“”]")


_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.I)


def _plain(value: object) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
    # Source links carry record ids ("directory-record/2644/..."), not figures.
    text = _URL_RE.sub(" ", text)
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", text).strip()


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _stem(word: str) -> str:
    return word[:5]


def _source_numbers(source: str) -> set[int]:
    found: set[int] = set()
    lowered = source.lower()
    for match in re.finditer(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?", lowered):
        found.add(int(match.group(1).replace(",", "")))
    for word, value in {**_NUMBER_WORDS, **_DECADE_WORDS}.items():
        if re.search(rf"\b{word}\b", lowered):
            found.add(value)
    # Compound words: "twenty-one".
    for tens, units in re.findall(r"\b(twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)[- ](one|two|three|four|five|six|seven|eight|nine)\b", lowered):
        found.add(_NUMBER_WORDS[tens] + _NUMBER_WORDS[units])
    # A time "11.30am" also states 11 and 30.
    for hour, minute in re.findall(r"\b(\d{1,2})[.:](\d{2})\s*(?:am|pm)\b", lowered):
        found.update({int(hour), int(minute)})
    return found


def _draft_numbers(draft: str) -> list[tuple[str, int]]:
    """Return (as written, value) for each figure the draft states."""
    lowered = draft.lower()
    claims: list[tuple[str, int]] = []
    # Decade ages: "in his 50s", "in her fifties".
    for match in re.finditer(r"\b(\d0)'?s\b", lowered):
        claims.append((match.group(0), int(match.group(1))))
    for match in re.finditer(r"\b(teens|twenties|thirties|forties|fifties|sixties|seventies|eighties|nineties)\b", lowered):
        claims.append((match.group(0), _DECADE_WORDS[match.group(1)]))
    stripped = re.sub(r"\b\d0'?s\b", " ", lowered)
    # Times count as their parts.
    for hour, minute in re.findall(r"\b(\d{1,2})[.:](\d{2})\s*(?:am|pm)\b", stripped):
        claims.append((f"{hour}.{minute}", int(hour)))
        claims.append((f"{hour}.{minute}", int(minute)))
    stripped = re.sub(r"\b\d{1,2}[.:]\d{2}\s*(?:am|pm)\b", " ", stripped)
    # Dates are left out. The writer is told to turn "this morning" or
    # "Wednesday" into the calendar date, so a day number absent from the
    # source is expected there; years have their own check in quality_issues.
    stripped = re.sub(rf"\b\d{{1,2}}(?:st|nd|rd|th)?(?:\s*[-–]\s*\d{{1,2}}(?:st|nd|rd|th)?)?\s+(?:of\s+)?(?:{_MONTHS})\b", " ", stripped)
    stripped = re.sub(rf"\b(?:{_MONTHS})\s*[-–]?\s*\d{{1,2}}(?:st|nd|rd|th)?\b", " ", stripped)
    for match in re.finditer(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:st|nd|rd|th)?", stripped):
        value = int(match.group(1).replace(",", ""))
        if 1900 <= value <= 2100:
            continue
        claims.append((match.group(0), value))
    for word in re.findall(r"\b(" + "|".join(_NUMBER_WORDS) + r")\b", stripped):
        if word == "one":
            continue  # "one of", "no one": not a figure
        claims.append((word, _NUMBER_WORDS[word]))
    return claims


def unsupported_numbers(draft: str, source: str) -> list[str]:
    draft_text = _plain(draft)
    source_numbers = _source_numbers(_plain(source))
    missing: list[str] = []
    for written, value in _draft_numbers(draft_text):
        if value not in source_numbers and written not in missing:
            missing.append(written)
    return missing


def unsupported_quotes(draft: str, source: str) -> list[str]:
    source_norm = " ".join(_tokens(_plain(source)))
    missing: list[str] = []
    for quote in _QUOTE_RE.findall(_plain(draft)):
        words = _tokens(quote)
        if len(words) < 3:
            continue
        if " ".join(words) not in source_norm:
            missing.append(quote.strip())
    return missing


def unsupported_attributions(draft: str, source: str, threshold: float = 0.5) -> list[str]:
    """Attributed sentences whose content words are mostly absent from the source."""
    source_stems = {_stem(t) for t in _tokens(_plain(source)) if len(t) >= 4}
    draft_text = _QUOTE_RE.sub(" ", _plain(draft))
    flagged: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", draft_text):
        if not _ATTRIBUTION_RE.search(sentence):
            continue
        content = [
            t for t in _tokens(sentence)
            if len(t) >= 4 and t not in _ATTRIBUTION_FILLER and not t.isdigit()
        ]
        if len(content) < 3:
            continue
        present = sum(1 for t in content if _stem(t) in source_stems)
        if present / len(content) < threshold:
            flagged.append(sentence.strip())
    return flagged


# Legal status and harm. Each group is one fact: the draft may only use a word
# from a group when the source uses a word from the same group. "Arrested" can
# never become "charged", "charged" never "convicted", "died" never "killed".
# These are the words that carry contempt-of-court and defamation risk.
_STATUS_GROUPS: tuple[tuple[str, str, str], ...] = (
    ("arrested", r"\barrest(?:ed|s|ing)?\b", r"\barrest"),
    ("charged", r"\b(?:charged with|been charged|was charged|were charged|is charged|are charged|charges? of)\b", r"\bcharg"),
    ("convicted / found guilty", r"\b(?:convicted|conviction|found guilty|pleaded guilty|admitted (?:the|a|an|his|her|their)? ?(?:offence|charge|count))", r"\b(?:convict|guilty|admitted)"),
    ("jailed / sentenced", r"\b(?:jailed|imprisoned|sentenced|prison sentence|custodial sentence|behind bars)\b", r"\b(?:jail|imprison|sentenc|prison|custod)"),
    ("remanded", r"\bremanded\b", r"\bremand"),
    ("bailed", r"\b(?:bailed|on bail|released on bail|granted bail)\b", r"\bbail"),
    ("murder", r"\bmurder", r"\bmurder"),
    ("manslaughter", r"\bmanslaughter\b", r"\bmanslaughter"),
    ("rape", r"\brap(?:e|ed|ist)\b", r"\brap(?:e|ed|ist)\b"),
    ("sexual offence", r"\bsexual(?:ly)? (?:assault|abuse|offence|activity|exploitation)", r"\bsexual"),
    ("assault", r"\bassault", r"\bassault"),
    ("robbery", r"\brobb(?:ery|ed|er)", r"\brobb"),
    ("burglary", r"\bburgl", r"\bburgl"),
    ("fraud", r"\bfraud", r"\bfraud"),
    ("stabbing", r"\bstab(?:bed|bing)\b", r"\bstab"),
    ("shooting", r"\b(?:shot|shooting|gunshot)\b", r"\b(?:shot|shoot|gun)"),
    ("death", r"\b(?:died|dies|death|dead|fatal(?:ly)?|passed away)\b", r"\b(?:died|dies|death|dead|fatal|passed away|killed)"),
    ("killed", r"\bkill(?:ed|ing)\b", r"\b(?:kill|murder|manslaughter)"),
    ("serious injury", r"\b(?:seriously injured|serious injuries|critical condition|life-changing|life-threatening)\b", r"\b(?:serious|critical|life-changing|life-threatening|life changing|life threatening)"),
    ("firearm", r"\b(?:firearm|gun|pistol|rifle|shotgun)s?\b", r"\b(?:firearm|gun|pistol|rifle|shotgun)"),
    ("knife", r"\b(?:knife|knives|bladed)\b", r"\b(?:knife|knives|blade)"),
)


def unsupported_status(draft: str, source: str) -> list[str]:
    """Legal-status and harm words in the draft that the source never uses."""
    draft_l = _QUOTE_RE.sub(" ", _plain(draft)).lower()
    source_l = _plain(source).lower()
    return [
        label for label, draft_re, source_re in _STATUS_GROUPS
        if re.search(draft_re, draft_l) and not re.search(source_re, source_l)
    ]


# Capitalised words that are furniture rather than a claim about who or where.
_NAME_ALLOW = {
    "rochdale", "daily", "the", "a", "an", "he", "she", "it", "they", "we", "i",
    "his", "her", "their", "its", "this", "that", "these", "those", "there",
    "mr", "mrs", "ms", "miss", "dr", "cllr", "councillor", "pc", "ps", "dc", "ds",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "uk", "england", "britain",
    "british", "english", "greater", "manchester", "borough", "council", "police",
    "gmp", "nhs", "a&e", "bst", "gmt", "am", "pm", "readers", "residents",
    "anyone", "people", "officers", "anybody", "source", "photograph", "image",
    # Titles and roles: the writer may expand "MP" or "Sgt"; the person's
    # name is what must match.
    "sergeant", "sgt", "inspector", "constable", "detective", "superintendent",
    "chief", "officer", "member", "parliament", "mp", "mayor", "leader",
    "minister", "secretary", "director", "executive", "manager", "headteacher",
    "head", "professor", "doctor", "deputy", "assistant", "spokesperson",
}


def unsupported_names(draft: str, source: str) -> list[str]:
    """Capitalised names (people, places, organisations) absent from the source."""
    text = _QUOTE_RE.sub(" ", _plain(draft))
    source_l = " " + " ".join(_tokens(_plain(source))) + " "
    missing: list[str] = []
    for sentence in re.split(r"(?<=[.!?:])\s+|\n+", text):
        words = re.findall(r"[A-Za-z][A-Za-z'’-]*", sentence)
        for index, word in enumerate(words):
            if index == 0 or not word[0].isupper():
                continue  # sentence-initial capitals are grammar, not names
            # Only capitalised pieces are names: "Rochdale-based" claims
            # Rochdale, not "based".
            for piece in re.split(r"[-'’]", word):
                if not piece or not piece[0].isupper():
                    continue
                part = piece.lower()
                if len(part) < 3 or part in _NAME_ALLOW:
                    continue
                if f" {part} " not in source_l and f" {part}s " not in source_l and not (part.endswith("s") and f" {part[:-1]} " in source_l):
                    if word not in missing:
                        missing.append(word)
    return missing


_MONTH_NUM = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], 1)}
_MONTH_NUM.update({k[:3]: v for k, v in list(_MONTH_NUM.items())})
_MONTH_NUM["sept"] = 9
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_RELATIVE_RE = re.compile(r"\b(?:today|tonight|this (?:morning|afternoon|evening)|earlier today|yesterday|last night|overnight)\b", re.I)


def _dates_in(text: str) -> set[tuple[int, int]]:
    """(day, month) pairs a text states, including both ends of ranges."""
    found: set[tuple[int, int]] = set()
    lowered = text.lower()
    month = r"(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec)\b"
    day = r"(\d{1,2})(?:st|nd|rd|th)?"
    for d1, d2, m in re.findall(rf"\b{day}\s*(?:[-–]|to|and|until)\s*{day}\s+(?:of\s+)?{month}", lowered):
        found.update({(int(d1), _MONTH_NUM[m]), (int(d2), _MONTH_NUM[m])})
    for d1, m, d2 in re.findall(rf"\b{day}\s+(?:of\s+)?{month}\s*[-–]\s*{day}\b(?!\s*(?:am|pm|:))", lowered):
        found.update({(int(d1), _MONTH_NUM[m]), (int(d2), _MONTH_NUM[m])})
    for d, m in re.findall(rf"\b{day}\s+(?:of\s+)?{month}", lowered):
        found.add((int(d), _MONTH_NUM[m]))
    for m, d in re.findall(rf"\b{month}\s+{day}\b", lowered):
        found.add((int(d), _MONTH_NUM[m]))
    for d, mo in re.findall(r"\b(\d{1,2})/(\d{1,2})/(?:20)?\d{2}\b", lowered):
        if 1 <= int(mo) <= 12:
            found.add((int(d), int(mo)))
    return {(d, m) for d, m in found if 1 <= d <= 31}


def _source_dates(source: str) -> list:
    from datetime import date
    out = []
    for value in re.findall(r"source date: (\d{4})-(\d{2})-(\d{2})", source):
        try:
            out.append(date(int(value[0]), int(value[1]), int(value[2])))
        except ValueError:
            pass
    return out


def unsupported_dates(draft: str, source: str, published_on=None) -> list[str]:
    """Dates in the draft that the source neither states nor implies.

    A source written on 11 November that says "this morning, Wednesday" or
    "yesterday" implies a calendar date; the writer may state it. Anything
    else must be in the source.
    """
    from datetime import timedelta
    source_plain = _plain(source)
    stated = _dates_in(source_plain)
    anchors = _source_dates(source)
    if published_on is not None:
        anchors.append(published_on)
    implied: set[tuple[int, int]] = set()
    lowered = source_plain.lower()
    weekdays = {i for i, w in enumerate(_WEEKDAYS) if re.search(rf"\b{w}\b", lowered)}
    for anchor in anchors:
        if _RELATIVE_RE.search(source_plain):
            for back in (0, 1):
                d = anchor - timedelta(days=back)
                implied.add((d.day, d.month))
        for offset in range(-8, 15):
            d = anchor + timedelta(days=offset)
            if d.weekday() in weekdays:
                implied.add((d.day, d.month))
    missing = []
    for day, month in sorted(_dates_in(_plain(draft)) - stated - implied):
        if not anchors and not stated:
            continue  # nothing to check against
        missing.append(f"{day} {list(_MONTH_NUM)[month - 1].title()}")
    return missing


def fidelity_issues(draft_text: str, source_text: str, published_on=None) -> list[str]:
    """Integrity issues, phrased as repair instructions for the writer."""
    issues: list[str] = []
    status = unsupported_status(draft_text, source_text)
    if status:
        issues.append(
            "Source fidelity: the draft says " + ", ".join(status)
            + " but the source does not. Never change a legal status, offence, "
            "weapon or harm; use the source's own word."
        )
    names = unsupported_names(draft_text, source_text)
    if names:
        issues.append(
            "Source fidelity: the name(s) " + ", ".join(names[:8])
            + " do not appear in the source. Name only people, places and "
            "organisations the source names."
        )
    dates = unsupported_dates(draft_text, source_text, published_on)
    if dates:
        issues.append(
            "Source fidelity: the date(s) " + ", ".join(dates)
            + " are neither stated nor implied by the source. Use only the "
            "source's dates."
        )
    numbers = unsupported_numbers(draft_text, source_text)
    if numbers:
        issues.append(
            "Source fidelity: the figure(s) " + ", ".join(numbers)
            + " do not appear in the source. Use only figures the source states."
        )
    quotes = unsupported_quotes(draft_text, source_text)
    if quotes:
        issues.append(
            "Source fidelity: these quotation(s) are not in the source word for "
            "word: " + " | ".join(q[:80] for q in quotes)
            + ". Quote only exact source words."
        )
    attributions = unsupported_attributions(draft_text, source_text)
    if attributions:
        issues.append(
            "Source fidelity: these sentence(s) attribute statements the source "
            "does not contain: " + " | ".join(a[:120] for a in attributions)
            + ". Remove them or report only what the source says."
        )
    return issues
