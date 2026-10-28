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
    r"a reminder of|underscor(?:e|es|ing)|highlights? the importance"
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

    def repl(match: re.Match[str]) -> str:
        inner = match.group(1)
        if "<" in inner:
            return match.group(0)
        text = html.unescape(inner)
        pieces = tidy_paragraphs([text])
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
