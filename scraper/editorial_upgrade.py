from __future__ import annotations

import html
import json
import re
from collections import Counter
from typing import Any

from house_style import HOUSE_STYLE_SYSTEM, STYLE_VERSION, style_issues

CATEGORY_ORDER = (
    ("crime", re.compile(
        # Tokens must carry criminal CONTEXT. Bare "charge" classified a
        # children's Bookstart event as crime because its body said
        # "free of charge"; bare "court" matches street names and tennis
        # courts. Weak words are now bound to legal phrasing.
        r"\b(?:rape|rapist|sexual assault|sexual offence|sexual abuse|grooming|"
        r"murder|manslaughter|burglary|robbery|theft|fraud|stabbing|"
        r"shooting|arrested?|convicted|sentenced?|jailed|"
        r"charged with|charges? (?:of|against)|faces? charges?|on charges?|"
        r"(?:weapons?|assault|drugs?|criminal|fraud) charges?|"
        r"pleads? (?:not )?guilty|"
        r"(?:crown|magistrates|county) court|court (?:hearing|case|appearance|proceedings)|"
        r"appeared? (?:at|in|before) (?:the )?court|"
        r"police|wanted person|appeal for witnesses|"
        r"(?:police )?investigation (?:launched|underway|ongoing)|police investigation|"
        r"attacks? (?:on|against) (?:a |an )?\w+|child attacks?|"
        r"criminal behaviour order|drugs raid|cannabis farm|deportation|parole)\b",
        re.I,
    )),
    ("traffic", re.compile(
        r"\b(?:traffic|roadworks?|road works?|road closure|road closed|lane closure|"
        r"lane closed|collision|crash|motorway incident|congestion|diversion|"
        r"temporary traffic lights|potholes?|speeding|M62|A627(?:\(M\))?|"
        r"junction\s+(?:19|20|21)|carriageway)\b",
        re.I,
    )),
    ("transport", re.compile(
        r"\b(?:bus(?:es)?|train|railway|tram|metrolink|Bee Network|station|"
        r"timetable|public transport|Northern Rail|service disruption)\b",
        re.I,
    )),
    ("politics", re.compile(
        r"\b(?:councillor|council budget|council tax|election|cabinet|mayor|"
        r"parliament|MP\b|motion|manifesto|government policy|legislation)\b",
        re.I,
    )),
    ("education", re.compile(
        r"\b(?:school|academy|college|university|Ofsted|teacher|pupil|student|"
        r"GCSE|A[- ]level|education|headteacher)\b",
        re.I,
    )),
    ("health", re.compile(
        r"\b(?:NHS|hospital|doctor|GP\b|clinic|health service|mental health|"
        r"patient|care service|pharmacy|vaccination|fitness|exercise (?:class(?:es)?|session(?:s)?)|workout|body combat|zumba|cardiovascular|wellbeing)\b",
        re.I,
    )),
    ("community", re.compile(
        r"\b(?:community pantry|pantry|food bank|foodbank|charity|fundraiser|"
        r"fundraising|volunteer|donation|support group|community group|"
        r"family support|local families|neighbourhood project|hidden hero|"
        r"protests?|protesters?|demonstration|petition|campaigners?|"
        r"safe haven|drop[- ]in|warm space|community centres?|support services?)\b",
        re.I,
    )),
    ("business", re.compile(
        r"\b(?:business|company|shop|restaurant|pub|takeaway|investment|"
        r"regeneration|commercial|retail|opening|closure|apartments?|development)\b",
        re.I,
    )),
    ("environment", re.compile(
        r"\b(?:flood|weather warning|pollution|recycling|litter|climate|wildlife|"
        r"reservoir|canal|environmental|nature reserve|green space|country park|"
        r"heatwave|met office|weather forecast|sunny|sunshine|rainfall|showers|"
        r"asbestos|contaminated|contamination|derelict|brownfield|"
        r"factory site|abandoned (?:site|factory|mill|works|land|building))\b",
        re.I,
    )),
    ("sport", re.compile(
        r"\b(?:Rochdale AFC|Rochdale Hornets|football|rugby|cricket|boxing|"
        r"athletics|parkrun|netball|MMA|Muay Thai|fixture|match|league|cup tie|"
        r"goalkeeper|striker|coach|tournament|sports? clubs?|tennis|badminton|pickleball|squash|basketball|paddle sport)\b",
        re.I,
    )),
    ("events", re.compile(
        r"\b(?:festival|concert|gig|exhibition|performance|parade|fair|"
        r"ticketed event|what'?s on|open day|coffee morning|reform club event)\b",
        re.I,
    )),
)

