"""House voice checks should improve copy without blocking legitimate local news."""

from house_style import HUMAN_VOICE_BRIEF, HOUSE_STYLE_SYSTEM, STYLE_VERSION, style_issues


def draft(title: str, paragraph: str) -> dict:
    return {
        "title": title,
        "excerpt": "A Rochdale business received a regional award after judges assessed customer ratings.",
        "paragraphs": [paragraph],
    }


def run() -> None:
    assert STYLE_VERSION == "rochdale-human-newsroom-v12"
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
    # v12 news syntax (7 Nov 2026): one-sentence opening of no more than ~30
    # words; a quote when the sources quote someone; UK ordinal-free dates.
    import house_style as _hs
    NEWS_SYNTAX_BRIEF = _hs.NEWS_SYNTAX_BRIEF
    assert NEWS_SYNTAX_BRIEF in _hs.HOUSE_STYLE_SYSTEM
    assert "'Jane Smith, 34, of Heywood'" in NEWS_SYNTAX_BRIEF
    long_open = style_issues(draft("Rochdale business wins award", " ".join(["word"] * 40) + "."))
    assert any("first paragraph" in item for item in long_open), long_open
    short_open = style_issues(draft("Rochdale business wins award", "A Heywood bakery, run by Jane Smith, 34, has won a regional award."))
    assert not any("first paragraph" in item for item in short_open), short_open
    import editorial_upgrade as eu
    assert eu.source_has_quote('The councillor said: "We will not let this park close while I am here."')
    assert not eu.source_has_quote('The "Love Rochdale Awards" return next week.')
    assert eu.draft_has_quote('She said: "It is a proud day for the bakery."')
    from reader_copy import uk_dates
    assert uk_dates("war on 4th August 1914 and 21st May") == "war on 4 August 1914 and 21 May"
    print("Human editorial voice checks passed.")


if __name__ == "__main__":
    run()
