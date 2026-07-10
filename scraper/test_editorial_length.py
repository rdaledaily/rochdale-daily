"""Tests for the source-proportional length budget and fabrication checks.

These import only editorial_upgrade and house_style, which are pure standard
library, so they can run in the Validate step before Feedparser, Playwright
or OpenAI are needed.

Background: the previous fixed 200-word floor forced the model to invent
content whenever the source was thin. The live article "Man arrested after
two-vehicle collision near Norden" was built from a two-sentence source and
contained fabricated residents' concerns and calls for better signage as a
direct result. The budget now scales with the evidence and padding a thin
story is a failure, not a requirement.
"""

from editorial_upgrade import (
    RICH_SOURCE_WORDS,
    length_budget,
    quality_issues,
    source_word_count,
)
from house_style import WEAK_STYLE_RE


def make_words(count: int) -> str:
    return " ".join(f"fact{index}" for index in range(count))


# ---------------------------------------------------------------------------
# length_budget
# ---------------------------------------------------------------------------

# A rich source keeps the original full-report budget.
rich_source = make_words(RICH_SOURCE_WORDS + 100)
assert length_budget(rich_source) == (200, 900)

# A two-sentence police snippet gets a short-brief budget.
thin_source = (
    "A man has been arrested in connection with a two-vehicle collision "
    "near Norden on 9 July. Police responded to the scene and enquiries "
    "are ongoing."
)
thin_words = source_word_count(thin_source)
floor, cap = length_budget(thin_source)
assert floor == 50, (floor, thin_words)  # very thin source -> minimum floor
assert cap == floor + 60, (cap, thin_words)
assert cap < 200, "A thin source must never be budgeted a full-length report."

# The floor never drops below 50 and the cap never exceeds 900.
assert length_budget(make_words(10))[0] == 50
assert length_budget(make_words(RICH_SOURCE_WORDS - 1))[1] <= 900


# ---------------------------------------------------------------------------
# quality_issues with a thin source
# ---------------------------------------------------------------------------

def build_draft(body_words_per_paragraph: list[int], seed_terms: list[str]) -> dict:
    """Build a draft whose paragraphs share vocabulary with the source so the
    token-grounding check passes, letting the tests isolate length behaviour."""
    paragraphs = []
    for index, count in enumerate(body_words_per_paragraph):
        seeds = " ".join(seed_terms)
        filler = " ".join(f"detail{index}{n}" for n in range(max(0, count - len(seed_terms))))
        paragraphs.append(f"{seeds} {filler}".strip())
    return {
        "publishable": True,
        "title": "Man arrested after collision near Norden say police",
        "excerpt": (
            "Police made one arrest after a two-vehicle collision near Norden "
            "and say their enquiries into the incident are continuing."
        ),
        "paragraphs": paragraphs,
    }


seed_terms = ["arrested", "collision", "norden", "police", "enquiries"]

# An honest short brief within the thin budget must raise no length issue.
per_paragraph = max(2, floor // 4 + 2)
short_brief = build_draft([per_paragraph] * 4, seed_terms)
issues = quality_issues(short_brief, thin_source)
assert not any("body words" in issue for issue in issues), issues

# A padded 250-word draft from the same thin source must be told to CUT,
# never to expand.
padded = build_draft([65, 65, 65, 65], seed_terms)
issues = quality_issues(padded, thin_source)
assert any("Tighten" in issue for issue in issues), issues
assert not any("at least" in issue and "body words" in issue for issue in issues), issues

# A rich source still demands a full report: 100 body words is too short.
short_on_rich = build_draft([25, 25, 25, 25], ["fact1", "fact2", "fact3"])
issues = quality_issues(short_on_rich, rich_source)
assert any("at least 200" in issue for issue in issues), issues


# ---------------------------------------------------------------------------
# Fabricated-reaction phrases must be flagged by the style loop.
# Every phrase below appeared in, or is shaped like, the fabricated content
# published on the live Norden article.
# ---------------------------------------------------------------------------
FABRICATED_SAMPLES = (
    "The incident has raised significant concerns regarding road safety.",
    "This is prompting local residents to voice their concerns.",
    "The crash is prompting discussions among residents about safety.",
    "Residents have voiced concerns about traffic in the area.",
    "Many have called for increased measures, including better signage.",
    "This incident adds to a growing list of traffic-related occurrences.",
    "The collision is part of a troubling trend of incidents locally.",
    "The plans have sparked widespread debate among villagers.",
)
for sample in FABRICATED_SAMPLES:
    assert WEAK_STYLE_RE.search(sample), f"Not flagged: {sample!r}"

# Attributed, sourced reporting of the same subject matter must NOT be
# flagged — the detector targets formulaic filler, not real journalism.
LEGITIMATE_SAMPLES = (
    "Councillor Jane Smith said residents had raised the junction's safety "
    "record at last month's township meeting.",
    "In a statement, the residents' association asked the council to review "
    "signage on the road.",
)
for sample in LEGITIMATE_SAMPLES:
    assert not WEAK_STYLE_RE.search(sample), f"Wrongly flagged: {sample!r}"

print("Editorial length and fabrication tests passed.")

# ---------------------------------------------------------------------------
# Regressions from the live Whitworth Swimming Baths article: wrong category
# from prose-word match, dangling empty date, headline describing a different
# story than the body.
# ---------------------------------------------------------------------------
from editorial_upgrade import deterministic_category

assert deterministic_category(
    "The initiative aims to provide a supportive environment for participants "
    "to engage in gentle yoga practices."
) != "environment", "'supportive environment' must not categorise as environment"
assert deterministic_category("Flood warning issued for the borough") == "environment"
assert deterministic_category("Litter pickers clean up the canal towpath") == "environment"

dangling = build_draft([60, 60, 60, 60], seed_terms)
dangling["paragraphs"][2] += " The first session is set to take place on ."
issues = quality_issues(dangling, rich_source + " arrested collision norden police enquiries")
assert any("missing date" in issue for issue in issues), issues

mismatch = {
    "publishable": True,
    "title": "Indoor Five-a-Side Football Sessions Announced at Whitworth Swimming Baths",
    "excerpt": (
        "New Back Care Yoga sessions are set to begin at Whitworth Swimming "
        "Baths, aimed at improving posture and alleviating back pain."
    ),
    "paragraphs": [
        "A series of Back Care Yoga sessions will commence at Whitworth Swimming Baths, designed to assist individuals in improving posture and managing back pain.",
        "The sessions will be led by qualified instructors who specialise in back care and yoga therapy for participants of all levels.",
        "Each class incorporates relaxation and mindfulness techniques alongside exercises that address common back issues for attendees.",
        "Classes run weekly and are expected to last approximately one hour, with mats available for anyone who does not bring their own.",
    ],
}
issues = quality_issues(
    mismatch,
    "Back Care Yoga sessions begin at Whitworth Swimming Baths led by qualified instructors weekly classes",
)
assert any("Align the headline" in issue for issue in issues), issues

coherent = dict(mismatch)
coherent["title"] = "Back Care Yoga Sessions Announced at Whitworth Swimming Baths"
issues = quality_issues(
    coherent,
    "Back Care Yoga sessions begin at Whitworth Swimming Baths led by qualified instructors weekly classes",
)
assert not any("Align the headline" in issue for issue in issues), issues

print("Category, dangling-date and headline-coherence tests passed.")
