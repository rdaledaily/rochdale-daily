"""Reader-copy rules (reader_copy.py), checked against the 28 Oct 2026 story
that prompted them: Rochdale Daily's deputy leader report, whose standfirst
repeated paragraph 1 and whose first paragraph ran to 69 words."""

from __future__ import annotations

import reader_copy as rc
from house_style import HOUSE_STYLE_SYSTEM, STYLE_VERSION, style_issues

P1 = ("Councillor Daalat Ali, the deputy leader of Rochdale council, was detained by authorities "
      "for a short period upon his arrival in Pakistan. This incident occurred during a civic "
      "delegation visit to the city of Sahiwal, which is twinned with Rochdale. The delegation "
      "includes Rochdale's ceremonial mayor, Councillor Faisal Rana, and aims to strengthen "
      "relationships between the two areas, which have historical ties dating back to their "
      "twinning in 1998.")
P2 = ("The council confirmed that the detention was brief. Fortunately, Councillor Ali is "
      "reported to be safe and well.")
EXCERPT = ("Councillor Daalat Ali was held for a short time upon arrival in Pakistan as part of a "
           "delegation aimed at strengthening ties with Sahiwal.")


def run() -> None:
    # Paragraphs are re-broken at sentences, never cut: every word survives.
    tidy = rc.tidy_paragraphs([P1, P2])
    assert all(rc.words(p) <= rc.MAX_PARAGRAPH_WORDS for p in tidy), tidy
    assert all(len(rc.split_sentences(p)) <= 2 for p in tidy), tidy
    assert " ".join(tidy).replace("Councillor Ali is", "Fortunately, Councillor Ali is") == " ".join(
        rc.plain(p) for p in [P1, P2]), "words were lost"
    assert "Fortunately" not in " ".join(tidy)

    # Abbreviations, initials and quotations are not sentence ends.
    assert rc.split_sentences('Mr. Smith said "It was bad. Very bad." He left at 5 p.m. on Tuesday.') == [
        'Mr. Smith said "It was bad. Very bad."', "He left at 5 p.m. on Tuesday."]
    assert len(rc.split_sentences("St. Mary's and J. Bloggs Ltd. both agreed.")) == 1

    # A single very long sentence stays whole rather than being cut mid-sentence.
    long_sentence = " ".join(["word"] * 60) + "."
    assert rc.split_long_paragraphs([long_sentence]) == [long_sentence]

    # HTML: plain paragraphs split; paragraphs with markup and other elements untouched.
    html_in = '<p>One. Two. Three.</p><p>A <a href="/x">link</a>. B. C. D.</p><ul><li>x</li></ul>'
    assert rc.tidy_content_html(html_in) == (
        '<p>One. Two.</p><p>Three.</p><p>A <a href="/x">link</a>. B. C. D.</p><ul><li>x</li></ul>')
    assert rc.tidy_content_html("<p>Short. Fine.</p>") == "<p>Short. Fine.</p>"

    # Repetition: the measured standfirst repeats paragraph 1.
    assert rc.repetition_issues(EXCERPT, [P1, P2])
    assert not rc.repetition_issues(
        "The Kingsway councillor was travelling with the mayor as part of a twinning delegation.",
        ["A Rochdale AFC striker has signed a two-year deal with Bury after a trial in August.",
         "The club said he would wear the number nine shirt."])

    assert rc.ai_tell_issues("This incident occurred during a visit.")
    assert not rc.ai_tell_issues("Police closed Halifax Road at 7am.")

    # Headlines: no capitals for shouting, no question on crime, no clickbait.
    assert rc.headline_issues("BREAKING INVESTIGATION: £50.3M OWED BY COUNCIL COMPANIES")
    assert rc.headline_issues("Was the Heywood man charged?", "crime")
    assert rc.headline_issues("Has Rochdale cleared its SEND backlog?", "education") == []
    assert rc.headline_issues("You won't believe this Rochdale chippy")

    # Social headline: kept when it passes, dropped when it breaks a hard rule.
    title = "Heywood lollipop man forced to leap out of way as drivers ignore crossing"
    good = "Heywood lollipop man forced to jump clear as two drivers ignore him"
    assert rc.clean_social_headline(good, title) == good
    assert rc.clean_social_headline(title, title) == ""
    assert rc.clean_social_headline("SHOCKING SCENES IN HEYWOOD AS DRIVERS IGNORE LOLLIPOP MAN", title) == ""
    assert rc.social_headline_issues("", title)

    # The house style carries the people-first brief and checks it.
    assert STYLE_VERSION == "rochdale-human-newsroom-v11"
    assert "Write about people, not incidents" in HOUSE_STYLE_SYSTEM
    issues = style_issues({"title": title, "excerpt": EXCERPT, "paragraphs": [P1, P2],
                           "social_headline": title, "category": "news"})
    assert any("standfirst repeats" in i for i in issues), issues
    assert any("machine-written" in i for i in issues), issues
    assert any("social_headline different" in i for i in issues), issues
    # Paragraph length is fixed by code, so it is never sent back to the model.
    assert not any("short paragraphs" in i for i in issues), issues

    print("Reader-copy rule tests passed.")


if __name__ == "__main__":
    run()
