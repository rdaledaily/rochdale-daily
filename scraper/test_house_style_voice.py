"""House voice checks should improve copy without blocking legitimate local news."""

from house_style import HUMAN_VOICE_BRIEF, HOUSE_STYLE_SYSTEM, STYLE_VERSION, style_issues


def draft(title: str, paragraph: str) -> dict:
    return {
        "title": title,
        "excerpt": "A Rochdale business received a regional award after judges assessed customer ratings.",
        "paragraphs": [paragraph],
    }


def run() -> None:
    assert STYLE_VERSION == "rochdale-human-newsroom-v11"
    from editorial_contract import NATURAL_STORY_POLICY
    assert NATURAL_STORY_POLICY in HOUSE_STYLE_SYSTEM
    assert HUMAN_VOICE_BRIEF in HOUSE_STYLE_SYSTEM
    assert "Rhetorical question" not in HUMAN_VOICE_BRIEF  # no forced devices in every piece
    assert "A rhetorical question" in HUMAN_VOICE_BRIEF
    assert "No jokes" in HUMAN_VOICE_BRIEF
    assert "Never manufacture first person experiences" in HUMAN_VOICE_BRIEF
    assert "dash punctuation" in HUMAN_VOICE_BRIEF

    generic = style_issues(draft(
        "Awards for Rochdale business",
        "The event was a significant milestone, a testament to the business.",
    ))
    assert any("formulaic" in item for item in generic), generic

    dash = style_issues(draft(
        "Rochdale business wins award",
        "Judges considered customer reviews — and announced the award yesterday.",
    ))
    assert any("dash punctuation" in item for item in dash), dash

    compound = style_issues(draft(
        "Rochdale business wins award",
        "The local family-run shop won a regional competition.",
    ))
    assert not any("dash punctuation" in item for item in compound), compound
    print("Human editorial voice checks passed.")


if __name__ == "__main__":
    run()
