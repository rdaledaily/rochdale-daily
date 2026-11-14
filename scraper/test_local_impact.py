"""'What it means for <place>' box (local_impact.py).

Fixtures are two live Rochdale Daily stories (12 Nov 2026) and one live crime
story that was filed under 'community'.
"""
import json
import re
from pathlib import Path

import local_impact as li

ROOT = Path(__file__).resolve().parents[1]

ROADWORKS = dict(
    title="Cartridge Street, roadworks in Heywood from 11 November 2026",
    excerpt="Part of Cartridge Street in Heywood is closed to repair a leaking service.",
    paragraphs=[
        "Rochdale Borough Council has published a traffic notice for Cartridge Street in Heywood.",
        "The closure began at 10.29am on Wednesday, 11 November 2026. Work will continue for a "
        "maximum of 21 days (2 December 2026), or when repairs are complete if sooner.",
        "The closure begins at the junction with Coomassie Street and ends 110 metres along the road.",
        "The published alternative route is Coomassie Street, Egerton Street, Pilsworth Road, Tower Street.",
    ],
    category="traffic",
    area="heywood",
)
TOY_APPEAL = dict(
    title="Heywood Christmas Toy Appeal seeks donations to support families in need",
    excerpt="The appeal is asking residents to donate toys and gifts for local families.",
    paragraphs=[
        "The Heywood Christmas Toy Appeal is calling on residents to donate toys and gifts to support local families in need.",
        "Donations are being accepted until 11 December, with collection points set up at local libraries and leisure centres.",
        "Last year, the appeal distributed 10,000 toys to around 3,000 children.",
        "The appeal has been running for thirteen years.",
    ],
    category="community",
    area="heywood",
)


def test_grounded_points_make_a_box_with_the_ward_name():
    impact = li.build({"audience": "drivers", "points": [
        "Work on the Cartridge Street closure will continue for a maximum of 21 days.",
        "The signed diversion runs via Egerton Street, Pilsworth Road and Tower Street.",
        "Work is due to finish by 2 December 2026.",
    ]}, **ROADWORKS)
    assert impact is not None
    assert impact["place"] == "Heywood"
    assert len(impact["points"]) == 3
    # 'drivers' is not in this body, so no audience is claimed.
    assert impact["audience"] == ""


def test_a_point_with_a_new_figure_or_name_is_dropped():
    impact = li.build({"audience": "", "points": [
        "Work on the Cartridge Street closure will continue for a maximum of 21 days.",
        "The work will cost the council £40,000 to complete.",          # figure not in article
        "Buses on the Bee Network 471 route will be diverted nearby.",  # names not in article
        "The signed diversion runs via Egerton Street, Pilsworth Road and Tower Street.",
    ]}, **ROADWORKS)
    # The invented cost and bus route never appear; anything kept is either a
    # grounded restatement or the story's own sentence.
    text = " ".join(impact["points"])
    assert "40,000" not in text and "Bee Network" not in text and "471" not in text
    assert "The signed diversion runs via Egerton Street, Pilsworth Road and Tower Street." in impact["points"]


LIBRARY = dict(
    title="Smithy Bridge library to close for repairs",
    excerpt="The library closes in January.",
    paragraphs=[
        "Rochdale Council will close Smithy Bridge library on 15 January for 150 days of repairs.",
        "The work will cost £2.5m and is funded by the council.",
        "Residents can use Littleborough library during the closure, the council said.",
        "A consultation on opening hours closes on 1 March.",
    ],
    category="community",
    area="smithy_bridge",
)
GOOD_LIBRARY_POINT = "Residents can use Littleborough library during the closure."


CLOSURE = "Rochdale Council will close Smithy Bridge library on 15 January for 150 days of repairs."
COST = "The work will cost £2.5m and is funded by the council."


def test_points_that_change_a_fact_are_corrected_to_the_story_sentence():
    # Each of these got through the first version (14 Nov 2026 check): every
    # figure and name was somewhere in the story, but the point said something
    # the story does not. Editor: change them, don't block them.
    for wrong, right in (
        ("The library will close for 15 days of repairs from January.", CLOSURE),       # 150 days
        # 1 March belongs to the consultation, so that is the sentence it becomes.
        ("The library will close on 1 March for repairs to the building.",
         "A consultation on opening hours closes on 1 March."),
        ("Smithy Bridge library will not close for repairs, the council said.", CLOSURE),  # negation
        ("The repairs will cost £2.5 for each resident in Smithy Bridge.", COST),       # £2.5m in total
    ):
        impact = li.build({"audience": "", "points": [wrong, GOOD_LIBRARY_POINT]}, **LIBRARY)
        assert impact is not None, wrong
        assert impact["points"][0] == right, (wrong, impact["points"])
        assert wrong not in impact["points"]


def test_a_point_with_nothing_to_correct_it_to_is_dropped():
    # Shares too few words with any sentence: no safe replacement exists.
    assert li.build({"audience": "", "points": [
        "Bin collections across Smithy Bridge move to a fortnightly timetable next spring.",
        GOOD_LIBRARY_POINT,
    ]}, **LIBRARY) is None


def test_two_points_corrected_to_the_same_sentence_appear_once():
    impact = li.build({"audience": "", "points": [
        "The library will close for 15 days of repairs from January.",
        "Smithy Bridge library will not close for repairs, the council said.",
        GOOD_LIBRARY_POINT,
    ]}, **LIBRARY)
    assert impact["points"] == [CLOSURE, GOOD_LIBRARY_POINT]