DEFAULT_CATEGORY_MINIMUMS = {
    "crime": 4,
    "traffic": 4,
    "transport": 3,
    "politics": 2,
    "education": 2,
    "sport": 3,
    "events": 3,
    "business": 2,
    "community": 3,
    "health": 2,
    "environment": 2,
    "news": 2,
}

CRIME_INCIDENT_RE = re.compile(
    r"\b(?:investigation|investigating|arrest(?:ed|s)?|charged with|charges? (?:of|against|brought)|faces? charges|assault(?:ed)?|"
    r"attack(?:s|ed)?|offences?|in court|court hearing|sentenc(?:ed|ing)|"
    r"appeal for (?:information|witnesses)|witness appeal|robbery|burglar(?:y|ies)|"
    r"theft|stolen|stabbing|murder|manslaughter|rape|wanted (?:man|woman)|"
    r"missing (?:person|man|woman|teenager|child))\b",
    re.I,
)

GENERIC_COPY_RE = re.compile(
    r"\b(?:the update was published by|has been categorised as|"
    r"further confirmed information will be added|the source item is titled|"
    r"this automated brief|readers can use the source link|"
    r"the article remains open to correction)\b",
    re.I,
)

STOPWORDS = {
    "about", "after", "again", "against", "also", "among", "because", "before",
    "being", "between", "could", "from", "have", "into", "latest", "local",
    "more", "news", "over", "said", "says", "that", "their", "there", "these",
    "they", "this", "through", "today", "under", "update", "updates", "what",
    "when", "where", "which", "with", "would", "will", "rochdale", "greater",
    "manchester", "source", "report", "reports", "reported",
}


def plain_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def deterministic_category(value: Any, fallback: str = "news") -> str:
    text = plain_text(value)
    if re.search(r"\b(?:kirkholt pantry|community pantry|food bank|foodbank|pantry)\b", text, re.I):
        return "community"
    # Score every category by DISTINCT matched terms and pick the strongest,
    # using the priority order only to break ties. First-match-wins misfiled
    # a live football report as traffic because one paragraph advised fans
    # about matchday congestion: 2 traffic tokens outranked 4 sport tokens
    # purely because traffic sits earlier in the list.
    best_category = ""
    best_score = 0
    scores: dict[str, int] = {}
    for category, pattern in CATEGORY_ORDER:
        # Multiword phrases ("safe haven", "food bank", "factory site") are
        # far less ambiguous than single words, so they count double.
        terms = {match.group(0).lower() for match in pattern.finditer(text)}
        score = sum(2 if " " in term else 1 for term in terms)
        scores[category] = score
        if score > best_score:
            best_category = category
            best_score = score
    # Crime carries the heaviest visual and legal weight on the site, so a
    # tie must never default to it: crime wins only when it OUTSCORES every
    # other category. On a tie, the strongest non-crime category takes it.
    if best_category == "crime" and any(
        score == best_score for cat, score in scores.items() if cat != "crime"
    ):
        best_category = next(
            cat for cat, _ in CATEGORY_ORDER
            if cat != "crime" and scores[cat] == best_score
        )
    # A story already filed as crime that describes a genuine incident or
    # police process must stay crime, whatever else its text mentions. A
    # child-attacks investigation was reclassified as community because
    # "local families" outweighed the single crime keyword "police".
    # Incidental police mentions (a welfare scheme the police support)
    # carry no incident marker, so those can still be re-filed.
    if str(fallback or "").lower() == "crime" and CRIME_INCIDENT_RE.search(text):
        return "crime"
    # A single ambiguous word ("opening", "school", "police") must never
    # override a category the pipeline already assigned. One incidental
    # keyword filed an asbestos-factory story under education ("school
    # holidays") and a Safe Haven welfare launch under business ("opening").
    # Overriding an existing category requires at least two points of
    # evidence; a lone keyword only decides genuinely uncategorised text.
    clean = str(fallback or "news").lower()
    known = {item[0] for item in CATEGORY_ORDER}
    if (
        best_score < 2
        and clean in known
        and best_category != clean
        and scores.get(clean, 0) > 0
    ):
        # Keep the assigned category only while it retains SOME textual
        # support. A pickleball participation story stayed "crime" because
        # nothing scored 2+, even though crime scored zero: a category with
        # no evidence at all must never beat a challenger that has some.
        return clean
    if best_category:
        return best_category
    return clean if clean in known | {"news"} else "news"


