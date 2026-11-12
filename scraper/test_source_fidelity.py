"""Regression tests for source_fidelity, built from real published failures.

12 Nov 2026: four live stories carried statements their only source never made.
Each case below is the published sentence against the source text the writer
was given.
"""
from datetime import date

from source_fidelity import (
    fidelity_issues,
    unsupported_attributions,
    unsupported_dates,
    unsupported_names,
    unsupported_numbers,
    unsupported_quotes,
    unsupported_status,
)
from editorial_upgrade import integrity_issues, quality_issues

FIREARM_SOURCE = (
    "Man arrested for possessing an imitation firearm at Rochdale Armistice Day event. "
    "A man in his 50s has been arrested after police found what they believe to be an air "
    "pistol near a remembrance ceremony in Rochdale town centre. Greater Manchester Police "
    "said officers approached the man at about 11.30am, this morning, Wednesday 11 November, "
    "after he appeared to be protesting near the ceremony. Officers said they had reasonable "
    "grounds to search him and found what is believed to be an air pistol. He was arrested on "
    "suspicion of possession of an imitation firearm and remains in custody while enquiries "
    "continue. No injuries have been reported and police said there is currently no evidence "
    "to suggest the air pistol was fired. Police confirmed the man did not interrupt the "
    "service and was standing some distance from the main ceremony."
)


def test_invented_police_statement_is_caught():
    published = (
        "A spokesperson for Greater Manchester Police confirmed that the man remains in custody "
        "as investigations continue. They reiterated that the safety of the public is their "
        "priority and that no one was harmed during the incident."
    )
    flagged = unsupported_attributions(published, FIREARM_SOURCE)
    assert any("safety of the public" in s for s in flagged)


def test_supported_police_statement_passes():
    accurate = (
        "Police said there was no evidence the air pistol had been fired. "
        "Officers said they had reasonable grounds to search him."
    )
    assert unsupported_attributions(accurate, FIREARM_SOURCE) == []


def test_source_corrected_age_is_caught():
    # RVR later corrected "in his 50s" to 39. Against the corrected source the
    # old age no longer stands.
    corrected = FIREARM_SOURCE.replace("A man in his 50s", "A 39-year-old man")
    assert unsupported_numbers("A man in his 50s was arrested.", corrected) == ["50s"]
    assert unsupported_numbers("A 39-year-old man was arrested.", corrected) == []


def test_time_and_calendar_date_are_not_false_positives():
    draft = "Officers approached him at about 11.30am on 11 November 2026."
    assert unsupported_numbers(draft, FIREARM_SOURCE) == []
    # The writer turns "this morning" into a date: a day number absent from the
    # source is expected and is not flagged.
    assert unsupported_numbers("The parade took place on 8 November.", "The parade took place on Sunday.") == []
    assert unsupported_numbers("on the weekend of 12-13 November", "this weekend") == []


def test_source_link_record_ids_are_not_figures():
    draft = "Council notice: www.rochdale.gov.uk/directory-record/2644/schofield-street-roadworks"
    assert unsupported_numbers(draft, "Schofield Street will close for roadworks.") == []


def test_invented_population_figure_is_caught():
    draft = "The calendar serves the borough's 200,000 residents."
    assert unsupported_numbers(draft, "The council has published a community events calendar.") == ["200,000"]


def test_invented_quote_is_caught():
    # RBH case: the source quotes the chief executive, the draft invented a
    # different "spokesperson" quote.
    source = (
        "Amanda Newton, RBH Chief Executive, said: “We are proud that our customers are "
        "telling us they're feeling the significant improvements that we have made.”"
    )
    invented = 'A spokesperson for RBH stated, "We are proud of our ranking and will strive to enhance our services further."'
    exact = 'Amanda Newton said: "We are proud that our customers are telling us they\'re feeling the significant improvements."'
    assert unsupported_quotes(invented, source)
    assert unsupported_quotes(exact, source) == []


def test_quote_from_source_with_no_quotes_is_caught():
    # Armistice Day photo gallery: the source quotes no one.
    source = "Armistice Day at Rochdale Cenotaph. Photos from the service at the Cenotaph on Wednesday."
    draft = 'A spokesperson for Rochdale Council said: "It is important to remember and honour the sacrifices made by our servicemen and women."'
    assert unsupported_quotes(draft, source)


def test_fidelity_failures_block_publication():
    issues = fidelity_issues(
        "They reiterated that the safety of the public is their priority and their main concern.",
        FIREARM_SOURCE,
    )
    assert issues
    assert integrity_issues(issues) == issues


