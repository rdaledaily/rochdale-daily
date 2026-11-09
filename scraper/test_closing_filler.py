"""Stories end on their last fact (editor, 9 Nov 2026).

Fixtures are real closing paragraphs from the live paper."""
from closing_filler_sweep import clean_page
from reader_copy import strip_closing_html, tidy_content_html, tidy_editor_html

TESCO = (
    "<p>Video footage shared on social media showed the air ambulance landing in the car park.</p>"
    "<p>Tesco has declined to comment on the incident when approached by media outlets. "
    "This incident raises concerns about safety in public spaces and the importance of rapid "
    "emergency response in critical situations.</p>"
)


def test_tesco_ends_on_tesco_not_commenting():
    for fn in (strip_closing_html, tidy_content_html, tidy_editor_html):
        out = fn(TESCO)
        assert "raises concerns" not in out, fn.__name__
        assert out.rstrip().endswith("when approached by media outlets.</p>"), (fn.__name__, out)


def test_archived_page_loses_appended_invitation_and_filler():
    page = (
        '<html><body><h1>Woman dies</h1><div class="article-copy">' + TESCO +
        '<p data-rd-reader-ending="1">How does this affect you or your neighbourhood, and what would '
        'you like to happen next? Share your thoughts in the comments.</p>'
        '<p class="rd-related-inline">More from Rochdale: <a href="/x">X</a></p>'
        '<details class="article-sources"><summary>Sources</summary></details></div>'
        '<section class="comments-section"></section></body></html>'
    )
    out = clean_page(page)
    assert "Share your thoughts" not in out and "raises concerns" not in out
    assert "air ambulance landing" in out and "declined to comment" in out
    assert 'class="rd-related-inline"' in out and "article-sources" in out
    assert clean_page(out) == out  # idempotent


def test_question_and_invitation_go_together_police_line_stays():
    body = ("<p>Police are appealing for help to find her.</p>"
            "<p>How can local communities support families during a missing person appeal? "
            "Share your thoughts in the comments. Any information about this appeal should go "
            "directly to the police using the contact details above.</p>")
    out = strip_closing_html(body)
    assert "?" not in out and "comments" not in out
    assert "should go directly to the police" in out


def test_manual_article_invitation_removed_source_line_kept():
    body = ("<p>The pilot is expected to launch in early 2027.</p>"
            "<p>What would make the biggest difference to mental health support for children and "
            "families in Rochdale? Share your thoughts in the comments, while protecting children's "
            "privacy.</p><p>Source: Department of Health and Social Care announcement.</p>")
    out = tidy_editor_html(body)
    assert "Share your thoughts" not in out and "biggest difference" not in out
    assert "Source: Department of Health" in out and "early 2027" in out


def test_invitation_above_link_lines_and_reader_question_with_figure():
    body = ("<p>For households watching every pound, read the letter carefully.</p>"
            "<p>Have you received your letter or seen the £150 appear on your energy account? "
            "Tell us your supplier and experience in the comments, keeping account numbers private.</p>"
            '<p>Scheme information: <a href="https://www.gov.uk/x">https://www.gov.uk/x</a></p>'
            '<p>Payment timetable: <a href="https://example.org/y">https://example.org/y</a></p>')
    for fn in (strip_closing_html, tidy_editor_html):
        out = fn(body)
        assert "£150" not in out and "comments" not in out, fn.__name__
        assert "Scheme information" in out and "read the letter carefully" in out


def test_mismatched_quote_earlier_does_not_shield_the_ending():
    body = ("<p>She said: “It doesn't cost anything to be kind, does it?\"</p>"
            "<p>A familiar face on a weekly errand can make a real difference.</p>"
            "<p>Do you know someone whose kindness deserves recognition? "
            "Tell us in the comments or email news@rochdaledaily.co.uk.</p>")
    out = strip_closing_html(body)
    assert "comments" not in out and "real difference" in out


def test_quotes_attributed_concern_and_reply_survive():
    keep = [
        '<p>"Share your thoughts with us," the organiser said.</p>',
        "<p>Residents said this decision raises concerns about parking on Bury Road.</p>",
        "<p>This decision raises questions because 40 homes lose access.</p>",
        "<p>Rochdale Daily has asked Tesco for comment.</p>",
        "<p>In response, the council said it would review the scheme.</p>",
    ]
    for p in keep:
        assert strip_closing_html("<p>Lead.</p>" + p).endswith(p), p


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("closing filler tests passed")
