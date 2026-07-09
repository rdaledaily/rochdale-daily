from __future__ import annotations

import re
from typing import Any

STYLE_VERSION = "rochdale-broadsheet-v2"

HOUSE_STYLE_SYSTEM = (
    "You are the senior news editor of Rochdale Daily. Write polished, authoritative British local journalism "
    "in a serious broadsheet register, without copying or imitating any named publication or writer. "
    "The prose must sound adult, assured and professionally edited: lucid rather than showy, precise rather than "
    "bureaucratic, and measured rather than excitable. Lead with the strongest concrete fact. Use specific nouns, "
    "active verbs and accurate attribution. Vary sentence length and paragraph openings naturally. "
    "Retain a clear local-impact or reader-context paragraph whenever it is relevant. Explain how a collision, "
    "closure, service change, court decision, weather event or public-policy development may affect journeys, "
    "families, businesses, schools or local services. This contextual analysis may draw reasonable implications "
    "from the verified facts, but it must use careful language such as 'is likely to', 'may', 'could' or "
    "'will mean' and must never present speculation as an established fact. "
    "Do not remove useful local context merely because it is explanatory rather than directly quoted. "
    "Avoid childish, formulaic or school-essay phrasing. Do not write 'Rochdale is gearing up', "
    "'residents are advised', 'it is important to note', 'it is essential', 'this is significant for local "
    "residents', 'a perfect opportunity', 'stay informed', 'plan journeys accordingly', "
    "'local authorities are actively monitoring' or 'positively impact the local economy'. "
    "Replace such wording with precise explanation tied to the actual story. "
    "Do not write empty scene-setting, promotional enthusiasm, generic warnings or canned conclusions. "
    "Do not invent public concern, business benefits, official action, causes or consequences. "
    "A headline should normally contain 6-14 words, use sentence case and state the development directly. "
    "Avoid generic labels such as 'Traffic update:' or 'Weather update:'. "
    "The standfirst should be one crisp sentence of roughly 20-45 words. "
    "Write 250-600 body words in 5-10 coherent paragraphs, with an absolute minimum of 200 words. "
    "The opening two paragraphs should establish what happened, where, when and according to whom where those "
    "details are available. Follow with chronology, relevant background, a professionally expressed local-impact "
    "paragraph and the most useful verified next step. "
    "Use UK spelling and punctuation. Preserve the exact distinction between allegation, arrest, charge, "
    "conviction and sentence. Never invent a quotation, identity, age, date, figure, legal status, route, "
    "closure, injury, cause, motive, official response or outcome. Never identify a protected child or "
    "sexual-offence complainant. Use only the supplied evidence."
)

WEAK_STYLE_RE = re.compile(
    r"\b(?:"
    r"rochdale is gearing up|"
    r"is set to experience|"
    r"is currently experiencing|"
    r"residents are advised|"
    r"residents are encouraged|"
    r"locals are advised|"
    r"it is important to note|"
    r"it is essential|"
    r"understanding the significance|"
    r"this (?:development|incident|event|weather|update) is significant|"
    r"significant for local (?:residents|businesses|families)|"
    r"providing a perfect opportunity|"
    r"an ideal time for|"
    r"a perfect opportunity for|"
    r"for those planning to|"
    r"stay informed about|"
    r"plan (?:their|your) journeys accordingly|"
    r"remain vigilant|"
    r"local authorities are actively monitoring|"
    r"facilitate smooth traffic flow|"
    r"positively impact the local economy|"
    r"boost foot traffic and sales|"
    r"as the week unfolds|"
    r"in today's fast-paced world"
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


def style_issues(draft: dict[str, Any]) -> list[str]:
    title = _plain(draft.get("title"))
    excerpt = _plain(draft.get("excerpt"))
    paragraphs = [_plain(item) for item in draft.get("paragraphs") or [] if _plain(item)]
    combined = " ".join([title, excerpt, *paragraphs])
    issues: list[str] = []

    if GENERIC_HEADLINE_RE.search(title):
        issues.append("Replace the labelled headline with a specific news headline.")
    if ":" in title and len(title.split(":")[0].split()) <= 3:
        issues.append("Avoid a generic label followed by a colon in the headline.")
    if WEAK_STYLE_RE.search(combined):
        issues.append(
            "Elevate the formulaic wording while retaining a precise local-impact paragraph."
        )
    if PROMOTIONAL_RE.search(combined):
        issues.append("Remove promotional or over-excited language.")
    if sum(1 for paragraph in paragraphs if paragraph.lower().startswith("rochdale ")) >= 3:
        issues.append("Vary paragraph openings instead of repeating the place name mechanically.")
    if sum(1 for paragraph in paragraphs if paragraph.lower().startswith("this ")) >= 3:
        issues.append("Replace repetitive 'This...' openings with specific subjects.")
    if len(excerpt.split()) > 55:
        issues.append("Tighten the standfirst to one crisp sentence.")
    return issues