def article_word_count(article: dict[str, Any]) -> int:
    body = plain_text(article.get("content_html") or article.get("excerpt") or article.get("summary"))
    return len(re.findall(r"\b[\w’'-]+\b", body))


def normalise_draft(draft: Any) -> dict[str, Any]:
    if not isinstance(draft, dict):
        return {}
    clean = dict(draft)
    clean["title"] = plain_text(clean.get("title"))[:160]
    paragraphs: list[str] = []
    seen: set[str] = set()
    for raw in clean.get("paragraphs") or []:
        paragraph = plain_text(raw)
        key = paragraph.casefold()
        if not paragraph or key in seen:
            continue
        seen.add(key)
        paragraphs.append(paragraph)
        if len(paragraphs) >= 12:
            break
    clean["paragraphs"] = paragraphs
    excerpt = plain_text(clean.get("excerpt"))[:360]
    if len(excerpt.split()) < 18 and paragraphs:
        excerpt = plain_text(" ".join(paragraphs[:2]))[:360]
        if len(excerpt) >= 355 and " " in excerpt:
            excerpt = excerpt.rsplit(" ", 1)[0].rstrip(" ,;:-") + "…"
    clean["excerpt"] = excerpt
    return clean


def draft_word_count(draft: dict[str, Any]) -> int:
    return len(re.findall(
        r"\b[\w’'-]+\b",
        " ".join(str(item or "") for item in draft.get("paragraphs") or []),
    ))


def source_word_count(source_text: str) -> int:
    return len(re.findall(r"\b[\w’'-]+\b", plain_text(source_text)))


# A source rich enough to support a full-length report.
RICH_SOURCE_WORDS = 320


def length_budget(source_text: str) -> tuple[int, int]:
    """Return (minimum, maximum) body words supported by the source material.

    The previous fixed 200-word floor forced fabrication: given a 40-word
    police snippet and the instruction "expand to at least 200 body words",
    the model's only way to comply was to invent residents' concerns, trends
    and calls for action — which is exactly what reached the live site. The
    budget now scales with the evidence: a rich source keeps the original
    200-word floor and 900-word ceiling; a thin source gets a short-brief
    budget, and the CEILING becomes the enforcement point, so padding a thin
    story is a quality failure rather than a quality requirement.
    """
    words = source_word_count(source_text)
    if words >= RICH_SOURCE_WORDS:
        return 200, 900
    floor = max(50, int(words * 0.6))
    cap = min(900, max(floor + 60, int(words * 1.5)))
    return floor, cap


def contains_long_verbatim_phrase(output: str, source: str, words: int = 20) -> bool:
    out_words = re.findall(r"[a-z0-9]+", plain_text(output).lower())
    src_words = re.findall(r"[a-z0-9]+", plain_text(source).lower())
    if len(out_words) < words or len(src_words) < words:
        return False
    source_runs = {
        tuple(src_words[index:index + words])
        for index in range(len(src_words) - words + 1)
    }
    return any(
        tuple(out_words[index:index + words]) in source_runs
        for index in range(len(out_words) - words + 1)
    )


