"""Reader-copy rules shared by the rewrite gate, the page renderer and Facebook.

Measured 28 October 2026 (GA, 9-27 Oct): 894 of 1,606 readers arrived from
Facebook and stayed 9 seconds on average; 890 never came back. On the same
story MEN published at the same minute, Rochdale Daily's standfirst repeated
paragraph 1, paragraph 1 ran to 69 words, and the copy carried filler such as
"This incident occurred" and "Fortunately". MEN's longest paragraph was 42
words and its standfirst added a fact the headline did not carry.

Everything here is deterministic. Nothing changes a fact, a quotation, a
name or a number: paragraphs are only re-broken at sentence boundaries, and
the only words ever removed are sentence-opening filler adverbs.
"""
from __future__ import annotations

import html
import re
from typing import Any, Iterable

MAX_PARAGRAPH_WORDS = 45
MAX_PARAGRAPH_SENTENCES = 2
SOCIAL_HEADLINE_MIN = 30
SOCIAL_HEADLINE_MAX = 110

# Abbreviations that end in a full stop without ending a sentence.
_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "st", "no", "nos", "cllr", "insp", "sgt", "supt",
    "pc", "det", "rev", "prof", "jr", "sr", "ltd", "co", "vs", "v", "eg", "ie",
    "etc", "approx", "dept", "gov", "govt", "inc", "jan", "feb", "mar", "apr",
    "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec", "a.m", "p.m",
    "e.g", "i.e", "ft", "mph", "est", "hon", "lt", "col", "capt", "gen",
}

_SPLIT_RE = re.compile(r"(?<=[.!?])[\"'”’)]?\s+(?=[\"'“‘(£\dA-Z])")

# Sentence-opening filler. Removing the word leaves the sentence intact and
# its meaning unchanged; each also editorialises ("Fortunately" takes a side).
FILLER_OPENER_RE = re.compile(
    r"(?:^|(?<=[.!?]\s))(?:Fortunately|Unfortunately|Additionally|Furthermore|"
    r"Moreover|Notably|Importantly|Interestingly|Ultimately|Overall|In addition|"
    r"In conclusion|As such),\s+([A-Za-z\u2018\u201c\"])",
)

# Phrases that read as machine filler. Style feedback for the repair loop;
# never applied to quotations by the renderer.
AI_TELL_RE = re.compile(
    r"\b(?:"
    r"this incident occurred|the incident occurred|this incident has|"
    r"it is worth noting|it should be noted|worth mentioning|"
    r"fortunately|unfortunately|furthermore|moreover|additionally|"
    r"in conclusion|regarding the matter|in relation to the matter|"
    r"shortly thereafter|thereafter|aims? to strengthen|"
    r"reassured that|in light of|amid(?:st)? growing|"
    r"plays? a (?:crucial|vital|pivotal) role|navigat(?:e|ing) the|"
    r"a reminder of|underscor(?:e|es|ing)|highlights? the importance|"
    r"(?:is|are) crucial|crucial (?:for|in|to|as)|critical importance|"
    r"ensuring the safety and security|reflects? the \w+(?:'s|’s)? commitment"
    r")\b",
    re.IGNORECASE,
)

_STOPWORDS = {
    "about", "above", "after", "again", "against", "also", "been", "before",
    "being", "below", "between", "both", "could", "does", "doing", "down",
    "during", "each", "from", "further", "have", "having", "here", "into",
    "itself", "just", "more", "most", "once", "only", "other", "over", "same",
    "should", "some", "such", "than", "that", "their", "them", "then",
    "there", "these", "they", "this", "those", "through", "under", "until",
    "very", "were", "what", "when", "where", "which", "while", "will", "with",
    "would", "your", "said", "says", "according", "rochdale",
}

# Words that mark a story where a question headline insinuates.
_QUESTION_UNSAFE_CATEGORIES = {"crime", "court", "courts", "police"}
_QUESTION_UNSAFE_RE = re.compile(
    r"\b(?:arrest|charged|court|jailed|sentenced|police|accused|alleged|"
    r"investigat|fraud|assault|murder|stabb|theft|abuse|guilty)\w*",
    re.IGNORECASE,
)