def test_true_restatements_of_the_library_story_survive():
    impact = li.build({"audience": "", "points": [
        "Smithy Bridge library will close on 15 January for 150 days of repairs.",
        "The repair work will cost £2.5m, funded by the council.",
        GOOD_LIBRARY_POINT,
    ]}, **LIBRARY)
    assert impact is not None and len(impact["points"]) == 3


def test_fewer_than_two_good_points_means_no_box_not_a_substitute():
    assert li.build({"audience": "", "points": [
        "Work on the Cartridge Street closure will continue for a maximum of 21 days.",
        "What will this mean for you?",
    ]}, **ROADWORKS) is None
    assert li.build({"audience": "", "points": []}, **ROADWORKS) is None
    assert li.build(None, **ROADWORKS) is None


def test_audience_needs_the_body_to_name_the_group():
    impact = li.build({"audience": "families", "points": [
        "Donations are accepted until 11 December at local libraries and leisure centres.",
        "Last year the appeal gave 10,000 toys to around 3,000 children.",
    ]}, **TOY_APPEAL)
    assert impact["audience"] == "families"
    assert li.build({"audience": "mums", "points": [
        "Donations are accepted until 11 December at local libraries and leisure centres.",
        "Last year the appeal gave 10,000 toys to around 3,000 children.",
    ]}, **TOY_APPEAL)["audience"] == ""


def test_crime_court_and_police_stories_never_get_a_box():
    points = {"audience": "", "points": [
        "Lodge Street was the scene of the vehicle stop on Wednesday 11 November.",
        "Cartledge is due at Manchester and Salford Magistrates' Court on 12 November.",
    ]}
    # Live example: a charge story filed under 'community'.
    assert li.build(points, title="Middleton man charged with assaulting emergency worker after Lodge Street stop",
                    excerpt="", paragraphs=["Lodge Street was the scene of the vehicle stop on Wednesday 11 November."],
                    category="community", area="middleton") is None
    assert li.build(points, **{**ROADWORKS, "category": "crime"}) is None
    assert li.build(points, **{**ROADWORKS, "sensitive": True}) is None
    assert li.build(points, **{**ROADWORKS, "category": "sport"}) is None


def test_unnamed_area_falls_back_to_the_borough_name():
    assert li.place_label("smithy_bridge", "Works at Smithy Bridge station") == "Smithy Bridge"
    assert li.place_label("norden", "A story about Bamford") == "Rochdale"
    assert li.place_label("rochdale", "Rochdale town centre") == "Rochdale"


def test_headings_vary_across_stories_but_never_within_one():
    slugs = [f"story-{n}" for n in range(200)]
    seen = {li.heading(s, "Norden") for s in slugs}
    assert seen == {h.format(place="Norden") for h in li.HEADINGS_PLACE}
    assert li.heading("same-slug", "Norden") == li.heading("same-slug", "Norden")
    with_group = {li.heading(s, "Heywood", "parents") for s in slugs}
    assert "What it means for Heywood parents" in with_group
    assert "For parents in Heywood" in with_group


def test_headings_spread_over_the_real_archive():
    data = json.loads((ROOT / "articles.json").read_text())
    articles = data["articles"] if isinstance(data, dict) else data
    counts = {}
    for article in articles:
        title = li.heading(article.get("slug") or "", "X")
        counts[title] = counts.get(title, 0) + 1
    # No single wording takes more than a third of the paper.
    assert max(counts.values()) <= len(articles) / 3


def test_render_escapes_and_places_box_at_the_end_of_the_report():
    impact = {"place": "Heywood", "audience": "", "points": [
        "Collection points are at <b>libraries</b>.", "Donations close on 11 December."]}
    box = li.render(impact, "slug")
    assert box.startswith('<section class="rd-impact"') and "&lt;b&gt;" in box
    paras = [f"<p>{n}</p>" for n in range(5)]
    out = li.paragraphs_with_box(paras, box)
    assert out == "".join(paras) + box
    assert li.paragraphs_with_box(paras, "") == "".join(paras)


def test_box_does_not_end_the_story_region_for_the_closing_sweep():
    import closing_filler_sweep as sweep
    box = li.render({"place": "Heywood", "audience": "", "points": [
        "Collection points are at local libraries.", "Donations close on 11 December."]}, "slug")
    page = ('<div class="article-copy">' + li.paragraphs_with_box(
        ["<p>One.</p>", "<p>Two.</p>", "<p>Three.</p>", "<p>Four, the real ending.</p>"], box)
        + '<section class="read-next"></section>')
    region = sweep.BODY.search(page).group(2)
    assert "Four, the real ending." in region
    # The sweep only edits attribute-free story <p>s; the box has none.
    assert [m.group(1) for m in sweep.STORY_P.finditer(region)][-1] == "Four, the real ending."


def test_schema_is_strict_compatible():
    import scraper
    schema = scraper.ARTICLE_SCHEMA["schema"]
    assert "local_impact" in schema["properties"]
    assert set(schema["required"]) == set(schema["properties"])
    sub = schema["properties"]["local_impact"]
    assert set(sub["required"]) == set(sub["properties"])
    assert sub["additionalProperties"] is False
