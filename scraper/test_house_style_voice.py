"""House voice checks should improve copy without blocking legitimate local news."""

from house_style import HUMAN_VOICE_BRIEF, HOUSE_STYLE_SYSTEM, STYLE_VERSION, style_issues


def draft(title: str, paragraph: str) -> dict:
    return {
        "title": title,
        "excerpt": "A Rochdale business received a regional award after judges assessed customer ratings.",
        "paragraphs": [paragraph],
    }


def run() -> None:
    assert STYLE_VERSION == "rochdale-human-newsroom-v15"
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
    # v13: single and curly quotation marks count; apostrophes do not.
    assert eu.source_has_quote("'It is a truly exceptional tragedy, we will act,' Mr Tusk said.")
    assert not eu.source_has_quote("The gunman's car and the officers' guns were found at the driver's home, police said.")
    assert eu.draft_has_quote("‘It was a proud day for us,’ she said.")
    # Curly apostrophes inside a curly single-quoted quotation.
    assert eu.source_has_quote("‘We’re working hard to keep this park open,’ she said.")
    assert eu.draft_has_quote("‘We’re working hard to keep this park open,’ she said.")
    assert eu.source_has_quote("‘The park’s future isn’t certain but we’ll fight for it,’ Mr Ali said.")
    assert not eu.source_has_quote("The gunman’s car and the officers’ guns were found at the driver’s home, police said.")
    assert "Mr Emmott" in NEWS_SYNTAX_BRIEF and "A Heywood man" in NEWS_SYNTAX_BRIEF
    from reader_copy import uk_dates
    assert uk_dates("war on 4th August 1914 and 21st May") == "war on 4 August 1914 and 21 May"
    # v14 (editor, 7 Nov 2026): no paper-voice sympathy closer.
    assert "Our thoughts are with the family and all those affected" not in _hs.HOUSE_STYLE_SYSTEM
    assert "has asked <the relevant body> for comment" in _hs.HOUSE_STYLE_SYSTEM
    assert "a right of reply line, a correction or clarification notice, and the source line" in _hs.HOUSE_STYLE_SYSTEM
    # Draft normalisation never changes a date inside a quotation.
    d = eu.normalise_draft({"title": "Party on 4th August", "excerpt": "x", "paragraphs": [
        'Jane Smith said: "Our celebration will be on 4th August this year."',
        "She said: 'It starts on 4th August.' It ends on 5th August."]})
    assert d["paragraphs"][0] == 'Jane Smith said: "Our celebration will be on 4th August this year."'
    assert d["paragraphs"][1] == "She said: 'It starts on 4th August.' It ends on 5 August."
    assert d["title"] == "Party on 4 August"
    # v15 story order (editor, 7 Nov 2026).
    assert _hs.STORY_ORDER_BRIEF in _hs.HOUSE_STYLE_SYSTEM
    order = _hs.STORY_ORDER_BRIEF
    assert order.index("invested") < order.index("What happened") < order.index("Quotes and comments") \
        < order.index("Background") < order.index("Conclusion")
    links = eu.verified_useful_links(
        [{"label": "Fundraiser for Amy", "url": "https://www.gofundme.com/f/help-amy"},
         {"label": "Invented", "url": "https://www.gofundme.com/f/not-in-sources"},
         {"label": "News site", "url": "https://www.manchestereveningnews.co.uk/news/x"},
         {"label": "Petition", "url": "https://petition.parliament.uk/petitions/700001"}],
        "Friends set up https://www.gofundme.com/f/help-amy and https://petition.parliament.uk/petitions/700001 "
        "see https://www.manchestereveningnews.co.uk/news/x")
    assert [l["label"] for l in links] == ["Fundraiser for Amy", "Petition"], links
    html_links = eu.useful_links_html(links)
    assert 'href="https://www.gofundme.com/f/help-amy"' in html_links and 'rel="noopener nofollow"' in html_links
    # The paper's own sympathy line goes from every story, death reports too.
    assert eu.strip_service_furniture(["A man, 52, died.", "Our thoughts are with the family and all those affected."], "news") == ["A man, 52, died."]
    assert eu.strip_service_furniture(["“Our thoughts are with his family,” the club said."], "sport") == ["“Our thoughts are with his family,” the club said."]
    print("Human editorial voice checks passed.")


if __name__ == "__main__":
    run()