CLICKBAIT_RE = re.compile(
    r"\b(?:you won'?t believe|what happened next|this is why|"
    r"shocking|jaw-dropping|mind-blowing|must see|goes viral)\b",
    re.IGNORECASE,
)


def plain(value: Any) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _quote_open(text: str) -> bool:
    curly = text.count("“") - text.count("”")
    straight = text.count('"') % 2
    return curly > 0 or straight == 1


def split_sentences(text: str) -> list[str]:
    """Split prose into sentences without breaking abbreviations or quotes."""
    text = plain(text)
    if not text:
        return []
    sentences: list[str] = []
    start = 0
    for match in _SPLIT_RE.finditer(text):
        head = text[start:match.start()]
        stripped = head.rstrip("\"'”’)").rstrip(".!?")
        last = stripped.rsplit(" ", 1)[-1].lower().rstrip(".")
        if last in _ABBREVIATIONS or len(last) == 1 and last.isalpha():
            continue
        if _quote_open(text[:match.start() + 1]):
            continue
        piece = text[start:match.end()].strip()
        if piece:
            sentences.append(piece)
        start = match.end()
    tail = text[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


def words(text: str) -> int:
    return len(re.findall(r"\S+", plain(text)))


def split_long_paragraphs(
    paragraphs: Iterable[str],
    max_sentences: int = MAX_PARAGRAPH_SENTENCES,
    max_words: int = MAX_PARAGRAPH_WORDS,
) -> list[str]:
    """Re-break paragraphs at sentence boundaries: at most two sentences and
    45 words each. A single sentence longer than that stays whole. Words are
    never added, removed or reordered."""
    out: list[str] = []
    for paragraph in paragraphs:
        text = plain(paragraph)
        if not text:
            continue
        if words(text) <= max_words and len(split_sentences(text)) <= max_sentences:
            out.append(text)
            continue
        current: list[str] = []
        for sentence in split_sentences(text):
            candidate = current + [sentence]
            if current and (
                len(candidate) > max_sentences
                or words(" ".join(candidate)) > max_words
            ):
                out.append(" ".join(current))
                current = [sentence]
            else:
                current = candidate
        if current:
            out.append(" ".join(current))
    return out


def strip_filler_openers(text: str) -> str:
    """'Fortunately, the councillor is safe' -> 'The councillor is safe'."""
    def repl(match: re.Match[str]) -> str:
        return match.group(1).upper()
    return FILLER_OPENER_RE.sub(repl, text)


# Closing commentary the paper never needs (measured 6 Nov 2026: 36 of 241
# automated stories ended on one, e.g. "This warning is crucial for ensuring
# the safety and security of residents in the community."). A sentence is
# removed only when ALL of these hold: it is in one of the last two plain
# paragraphs; it opens with a summary subject ("This incident", "These
# events"); it moralises ("is crucial", "underscores the importance",
# "reflects the council's commitment"); and it holds no number, no quotation
# and no attribution. So no fact, figure or quote can be lost. Sentences that
# tell the reader what changes for them ("may affect daily travel routes")
# do not match and stay.
_SUMMARY_SUBJECT_RE = re.compile(
    r"^(?:This|These|The|Such) (?:[a-z]+ )?(?:incident|initiative|initiatives|event|events|case|"
    r"situation|development|recognition|warning|warnings|news|move|scheme|project|decision|"
    r"programme|investment|achievement|milestone|operation|effort|efforts|sessions?|award|"
    r"celebration|appointment|partnership|closure|change|changes)\b"
)
_MORALISING_RE = re.compile(
    r"\b(?:(?:is|are|was|were|remains?) (?:crucial|vital|essential)|crucial (?:for|in|to|as)|"
    r"plays? an? (?:crucial|vital|pivotal|key|important) role|serves? as an? (?:important |timely |stark )?reminder|"
    r"(?:is|are|was) a testament|underscor\w+|highlights? the (?:importance|need|value|critical)|"
    r"critical (?:importance|role)|reflects? the \w+(?:'s|’s)? commitment|ensur\w+ the safety and security)\b",
    re.I,
)
_FACT_MARK_RE = re.compile(r"\d|[\"“”]|\b(?:said|says|stated|according)\b", re.I)
# A clause that explains or reports ("because engineers found...", "as it
# seeks to provide housing", "by streamlining operations") keeps the sentence.
_EXPLAINS_RE = re.compile(
    r"\b(?:because|since|after|following|due|as (?:it|they|he|she|the|this|these|a|an)|by|which|who|when|"
    r"where|while|whilst|offering|providing|allowing|enabling|including|seeks?|aims?|will|would|found|"
    r"not only)\b",
    re.I,
)
# Every content word of a disposable closer comes from this list: the stock
# vocabulary of an AI moral ending, with nothing about this particular story.
# Measured 6 Nov 2026 on the 241 automated stories: a summary subject plus a
# moralising phrase matched 22 closing sentences, several of which carried
# reporting (housing plans, SEN services, the need for foster carers). Only
# sentences made wholly of these words are removed.
_BOILERPLATE_WORDS = frozenset("""
this these the such a an of and or in to for on its their our is are was were be being remains
incident initiative initiatives event events case situation development recognition warning warnings
news move scheme project decision programme investment achievement milestone operation effort efforts
session sessions award celebration appointment partnership closure change changes tragic recent latest
crucial vital essential critical key important pivotal significant timely stark
underscores underscore underscored highlights highlight highlighted serves serve reminder reminds testament
reflects reflect reflected plays play role importance need needs value
ensuring ensure maintaining maintain protecting protect safeguarding promoting
safety security wellbeing welfare public community communities residents resident local people everyone
individuals vulnerable area areas borough town region all those
awareness vigilance vigilant proactive measures preparedness responsible responsibility cooperation
support supporting involvement engagement commitment council council's councils
trust integrity accountability transparency inclusivity accessibility
staying informed being aware taking precautions caution care alert
continued ongoing wider broader overall general importance particularly especially also
protocols procedures effective response emergency services situations such schools
character neighbourhoods neighbourhood adhering adherence regulations rules planning
""".split())


# 7 Nov 2026 (editor): no sympathy or good wishes in the paper's own voice.
# A sentence inside quotation marks is someone's words and is never matched.
_SENTIMENT_CLOSER_RE = re.compile(
    r"^(?:Our|Rochdale Daily's|Rochdale Daily sends its) (?:deepest |sincere |heartfelt )?(?:thoughts|sympathies|condolences|prayers)\b"
    r"|^(?:We|Rochdale Daily) (?:wish|send|extend|offer)\b[^.]*\b(?:well|recovery|condolences|sympathies|best|love|thoughts)\b"
    r"|^Wishing (?:him|her|them|you|everyone|all|the [a-z]+|[A-Z][a-z]+(?: [A-Z][a-z]+)?) (?:a |the )?"
    r"(?:well|speedy|swift|full|quick|happy|best|luck|good luck|all the best)\b"
    r"|^(?:Best wishes|Get well soon|Thoughts and prayers|Rest in peace|RIP)\b",
    re.I,
)


def is_sentiment_closer(sentence: str) -> bool:
    text = plain(sentence).strip()
    if not text or text[0] in "\"“‘'":
        return False
    return bool(_SENTIMENT_CLOSER_RE.search(text))


def is_filler_closer(sentence: str) -> bool:
    """A moralising closing sentence that carries no reporting at all.

    Requires the summary subject ("This incident...") and a moralising
    phrase, and then that EVERY content word is generic commentary
    vocabulary, with no figure, quotation, attribution or explaining clause.
    A sentence with anything specific in it is kept whole."""
    sentence = plain(sentence)
    if not (_SUMMARY_SUBJECT_RE.search(sentence) and _MORALISING_RE.search(sentence)):
        return False
    if _FACT_MARK_RE.search(sentence) or _EXPLAINS_RE.search(sentence):
        return False
    words = re.findall(r"[a-z][a-z'’]*", sentence.lower().replace("’", "'"))
    return bool(words) and all(word in _BOILERPLATE_WORDS for word in words)


_MONTHS = ("January|February|March|April|May|June|July|August|September|"
           "October|November|December")
_US_DATE_RE = re.compile(
    r"\b(?:(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+)?"
    r"(" + _MONTHS + r")\s+(\d{1,2})(?:st|nd|rd|th)?\b(?:,?\s+(\d{4})\b)?"
)


_ORDINAL_DAY_RE = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th) (" + _MONTHS + r")\b")


