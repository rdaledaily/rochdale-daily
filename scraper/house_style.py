from __future__ import annotations

import re
from typing import Any

STYLE_VERSION = "rochdale-precision-desk-v7"

HOUSE_STYLE_SYSTEM = (
    "You are the senior news editor of Rochdale Daily. Write accurate, polished British local journalism. "
    "Lexical precision is paramount: choose the most exact ordinary noun, verb and adjective supported by the "
    "evidence. Never choose a grander synonym merely because it sounds more literary. Prefer 'called' to 'summoned', "
    "'died at the scene' to 'was pronounced dead at the location', 'fire' to 'blaze' unless the source uses that "
    "description, 'person' to 'individual', and 'detectives are investigating' to 'detectives are working diligently'. "
    "Use 'suspect' only when a source uses that term; an arrest alone does not justify it. Use a person's relationship "
    "or role — such as mother, teacher, councillor or officer — only when the evidence establishes it. "
    "Apply strict first-reference grammar to unidentified people. Introduce the exact noun with an indefinite "
    "article before using its definite form: write 'A woman was pronounced dead at the scene' before any later "
    "reference to 'the woman'; write 'a man' before 'the man', 'a person' before 'the person', and "
    "'a mother' before 'the mother'. A different role noun does not license a definite gender noun: after "
    "'a mother', write 'a woman' before later writing 'the woman'. Never begin an unidentified person's "
    "reference with 'the woman', 'the man', 'the person', 'the mother' or 'the father'. "
    "Avoid emotive modifiers such as 'harrowing', 'profound', 'close-knit', 'shocking', 'tragic' or 'devastating' "
    "unless they appear in an attributed quotation or are indispensable to an accurate description. Report a death "
    "plainly and respectfully. Do not manufacture atmosphere. "
    "Lead with the strongest verified development. Use active verbs, accurate attribution and natural sentence "
    "structure. Retain relevant local context, but do not invent community reaction, concern, meetings, safety "
    "measures, business effects or official plans. A practical local-impact paragraph may explain likely effects on "
    "journeys, services, families or businesses only when those effects follow reasonably from the verified facts, "
    "and must use measured language such as 'may', 'could', 'is likely to' or 'will mean'. "
    "For police matters, do not say officers are appealing for witnesses unless the evidence records an appeal. "
    "ONLY in a report about a crime, a police investigation or a court case may Rochdale Daily add this service "
    "sentence, without treating it as a police statement: 'Anyone with information can find Greater Manchester "
    "Police and Crimestoppers contact details at the end of this article.' It must NEVER appear in any other kind "
    "of story: never in community, business, sport, education, health, events or human-interest reports. "
    "ONLY in a report of a death may Rochdale Daily close with: 'Our thoughts are with the family and all those "
    "affected.' This is an editorial expression of sympathy, not a factual claim, and it must never appear in a "
    "story where nobody has died. "
    "Never state or imply that a venue, organisation or event is in Rochdale or the borough unless the supplied "
    "records establish that location; a familiar-sounding venue name is not evidence of where it is. "
    "Never predict a council meeting, policy response, safety review, new measure or future announcement. "
    "Never claim residents posted condolences, expressed shock or rallied around a family unless attributable source "
    "material explicitly supports that statement. "
    "Use UK spelling and punctuation. Preserve the exact distinction between allegation, arrest, charge, conviction "
    "and sentence. Never invent a quotation, identity, age, date, figure, place, relationship, injury, cause, motive, "
    "official response or outcome. Never identify a protected child or sexual-offence complainant. "
    "A headline should normally contain 6-14 words and state the development directly. The standfirst should be one "
    "clear sentence of roughly 20-45 words. Match the length budget supplied with each assignment: it reflects how "
    "much verified source material exists. A rich source supports a full report; a thin source supports only a "
    "short, accurate brief of four tight paragraphs. Never pad towards a word count with unsupported reaction, "
    "trends, background or speculation — a short true report always beats a long invented one. "
    "Use only the supplied source evidence."
)

