"""Reader-first reporting prompts for Rochdale Daily.

This is a reporting guide, not a source of facts or a compulsory article outline.
The newsroom must not add invented information to satisfy a checklist.
"""
from __future__ import annotations


READER_FIRST_POLICY = (
    "Reader-first test: answer what has actually happened, the precise local place "
    "and time where established, who is affected, what they can practically do, "
    "the most useful supporting evidence or comparison, and what happens next "
    "if a next step is confirmed. Every detail must be supported by the source "
    "records or a directly identified authoritative document. Never guess a "
    "time, price, service status, road diversion, eligibility rule, official response "
    "or contact number. Attribute disputed facts. "
    "Prioritise the reader's actual question rather than repeating the announcement; "
    "one useful specific detail is worth three paragraphs of generic context. "
    "The headline and standfirst should match the main question a local reader "
    "would type into search, in natural language, not keyword stuffing. "
    "Use concise meaningful subheadings only when they help readers scan a "
    "substantial report. Never turn every story into the same FAQ or force an "
    "identical list of sections. A thin source warrants a short brief and an "
    "honest account of what is not confirmed. Add useful links and official "
    "contact routes only where verified and permitted by the publishing format. "
    "Never manufacture public reaction, promises, advice or reporting. "
    "Lead with the main verified finding, its local consequence and any confirmed "
    "deadline; do not withhold the answer behind a teaser. For continuing issues, "
    "compare the latest document with earlier coverage, distinguish a promise "
    "from delivery, and state whose response is recorded. Original reporting "
    "requires actual evidence gathering; never label a source rewrite as an "
    "interview or investigation. Prefer updating the existing canonical story "
    "when there is no materially separate development. Preserve uncertainty "
    "rather than adding a list of unverified practical details."
)


COMMON_QUESTIONS = (
    "What happened, and what is the latest confirmed development?",
    "Who is involved: full names and roles of the people and organisations, as the source gives them?",
    "Exactly where and when did it happen, if established (street, place, town; day and date)?",
    "How and why did it happen, according to the source?",
    "Who is affected locally, and what difference does it make?",
    "What is known from verifiable sources, and what remains uncertain?",
    "What is the next confirmed step, deadline or update, if any?",
)

QUESTIONS_BY_DESK: dict[str, tuple[str, ...]] = {
    "traffic": (
        "Which named road, stretch, junction and direction are affected?",
        "What are the confirmed start and end times, diversions, and access arrangements?",
        "Are any bus routes or parking restrictions affected, according to the source?",
        "Where can travellers check authoritative current conditions?",
    ),
    "transport": (
        "Which numbered services, stops, stations or journeys are affected?",
        "When does the change apply, and how long is it expected to last?",
        "What verified alternative routes, ticket options or operator updates exist?",
    ),
    "politics": (
        "Which council decision, proposal, vote or spending figure is documented?",
        "How much public money is involved, over what period, and compared with what baseline?",
        "What exactly is decided, proposed or disputed, and whose response is recorded?",
        "When is the next confirmed vote, deadline or consultation opportunity?",
    ),
    "education": (
        "Which school, year group or service is affected?",
        "What are the relevant dates, eligibility rules and educational consequences?",
        "What do inspection reports, published figures or formal decisions actually establish?",
        "What practical support or appeal route is confirmed, where relevant?",
    ),
    "health": (
        "Which named service, facility or group of patients is affected?",
        "What hours, access changes or eligibility criteria are verified?",
        "What does official health guidance say? Avoid clinical speculation.",
    ),
    "crime": (
        "What exactly have police or courts confirmed, and when?",
        "Are the people involved arrested, charged, convicted or merely alleged?",
        "Is an appeal for information actually being made, and by whom?",
        "Protect victims, personal details and all legally restricted identities.",
    ),
    "business": (
        "Where is the business, and what has opened, closed or changed?",
        "Are opening hours, prices, services, contact details or jobs verified?",
        "What is distinctive or relevant to customers rather than merely promotional?",
    ),
    "events": (
        "What is happening, where, on which date, and at what time?",
        "Are tickets, costs, age limits, accessibility and booking requirements confirmed?",
        "What is the official source for current arrangements?",
    ),
    "community": (
        "Who is organising the activity and who can benefit?",
        "Where and when can people attend, volunteer or seek help?",
        "Are registration requirements, costs, donations and contact details verified?",
    ),
    "environment": (
        "Which site, waterway or neighbourhood is affected?",
        "What measured findings, dates, units or official records substantiate the claim?",
        "What practical advice or next action is supported by an authoritative body?",
    ),
    "sport": (
        "Which teams or competitors, what result and which competition?",
        "What does the result mean for the table or next fixture, if verified?",
        "Are fixture date, venue, tickets and availability confirmed?",
    ),
    "news": (
        "What is materially new compared with the earlier public announcement?",
        "What specific borough impact or verifiable context makes this worth reading?",
    ),
}


def reader_questions_for(category: str = "", source_kind: str = "") -> list[str]:
    """Return a short desk-specific assignment guide, never requirements for facts."""
    desk = str(category or "news").strip().lower().replace("_", " ")
    if desk in {"transport", "trains", "buses"}:
        desk = "transport"
    elif desk in {"roadworks", "road closures"}:
        desk = "traffic"
    elif desk in {"council", "accountability", "investigations"}:
        desk = "politics"
    elif desk in {"arts", "culture"}:
        desk = "community"
    elif desk not in QUESTIONS_BY_DESK:
        desk = "news"
    questions = list(COMMON_QUESTIONS) + list(QUESTIONS_BY_DESK[desk])
    if str(source_kind or "").lower() in {"live", "breaking"}:
        questions.append("Which information is current and timestamped, and what remains unconfirmed?")
    return questions