def uk_dates(text: str) -> str:
    """'Tuesday, November 10' -> 'Tuesday 10 November'; 'November 8, 2026'
    -> '8 November 2026'. Day-first dates are left alone. Case-sensitive, so
    the verb 'may' is never touched."""
    def repl(m: re.Match[str]) -> str:
        weekday, month, day, year = m.group(1), m.group(2), m.group(3), m.group(4)
        if int(day) > 31 or int(day) == 0:
            return m.group(0)
        out = f"{day} {month}" + (f" {year}" if year else "")
        return f"{weekday} {out}" if weekday else out
    text = _US_DATE_RE.sub(repl, str(text or ""))
    # "4th August 1914" -> "4 August 1914" (v12 house style).
    return _ORDINAL_DAY_RE.sub(r"\1 \2", text)


def _quote_step(in_quote: bool, ch: str, prev: str, nxt: str) -> tuple[bool, bool]:
    """(new in_quote, is_quote_mark) for one character. Double and single
    marks, straight or curly; a single mark with a letter on both sides is an
    apostrophe (we're, park's), never a quotation mark."""
    if ch == "“":
        return True, True
    if ch == "”":
        return False, True
    if ch == '"':
        return (not in_quote), True
    if ch in "‘'":
        if prev.isalpha() and nxt.isalpha():
            return in_quote, False
        if not in_quote and not prev.isalnum() and nxt.isalnum():
            return True, True
        if ch == "‘":
            return in_quote, False
    if ch in "’'":
        if prev.isalpha() and nxt.isalpha():
            return in_quote, False
        if in_quote and prev and not prev.isspace() and not nxt.isalnum():
            return False, True
    return in_quote, False