WEAK_STYLE_RE = re.compile(
    r"\b(?:"
    r"working diligently|"
    r"piece together the events leading up to|"
    r"summoned to the scene|"
    r"the blaze erupted|"
    r"pronounced dead at the location|"
    r"in the aftermath of|"
    r"at this time|"
    r"profound shock and sorrow|"
    r"harrowing time|"
    r"close-knit nature|"
    r"raised significant concerns|"
    r"prompting (?:local )?residents to voice|"
    r"prompting discussions among (?:local )?residents|"
    r"residents have (?:voiced|expressed) (?:their )?concerns?|"
    r"many have called for|"
    r"adds? to a (?:growing|troubling) (?:list|trend)|"
    r"part of a (?:growing|troubling) trend|"
    r"sparked (?:widespread )?(?:concern|debate) among|"
    r"community vigilance|"
    r"actively appealing|"
    r"actively monitoring|"
    r"local authorities will implement|"
    r"local council is expected to convene|"
    r"further details .* will be announced in the coming days|"
    r"residents are advised|"
    r"stay informed|"
    r"it is important to note|"
    r"it is essential"
    r")\b",
    re.IGNORECASE,
)

GENERIC_HEADLINE_RE = re.compile(
    r"^(?:traffic update|weather update|latest update|community update|breaking)\s*:",
    re.IGNORECASE,
)

PROMOTIONAL_RE = re.compile(
    r"(?:!{2,}|\b(?:fantastic|amazing|stunning|unmissable|incredible|epic)\b)",
    re.IGNORECASE,
)


def _plain(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def exact_style_matches(draft: dict[str, Any]) -> list[str]:
    title = _plain(draft.get("title"))
    excerpt = _plain(draft.get("excerpt"))
    paragraphs = [_plain(item) for item in draft.get("paragraphs") or [] if _plain(item)]
    combined = " ".join([title, excerpt, *paragraphs])

    matches = {
        match.group(0)
        for pattern in (WEAK_STYLE_RE, PROMOTIONAL_RE)
        for match in pattern.finditer(combined)
    }
    if GENERIC_HEADLINE_RE.search(title):
        matches.add(title.split(":", 1)[0] + ":")
    return sorted(matches, key=str.casefold)



FIRST_REFERENCE_NOUNS = ("woman", "man", "person", "mother", "father")


def first_reference_issues(draft: dict[str, Any]) -> list[str]:
    """Require the same anonymous-person noun to be introduced indefinitely first."""
    paragraphs = [_plain(item) for item in draft.get("paragraphs") or [] if _plain(item)]
    body = " ".join(paragraphs)
    issues: list[str] = []

    for noun in FIRST_REFERENCE_NOUNS:
        definite = re.search(rf"\bthe\s+{noun}\b", body, re.IGNORECASE)
        if not definite:
            continue

        preceding = body[:definite.start()]
        indefinite_pattern = re.compile(
            rf"\b(?:a|an|one)\s+"
            rf"(?:(?:young|elderly|local|adult|unidentified|injured|arrested|deceased)\s+|"
            rf"(?:\d{{1,3}}-year-old)\s+)*"
            rf"{noun}\b",
            re.IGNORECASE,
        )
        if not indefinite_pattern.search(preceding):
            issues.append(
                f"Introduce the unidentified person as 'a {noun}' before referring to 'the {noun}'."
            )

    return issues


def style_issues(draft: dict[str, Any], source_kind: str = "") -> list[str]:
    title = _plain(draft.get("title"))
    excerpt = _plain(draft.get("excerpt"))
    paragraphs = [_plain(item) for item in draft.get("paragraphs") or [] if _plain(item)]
    issues: list[str] = []

    exact = exact_style_matches(draft)
    if exact:
        issues.append(
            "Replace these imprecise or formulaic expressions with exact ordinary language: "
            + "; ".join(exact)
        )
    if GENERIC_HEADLINE_RE.search(title):
        issues.append("Replace the labelled headline with a specific news headline.")
    if (
        source_kind != "live"
        and ":" in title
        and len(title.split(":", 1)[0].split()) <= 3
    ):
        # Live-page content (weather forecasts, travel alerts) conventionally
        # uses exactly this "Location/topic: detail" headline shape — "Rochdale
        # weather: sunny spells and light winds" is correct style for a
        # forecast, not a lazy generic label, so the check does not apply here.
        issues.append("Avoid a generic label followed by a colon in the headline.")
    if sum(1 for paragraph in paragraphs if paragraph.lower().startswith("this ")) >= 3:
        issues.append("Replace repetitive 'This...' openings with specific subjects.")
    if len(excerpt.split()) > 55:
        issues.append("Tighten the standfirst to one clear sentence.")
    issues.extend(first_reference_issues(draft))
    return list(dict.fromkeys(issues))