def quality_issues(draft: Any, source_text: str) -> list[str]:
    clean = normalise_draft(draft)
    if not clean:
        return ["The model did not return an article object."]
    if not bool(clean.get("publishable")):
        return ["The model marked the story unpublishable."]

    title = clean.get("title") or ""
    excerpt = clean.get("excerpt") or ""
    paragraphs = clean.get("paragraphs") or []
    combined = plain_text(" ".join([title, excerpt, *paragraphs]))
    issues: list[str] = []

    if len(title.split()) < 4 or len(title.split()) > 26:
        issues.append("Write a specific complete headline of 4-26 words.")
    if len(excerpt.split()) < 15:
        issues.append("Write a useful standfirst.")
    if len(paragraphs) < 4:
        issues.append("Use at least four substantive paragraphs.")
    words = draft_word_count(clean)
    floor, cap = length_budget(source_text)
    if words < floor:
        issues.append(
            f"Write at least {floor} body words using only facts already "
            f"present in the sources; the draft currently has {words}."
        )
    if words > cap:
        issues.append(
            f"Tighten the report to fewer than {cap} body words. The source "
            "material only supports a short report; cut every sentence that "
            "is not directly supported by the supplied evidence."
        )
    if GENERIC_COPY_RE.search(combined):
        issues.append("Remove publishing-process language and report the story itself.")

    # A preposition running straight into punctuation means the model left a
    # date, time or place blank ("the first session set to take place on .").
    if re.search(r"\b(?:on|at|from|until|between|by)\s*[.,;:]", combined):
        issues.append(
            "Complete or remove the sentence with a missing date, time or "
            "place; never leave a preposition hanging before punctuation."
        )

    # The headline must describe the same story as the body. A published
    # example: headline about indoor five-a-side football sessions on a body
    # entirely about back-care yoga at the same venue.
    title_tokens = {
        token for token in re.findall(r"[a-z0-9-]+", title.lower())
        if len(token) >= 4 and token not in STOPWORDS
    }
    body_tokens = set(re.findall(r"[a-z0-9-]+", " ".join([excerpt, *paragraphs]).lower()))
    if len(title_tokens) >= 4:
        present = len(title_tokens & body_tokens)
        if present / len(title_tokens) < 0.6:
            issues.append(
                "Align the headline with the report: most of its key words "
                "never appear in the body, so the headline and body describe "
                "different stories."
            )

    source_tokens = {
        token for token in re.findall(r"[a-z0-9]+", source_text.lower())
        if len(token) >= 4 and token not in STOPWORDS
    }
    output_tokens = {
        token for token in re.findall(r"[a-z0-9]+", combined.lower())
        if len(token) >= 4 and token not in STOPWORDS
    }
    if len(source_tokens) >= 4 and len(source_tokens & output_tokens) < 3:
        issues.append("Ground the report more clearly in the supplied facts.")
    if contains_long_verbatim_phrase(combined, source_text, 20):
        issues.append("Rewrite the long verbatim source passage.")
    issues.extend(style_issues(clean))
    return issues