def quote_open(text: str) -> bool:
    """Whether a quotation opened in text is still open at its end: the next
    words are someone else's (7 Nov 2026 review: 'The team is devastated.
    Our thoughts are with his family.' lost its second sentence)."""
    text = str(text or "")
    in_quote = False
    for i, ch in enumerate(text):
        in_quote, _ = _quote_step(in_quote, ch, text[i - 1] if i else "", text[i + 1] if i + 1 < len(text) else "")
    return in_quote


def uk_dates_outside_quotes(html_text: str) -> str:
    """uk_dates on the reporter's own words only. Text inside quotation marks
    (double or single, straight or curly) is someone else's words and is
    never altered, and nothing inside a tag (an href, an alt) is touched. An
    unclosed quote protects the rest of the text."""
    text = str(html_text or "")
    out: list[str] = []
    run: list[str] = []
    in_tag = in_quote = False

    def flush(convert: bool) -> None:
        if run:
            chunk = "".join(run)
            out.append(uk_dates(chunk) if convert else chunk)
            run.clear()

    for i, ch in enumerate(text):
        if in_tag:
            out.append(ch)
            if ch == ">":
                in_tag = False
            continue
        if ch == "<":
            flush(not in_quote)
            in_tag = True
            out.append(ch)
            continue
        now, mark = _quote_step(in_quote, ch, text[i - 1] if i else "", text[i + 1] if i + 1 < len(text) else "")
        if mark and now and not in_quote:
            flush(True)
            run.append(ch)
        elif mark and not now and in_quote:
            run.append(ch)
            flush(False)
        else:
            run.append(ch)
        in_quote = now
    flush(not in_quote)
    return "".join(out)


