"""Background box for short stories: checked facts only, relevant, never stacked.

Run: python -m pytest -q scraper/test_story_background.py
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import story_background as B  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def story(title, body="<p>A short report.</p><p>Second paragraph.</p>", **extra):
    record = {"slug": re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-"), "title": title,
              "category": "news", "content_html": body, "status": "published"}
    record.update(extra)
    return record


def test_facts_file_is_well_formed():
    data = json.loads((ROOT / "story_facts.json").read_text(encoding="utf-8"))
    ids = set()
    for subject in data["subjects"]:
        re.compile(subject["match"])
        if subject.get("exclude"):
            re.compile(subject["exclude"])
        for fact in subject["facts"]:
            assert fact["id"] not in ids, fact["id"]
            ids.add(fact["id"])
            assert fact["text"].endswith("."), fact["id"]
            assert fact["source"]["url"].startswith("https://"), fact["id"]
            assert fact["source"]["title"], fact["id"]
            # Each sentence must stand alone; it may be the only one in the box.
            assert not re.match(r"(?:It|Its|The club|The building|The ground|The council|The hospice)\b", fact["text"]), fact["id"]


def test_dale_story_gets_relevant_dale_facts():
    s = story("Rochdale AFC to face Bolton in midweek cup tie", category="sport",
              body="<p>Dale travel to Bolton Wanderers for the cup tie on Tuesday.</p>",
              published_at="2026-10-20T10:00:00Z")
    texts = [f["text"] for f in B.choose_facts(s)]
    assert texts and any("League Cup final in 1962" in t or "FA Cup" in t for t in texts)
    assert len(texts) <= B.MAX_FACTS
    html = B.box(s)
    assert 'data-rd-background="1"' in html and "Background sources:" in html
    assert "en.wikipedia.org/wiki/Rochdale_A.F.C." in html


def test_subject_must_be_in_the_headline():
    # A foodbank story that mentions a Milnrow school gets foodbank facts, not Milnrow ones.
    s = story("Rochdale Foodbank receives Harvest donations",
              body="<p>Pupils at a school in Milnrow collected tins for the harvest appeal.</p>")
    texts = " ".join(f["text"] for f in B.choose_facts(s))
    assert "Foodbank" in texts and "Milnrow" not in texts


def test_fact_already_in_story_is_skipped():
    s = story("Rochdale Foodbank appeals for items",
              body="<p>The foodbank, started in 2012 with £400 and six people, needs tins.</p>")
    assert all("2012" not in f["text"] for f in B.choose_facts(s))


def test_unrelated_facts_are_not_used():
    # A Middleton child guitarist does not get Peterloo or the parish church.
    s = story("Nine-year-old guitarist from Middleton on verge of world record",
              body="<p>He plays guitar and hopes to set a record.</p>")
    assert B.choose_facts(s) == []


def test_sensitive_and_commercial_stories_get_nothing():
    for s in (
        story("Sponsored: Rochdale AFC hospitality packages", sponsored=True),
        story("Morning Briefing: Saturday 24 October 2026", briefing_slot="morning"),
        story("Man charged after incident near Crown Oil Arena", category="crime"),
        story("Police appeal to find missing man in Heywood"),
        story("Doorman highlights racial abuse after incident in Heywood"),
        story("Restore Britain branch announces Heywood event", category="politics"),
        story("Accrington Stanley vs Rochdale AFC streaming live", category="sport"),
    ):
        assert B.box(s) == "", s["title"]


def test_long_stories_are_left_alone():
    body = "<p>" + "word " * 300 + "</p>"
    assert B.box(story("Rochdale AFC draw with Grimsby", body=body, category="sport")) == ""


def test_ward_line_only_when_headline_names_the_place():
    s = story("Plans for 45-home development in Bamford face objections",
              excerpt="Residents in Bamford have objected.", category="environment",
              published_at="2026-10-01T10:00:00Z")
    line = B.ward_line(s)
    assert line and "Bamford" in line[0] and line[0].count(",") == 1 and " and " in line[0]
    borough_wide = story("Hundreds of families join Holiday Hive fun in the parks",
                         excerpt="A craft session at Spotland library next week.", category="news")
    assert B.ward_line(borough_wide) is None
    match = story("Rochdale AFC host Crewe at Spotland", excerpt="Dale play at Spotland.", category="sport")
    assert B.ward_line(match) is None


def test_same_story_same_box():
    s = story("Rochdale Hornets players compete in international matches", category="sport",
              body="<p>Six players were picked for Fiji and other nations.</p>")
    assert B.box(s) == B.box(dict(s))


def test_insert_before_reader_question_and_strip():
    s = story("Springhill Hospice to host free will clinic")
    body = s["content_html"] + '<p data-rd-reader-ending="1">What do you think?</p>'
    out = B.insert(body, s)
    assert out.index("rd-background") < out.index("data-rd-reader-ending")
    assert B.insert(out, s).count('data-rd-background="1"') == 1      # never stacks
    assert "rd-background" not in B.strip(out)


def test_render_read_back_does_not_stack():
    import generate_pages
    from archive_quality import article_body
    s = story("Rochdale Foodbank appeals for this week's most-needed items")
    record = dict(s)
    for _ in range(3):
        page = generate_pages.render_article_page(dict(record), [record])
        assert page.count('data-rd-background="1"') == 1
        record["content_html"] = article_body(page)
        assert "rd-background" not in record["content_html"]


def test_background_is_not_story_text_for_topic_hubs():
    import internal_links
    s = story("Rochdale Foodbank appeals for this week's most-needed items")
    page = '<div class="article-copy">' + B.insert(s["content_html"], s) + '<details class="article-sources"></details></div>'
    assert "Newgate" in page and "Newgate" not in internal_links.body_text(page)


def test_time_bound_facts_never_appear_before_they_were_true():
    old = story("Rochdale AFC host Gillingham in National League match", category="sport",
                body="<p>Dale host Gillingham in the league this weekend.</p>", published_at="2025-03-01T10:00:00Z")
    new = dict(old, slug="new-one", published_at="2026-10-01T10:00:00Z")
    assert not any("May 2026" in f["text"] for f in B.choose_facts(old))
    assert any("May 2026" in f["text"] or "relegated in 2023" in f["text"] for f in B.choose_facts(new))
    planning = story("Plans for 45-home development in Bamford face objections", category="environment",
                     published_at="2025-11-01T10:00:00Z")
    assert B.ward_line(planning) is None                       # before the current councillors were elected