def test_quality_gate_runs_fidelity_checks():
    draft = {
        "publishable": True,
        "content_class": "news_report",
        "is_about_rochdale_borough": True,
        "title": "Man arrested over imitation firearm near Rochdale remembrance ceremony",
        "excerpt": "Police found what they believe is an air pistol on a man near the Cenotaph service on Wednesday.",
        "paragraphs": [
            "A man in his 50s was arrested near the remembrance ceremony in Rochdale town centre.",
            "Officers searched him and found what is believed to be an air pistol.",
            "They reiterated that the safety of the public is their priority at every public event.",
        ],
        "category": "crime",
        "area": "rochdale",
    }
    issues = quality_issues(draft, FIREARM_SOURCE, "article")
    assert any(issue.startswith("Source fidelity:") for issue in integrity_issues(issues))



def test_legal_status_cannot_be_upgraded():
    source = "A 39-year-old man was arrested on suspicion of possession of an imitation firearm."
    assert unsupported_status("A man has been charged with possessing a firearm.", source) == ["charged"]
    assert unsupported_status("A man was convicted of possessing a firearm.", source) == ["convicted / found guilty"]
    assert unsupported_status("A man was arrested over a firearm.", source) == []


def test_harm_and_weapon_cannot_be_invented():
    source = "Police were called to a disturbance on Yorkshire Street. A man was taken to hospital."
    assert "stabbing" in unsupported_status("A man was stabbed on Yorkshire Street.", source)
    assert "serious injury" in unsupported_status("A man was left in a critical condition.", source)
    assert "death" in unsupported_status("A man died on Yorkshire Street.", source)


def test_died_is_not_killed():
    source = "A man died after a fire at his flat. Police say there are no suspicious circumstances."
    assert unsupported_status("A man died in a flat fire.", source) == []
    assert unsupported_status("A man was killed in a flat fire.", source) == ["killed"]


def test_invented_name_or_place_is_caught():
    source = "Mark Massey, of Hardman Street, Milnrow, has been charged with violent disorder."
    assert unsupported_names("Police said Mark Massey, of Hardman Street, Milnrow, was charged.", source) == []
    assert unsupported_names("The charges follow an incident in Littleborough.", source) == ["Littleborough"]


def test_titles_and_compound_words_are_not_names():
    source = "Sgt Jane Smith said the shop in Rochdale was raided."
    assert unsupported_names("Police Sergeant Jane Smith said the Rochdale-based shop was raided.", source) == []


def test_sentence_initial_capitals_are_not_names():
    source = "Ramsden Road will be closed for the concert."
    assert unsupported_names("Road closure for concert. Temporary closure of Ramsden Road.", source) == []


def test_wrong_meeting_date_is_caught():
    # Real case: source published Saturday 10 Oct said "on Thursday" (15 Oct);
    # the published story said 13 October.
    source = "When Rochdale's full council meets on Thursday, it will consider a motion."
    published = date(2026, 10, 10)
    assert unsupported_dates("The council will discuss the motion on 13 October.", source, published) == ["13 October"]
    assert unsupported_dates("The council will discuss the motion on 15 October.", source, published) == []


def test_wrong_date_range_is_caught():
    # Real case: the Ale Trail runs Thursday 12 to Sunday 15 November; the
    # published story said 12-13 November.
    source = "Ales and ciders from Thursday, November 12, to Sunday, November 15."
    assert unsupported_dates("Scheduled for the weekend of 12-13 November.", source, date(2026, 11, 2)) == ["13 November"]
    assert unsupported_dates("Runs from 12 to 15 November.", source, date(2026, 11, 2)) == []


def test_relative_date_in_source_allows_calendar_date():
    source = "Officers approached the man at about 11.30am this morning, Wednesday 11 November."
    assert unsupported_dates("Officers approached him on 11 November.", source, date(2026, 11, 11)) == []
    assert unsupported_dates("The man was arrested on 10 November.", "He was arrested this morning.", date(2026, 11, 11)) == []
    assert unsupported_dates("The man was arrested on 8 November.", "He was arrested this morning.", date(2026, 11, 11)) == ["8 November"]


if __name__ == "__main__":
    failures = []
    for name, test in sorted(globals().items()):
        if name.startswith("test_") and callable(test):
            try:
                test()
                print(f"ok   {name}")
            except AssertionError as exc:
                failures.append(name)
                print(f"FAIL {name}: {exc}")
    if failures:
        raise SystemExit(f"{len(failures)} source-fidelity test(s) failed")
    print("all source-fidelity tests passed")