RIGHT_OF_REPLY_RE = re.compile(
    r"right (?:of|to) reply|\b(?:in|by way of) (?:a )?(?:response|reply)\b|\bresponded\b|"
    r"\b(?:said|says) in a statement\b|\bstatement (?:to|from) rochdale daily\b",
    re.I,
)


def _text_before(source: str, index: int) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", source[:index]))


def _keep_reporting(sentences: list[str], before: str) -> list[str]:
    """Drop filler and the paper's own sentiment from closing sentences, never
    a sentence that sits inside a quotation opened earlier in the paragraph or
    in an earlier one: those are someone else's words."""
    kept: list[str] = []
    context = before
    for sentence in sentences:
        quoted = quote_open(context)
        if quoted or not (is_filler_closer(sentence) or is_sentiment_closer(sentence)):
            kept.append(sentence)
        context += " " + sentence
    return kept


def tidy_editor_html(content_html: str) -> str:
    """House style for the editor's own articles, applied at render.

    Unlike tidy_content_html, paragraphs are never split or re-joined: the
    editor's paragraphing stands. Two things change: dates outside quotation
    marks go into UK order ("Saturday 7 November 2026"), and a moralising
    closing sentence made entirely of stock commentary (is_filler_closer) is
    dropped from the last two paragraphs. A right-of-reply paragraph, or any
    paragraph carrying someone's response, is left exactly as written."""
    source = str(content_html or "")
    spans = [m.span() for m in _P_RE.finditer(source)]
    closing = set(spans[-2:])

    def repl(match: re.Match[str]) -> str:
        whole, inner = match.group(0), match.group(1)
        if RIGHT_OF_REPLY_RE.search(plain(inner)):
            return whole
        fixed = uk_dates_outside_quotes(inner)
        if match.span() in closing and "<" not in fixed:
            sentences = split_sentences(html.unescape(fixed))
            kept = _keep_reporting(sentences, _text_before(source, match.start()))
            if not kept:
                return ""
            if len(kept) != len(sentences):
                fixed = html.escape(" ".join(kept), quote=False)
        if fixed == inner:
            return whole
        start, end = match.start(1) - match.start(), match.end(1) - match.start()
        return whole[:start] + fixed + whole[end:]

    # Lists and subheadings between paragraphs (the morning briefing's
    # bullets) get UK dates too.
    out, position = [], 0
    for match in _P_RE.finditer(source):
        out.append(uk_dates_outside_quotes(source[position:match.start()]))
        out.append(repl(match))
        position = match.end()
    out.append(uk_dates_outside_quotes(source[position:]))
    return "".join(out)


def tidy_paragraphs(paragraphs: Iterable[str]) -> list[str]:
    return split_long_paragraphs(strip_filler_openers(plain(p)) for p in paragraphs)


_P_RE = re.compile(r"<p\b[^>]*>(.*?)</p>", re.S | re.I)


def tidy_content_html(content_html: str) -> str:
    """Apply the paragraph rules to rendered HTML.

    Only plain paragraphs are touched. A paragraph holding inline markup
    (links, emphasis), or any other element (lists, figures, quotes, ad
    slots), is left exactly as it is, so nothing an editor or another pass
    put there is lost.
    """
    source = str(content_html or "")
    plain_spans = [m.span() for m in _P_RE.finditer(source) if "<" not in m.group(1)]
    closing = set(plain_spans[-2:])

    def repl(match: re.Match[str]) -> str:
        inner = match.group(1)
        if "<" in inner:
            return match.group(0)
        text = html.unescape(inner)
        fixed = html.unescape(uk_dates_outside_quotes(inner))
        if match.span() in closing:
            kept = _keep_reporting(split_sentences(fixed), _text_before(source, match.start()))
            if not kept:
                return ""
            fixed = " ".join(kept)
        pieces = tidy_paragraphs([fixed])
        if len(pieces) == 1 and pieces[0] == plain(text):
            return match.group(0)
        return "".join(f"<p>{html.escape(piece, quote=False)}</p>" for piece in pieces)

    return _P_RE.sub(repl, source)