def enrich_records(
    records: list[dict[str, Any]],
    fetch_metadata,
    canonicalise_url,
    source_is_denied,
    logger,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in records[:12]:
        record = dict(raw)
        url = canonicalise_url(str(record.get("url") or ""))
        key = url or plain_text(record.get("title")).casefold()
        if not key or key in seen:
            continue
        seen.add(key)

        current_body = plain_text(record.get("body_excerpt"))
        current_summary = plain_text(record.get("summary"))
        if url and len(current_body) < 700 and not source_is_denied(str(record.get("name") or ""), url):
            try:
                metadata = fetch_metadata(url)
                richer_body = plain_text(metadata.get("body_excerpt"))
                richer_summary = plain_text(metadata.get("description"))
                richer_title = plain_text(metadata.get("title"))
                if richer_title and len(richer_title) > len(str(record.get("title") or "")):
                    record["title"] = richer_title
                if len(richer_summary) > len(current_summary):
                    record["summary"] = richer_summary
                if len(richer_body) > len(current_body):
                    record["body_excerpt"] = richer_body
                resolved = canonicalise_url(str(metadata.get("url") or url))
                if resolved:
                    record["url"] = resolved
            except Exception as exc:
                logger.debug("Source enrichment unavailable for %s: %s", url, exc)
        enriched.append(record)
    return enriched


def compact_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    total = 0
    for raw in records[:12]:
        record = dict(raw)
        record["title"] = plain_text(record.get("title"))[:300]
        record["summary"] = plain_text(record.get("summary"))[:2200]
        record["body_excerpt"] = plain_text(record.get("body_excerpt"))[:5200]
        size = len(json.dumps(record, ensure_ascii=False))
        if compacted and total + size > 32000:
            break
        compacted.append(record)
        total += size
    return compacted


def request_article(
    *,
    client,
    model: str,
    schema: dict[str, Any],
    candidate,
    source_records: list[dict[str, Any]],
    social_context: list[dict[str, Any]],
    source_text: str,
    sensitive: bool,
    right_to_reply_email: str,
    logger,
) -> dict[str, Any] | None:
    system_message = HOUSE_STYLE_SYSTEM
    floor, cap = length_budget(source_text)

    base_payload = {
        "primary_source": getattr(candidate, "source_name", ""),
        "primary_url": getattr(candidate, "source_url", ""),
        "source_published_at": getattr(candidate, "source_published_at", ""),
        "detected_area": getattr(candidate, "area", ""),
        "detected_category": getattr(candidate, "category", ""),
        "source_records": source_records,
        "social_context": social_context,
        "sensitive_story": sensitive,
        "editorial_requirements": {
            "minimum_body_words": floor,
            "maximum_body_words": cap,
            "target_body_words": f"{floor}-{cap}",
            "length_policy": (
                "This budget reflects how much verified source material "
                "exists. A thin source gets a short accurate brief of four "
                "tight paragraphs. Never pad towards a word count with "
                "unsupported reaction, trends, background or speculation; "
                "a short true report always beats a long invented one."
            ),
            "paragraphs": "4-10",
            "include_when_supported": [
                "latest development",
                "chronology",
                "relevant background",
                "local significance",
                "practical information",
                "what happens next",
            ],
            "seo": "Natural descriptive headline; no keyword stuffing or clickbait.",
            "house_style": STYLE_VERSION,
            "retain_local_impact_context": True,
        },
        "right_to_reply": (
            "Anyone directly affected may request a correction or right of reply by emailing "
            + right_to_reply_email
            + "."
        ),
    }

    previous = None
    feedback: list[str] = []
    for attempt in range(4):
        payload = dict(base_payload)
        if attempt:
            payload["previous_draft"] = previous
            payload["repair_required"] = feedback
            payload["repair_instruction"] = (
                "Correct every issue while preserving all supported facts. "
                "Do not pad with generic prose, and never add reaction, "
                "trends or consequences that the sources do not state."
            )
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                response_format={"type": "json_schema", "json_schema": schema},
                temperature=0.18,
                max_tokens=3000,
            )
            draft = normalise_draft(json.loads(response.choices[0].message.content or "{}"))
        except Exception as exc:
            logger.warning(
                "OpenAI journalism attempt %d failed for %s: %s",
                attempt + 1,
                getattr(candidate, "source_url", ""),
                exc,
            )
            continue

        feedback = quality_issues(draft, source_text)
        if not feedback:
            return draft
        previous = draft
        logger.warning(
            "Journalism repair requested after attempt %d for %s: %s",
            attempt + 1,
            getattr(candidate, "source_url", ""),
            "; ".join(feedback),
        )
    return None


def enforce_category_minimums(
    selected: list[dict[str, Any]],
    pool: list[dict[str, Any]],
    target: int,
    category_getter,
    minimums: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    floors = minimums or DEFAULT_CATEGORY_MINIMUMS
    output = list(selected[:target])
    counts = Counter(category_getter(item) for item in output)

    for category, minimum in floors.items():
        available = [item for item in pool if category_getter(item) == category]
        required = min(minimum, len(available))
        while counts[category] < required:
            addition = next((item for item in available if item not in output), None)
            if addition is None:
                break
            if len(output) < target:
                output.append(addition)
                counts[category] += 1
                continue

            removable_index = None
            for index in range(len(output) - 1, -1, -1):
                other = category_getter(output[index])
                other_available = sum(1 for item in pool if category_getter(item) == other)
                other_floor = min(floors.get(other, 1), other_available)
                if other != category and counts[other] > other_floor:
                    removable_index = index
                    break
            if removable_index is None:
                break
            removed = output.pop(removable_index)
            counts[category_getter(removed)] -= 1
            output.append(addition)
            counts[category] += 1
    return output[:target]
