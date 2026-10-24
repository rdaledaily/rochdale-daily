"""House headline style: sentence case, like a British newspaper.

Measured 24 Oct 2026: 109 of 110 automated rewrites came out in Title Case
("Rochdale AFC Secures 3-0 Victory Against Shrewsbury Town") while editors'
own headlines were sentence case. Title Case reads as press-release copy and
earns fewer clicks. The rewrite prompt now asks for sentence case, and this
module enforces it deterministically, because the model does not always obey.

How a word keeps its capital:
  * the first word of the headline, and the first word after a colon;
  * acronyms and anything containing a digit (AFC, GMP, M62, A58, 3-0);
  * days, months, and the word "I";
  * proper nouns: a word the story's own text writes with a capital letter
    somewhere other than the start of a sentence ("Shrewsbury Town",
    "Crown Oil Arena", "Rochdale Council");
  * a small gazetteer of borough places, for headlines whose body is short.

Only headlines that are actually in Title Case are changed, and only on
automated news rewrites: editors' headlines and event listings (show names)
are never touched.
"""
from __future__ import annotations

import html
import re

SMALL_WORDS = frozenset(
    "a an the and or but nor of in on at to for by from with as vs via into onto "
    "over after before off out up per than".split()
)
ALWAYS_CAPITAL = frozenset(
    "i monday tuesday wednesday thursday friday saturday sunday january february march "
    "april may june july august september october november december christmas easter "
    "halloween eid diwali ramadan".split()
)
# "may" and "march" are also ordinary words; they keep a capital only when the
# body confirms the month (handled by the proper-noun check first).
AMBIGUOUS_CALENDAR = frozenset({"may", "march"})
PLACES = frozenset(
    "rochdale heywood middleton littleborough milnrow newhey wardle norden bamford "
    "castleton spotland falinge deeplish smallbridge firgrove kirkholt balderstone "
    "healey hopwood alkrington syke shawclough whitworth oldham bury manchester "
    "greater england britain british uk english scotland scottish wales welsh "
    "ireland irish europe european london liverpool leeds bolton salford stockport "
    "wigan tameside trafford rossendale todmorden bacup ramsbottom huddersfield "
    "halifax burnley blackburn preston lancashire yorkshire cheshire pennines "
    "pakistan pakistani india indian bangladesh bangladeshi poland polish".split()
)
_WORD = re.compile(r"[A-Za-z][A-Za-z'’\-.&]*")


def _plain(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))


def is_title_case(title: str) -> bool:
    words = [w for w in _WORD.findall(title)[1:] if w.lower() not in SMALL_WORDS and len(w) > 3]
    return len(words) >= 2 and sum(w[0].isupper() for w in words) / len(words) > 0.8


def _body_evidence(body: str) -> tuple[set[str], set[str]]:
    """From the story text: words written with a capital mid-sentence, and words
    ever written in lower case."""
    standalone: set[str] = set()
    lower: set[str] = set()
    for sentence in re.split(r"(?<=[.!?:])\s+|\n+", body):
        words = _WORD.findall(sentence)
        for index, word in enumerate(words):
            key = _key(word)
            if word[0].islower():
                lower.add(key)
                continue
            if not index:
                continue
            # Any capital mid-sentence counts. Erring towards keeping a capital
            # ("by Court") is a blemish; lower-casing a surname or a club
            # ("Chris cheap", "face bolton") is an error. Words the story also
            # writes in lower case are still lowered (see sentence_case).
            standalone.add(key)
    return standalone, lower


def _names_in_body(matches: list, title: str, body: str) -> set[int]:
    """Indexes of title words inside a multi-word name the body writes the same
    way, mid-sentence ("Office of Rail and Road", "Restaurant of the Year")."""
    keep: set[int] = set()
    for size in range(5, 1, -1):
        for start in range(0, len(matches) - size + 1):
            span = title[matches[start].start():matches[start + size - 1].end()]
            words = [m.group(0) for m in matches[start:start + size]]
            if words[0].lower() in SMALL_WORDS or words[-1].lower() in SMALL_WORDS:
                continue
            if sum(w[0].isupper() for w in words) < 2:
                continue
            for found in re.finditer(r"(?<![A-Za-z])" + re.escape(span) + r"(?![a-z])", body):
                lead = body[:found.start()].rstrip()
                if lead and lead[-1] not in ".!?:\n\"“‘'":
                    keep.update(range(start, start + size))
                    break
    return keep


def _key(word: str) -> str:
    return re.sub(r"['’]s$", "", word).lower().strip(".")


INSTITUTION_WORDS = frozenset({"council", "borough"})
STREET_WORDS = frozenset(
    "street road lane avenue way drive close park place square terrace crescent "
    "grove gardens walk row hill brow bridge green parade fold".split()
)