def content_tokens(text: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9]+", plain(text).lower())
        if len(token) >= 4 and token not in _STOPWORDS
    }


def share_of(a: str, b: str) -> float:
    """Share of a's content words that already appear in b."""
    left, right = content_tokens(a), content_tokens(b)
    if len(left) < 4:
        return 0.0
    return len(left & right) / len(left)


def repetition_issues(excerpt: str, paragraphs: list[str]) -> list[str]:
    issues: list[str] = []
    body = [plain(p) for p in paragraphs if plain(p)]
    if excerpt and body and share_of(excerpt, body[0]) >= 0.55:
        issues.append(
            "The standfirst repeats paragraph 1. Make the standfirst add one fact "
            "the headline and first paragraph do not carry (a role, a figure, a "
            "consequence, what happens next)."
        )
    if len(body) >= 2:
        first_of_second = (split_sentences(body[1]) or [body[1]])[0]
        if share_of(first_of_second, body[0]) >= 0.7:
            issues.append(
                "Paragraph 2 restates paragraph 1. Every paragraph must add a new "
                "fact, quote or consequence."
            )
    return issues


def paragraph_length_issues(paragraphs: list[str]) -> list[str]:
    long_ones = [
        p for p in paragraphs
        if words(p) > MAX_PARAGRAPH_WORDS or len(split_sentences(p)) > MAX_PARAGRAPH_SENTENCES
    ]
    if long_ones:
        return [
            "Write short paragraphs for phone readers: one or two sentences and no "
            f"more than {MAX_PARAGRAPH_WORDS} words each."
        ]
    return []


def ai_tell_issues(text: str) -> list[str]:
    found = sorted({m.group(0).lower() for m in AI_TELL_RE.finditer(plain(text))})
    if found:
        return [
            "Cut filler that reads as machine-written and say the thing plainly: "
            + "; ".join(found)
        ]
    return []


def is_shouting(title: str) -> bool:
    letters = [c for c in title if c.isalpha()]
    caps_words = re.findall(r"\b[A-Z]{3,}\b", title)
    return bool(letters) and len(caps_words) >= 3 and sum(c.isupper() for c in letters) > 0.5 * len(letters)


def headline_issues(title: str, category: str = "", body: str = "") -> list[str]:
    issues: list[str] = []
    title = plain(title)
    if is_shouting(title):
        issues.append("Write the headline in sentence case, never capitals.")
    if "?" in title and (
        str(category or "").lower() in _QUESTION_UNSAFE_CATEGORIES
        or _QUESTION_UNSAFE_RE.search(title)
    ):
        issues.append(
            "State the news: no question headline on crime, court or police "
            "stories, where a question insinuates."
        )
    if CLICKBAIT_RE.search(title):
        issues.append("Remove the clickbait wording from the headline.")
    return issues


def social_headline_issues(social: str, title: str, category: str = "") -> list[str]:
    social = plain(social)
    if not social:
        return ["Write a social_headline for Facebook."]
    issues: list[str] = []
    if not SOCIAL_HEADLINE_MIN <= len(social) <= SOCIAL_HEADLINE_MAX:
        issues.append(
            f"Keep the social_headline between {SOCIAL_HEADLINE_MIN} and "
            f"{SOCIAL_HEADLINE_MAX} characters."
        )
    if social.casefold() == plain(title).casefold():
        issues.append(
            "Make the social_headline different from the headline: lead with the "
            "person and the human stake, as a neighbour would tell it."
        )
    issues.extend(
        issue.replace("headline", "social_headline", 1)
        for issue in headline_issues(social, category)
    )
    return issues


def clean_social_headline(value: Any, title: str = "") -> str:
    """The stored social headline, or '' when it fails a hard rule. The
    publisher then uses the article headline: the same verified words."""
    social = plain(value)
    if not social or headline_issues(social) or len(social) > SOCIAL_HEADLINE_MAX + 20:
        return ""
    if social.casefold() == plain(title).casefold():
        return ""
    return social