def sentence_case(title: str, body: str = "") -> str:
    """Convert a Title Case headline to sentence case; anything else is returned unchanged.
    It only ever lowers capitals; it never adds one."""
    title = str(title or "").strip()
    if not is_title_case(title):
        return title
    plain_body = _plain(body)
    standalone, lower = _body_evidence(plain_body)
    matches = list(_WORD.finditer(title))
    keys = [_key(m.group(0)) for m in matches]
    keep = [False] * len(matches)
    for i in _names_in_body(matches, title, plain_body):
        keep[i] = True
    for i, match in enumerate(matches):
        word, key = match.group(0), keys[i]
        before = title[matches[i - 1].end():match.start()] if i else ""
        if keep[i]:
            continue
        if i == 0 or ":" in before:
            keep[i] = True
        elif any(ch.isdigit() for ch in word):
            keep[i] = True
        elif len(word) > 1 and re.sub(r"[-.&'’]", "", word).isupper():
            keep[i] = True                                   # AFC, GMP, HMO, RUFC
        elif key in ALWAYS_CAPITAL and key not in AMBIGUOUS_CALENDAR:
            keep[i] = True
        elif key in PLACES:
            keep[i] = True
        elif key in standalone and key not in lower:
            keep[i] = True                                   # a name: Bolton, Abraham, Tesco, Ofsted
        elif key in INSTITUTION_WORDS and i and keys[i - 1] in PLACES:
            keep[i] = True                                   # Rochdale Council, Rochdale Borough
    # Road names: "Trafalgar Street", "Elizabethan Way" -- when the story writes
    # that exact name ("Temporary Road closures" is not a road).
    for i in range(len(matches) - 1, 0, -1):
        if keys[i] in STREET_WORDS and matches[i].group(0)[0].isupper():
            name = title[matches[i - 1].start():matches[i].end()]
            confirmed = re.search(r"(?<![A-Za-z])" + re.escape(name) + r"(?![a-z])", plain_body)
            # Mid-headline "X Street" is a road name even if the text is silent;
            # only a headline's opening word ("Temporary Road ...") needs proof.
            if confirmed or (i - 1 > 0 and keys[i - 1] not in SMALL_WORDS):
                keep[i] = keep[i - 1] = True
    # Quoted titles and slogans stay exactly as written.
    for quoted in re.finditer(r"(?:^|(?<=\s))['‘\"“]([^'’\"”]{2,80})['’\"”](?=$|[\s,.;:!?])", title):
        for i, match in enumerate(matches):
            if quoted.start(1) <= match.start() < quoted.end(1):
                keep[i] = True
    out: list[str] = []
    position = 0
    for i, match in enumerate(matches):
        out.append(title[position:match.start()])
        word = match.group(0)
        if keep[i] and i == 0 and "-" in word and not any(ch.isdigit() for ch in word):
            first, *rest = word.split("-")                   # "Nine-Year-Old" -> "Nine-year-old"
            out.append("-".join([first] + [
                part if (_key(part) in PLACES or (_key(part) in standalone and _key(part) not in lower)
                         or part[1:] != part[1:].lower())
                else part[:1].lower() + part[1:]
                for part in rest]))
        elif keep[i]:
            out.append(word)                                 # never add a capital
        else:
            out.append("-".join(part[:1].lower() + part[1:] if part[1:] == part[1:].lower() else part
                                for part in word.split("-")))
        position = match.end()
    out.append(title[position:])
    return "".join(out)


def should_restyle(record: dict) -> bool:
    """Only automated news rewrites. Editors' headlines and event listings
    (whose titles are show names) are never touched."""
    if record.get("manual_article") or record.get("editorial_lock"):
        return False
    if record.get("event_start_at") or str(record.get("source_kind") or "") == "event":
        return False
    if str(record.get("category") or "") == "events":
        return False
    route = str(record.get("publication_route") or "")
    return route in ("", "ai-grounded-rewrite", "official-record-grounded-rewrite")


TITLE_SUFFIX = " | Rochdale Daily"
TITLE_TAG_LIMIT = 60


def title_tag(title: str) -> str:
    """The <title>: the brand suffix only when it still fits Google's display.

    1,427 of 1,785 page titles ran past what Google shows, partly because the
    17-character suffix was always added. Google shows the site name beside
    results separately, so a long headline goes out alone rather than being
    cut off mid-word."""
    title = str(title or "").strip()
    return title + TITLE_SUFFIX if len(title) + len(TITLE_SUFFIX) <= TITLE_TAG_LIMIT else title


def restyle_feed(path) -> int:
    """Sentence-case automated headlines in articles.json. Idempotent: a
    converted headline is no longer Title Case, so it is left alone after."""
    import json
    from pathlib import Path as _Path
    path = _Path(path)
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    if not isinstance(records, list):
        return 0
    changed = 0
    for record in records:
        if not isinstance(record, dict) or not should_restyle(record):
            continue
        title = str(record.get("title") or "")
        body = " ".join(str(record.get(k) or "") for k in ("content_html", "excerpt"))
        new = sentence_case(title, body)
        if new != title:
            record["title"] = new
            changed += 1
    if changed:
        path.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changed
