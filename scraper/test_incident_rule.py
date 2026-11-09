"""Blanket incident rule (editor, 9 Nov 2026): "emergency" in a headline is
Community with the red Incident card, in every lane, over every other rule."""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
ROOT = HERE.parent

import incident_rule as ir  # noqa: E402

MIDDLETON = {
    "slug": "emergency-services-respond-to-incident-in-middleton-town-centre",
    "title": "Emergency services respond to incident in Middleton town centre",
    "category": "business",
    "image_url": "assets/img/cards/8eb23c6532c8bbda-town-photo.jpg",
    "image_alt": "File photo: Middleton. Not a photograph of this event.",
    "image_status": "town-file-photo",
    "content_html": "<p>Emergency services responded to an incident in Middleton town centre.</p>",
}


def test_card_exists_and_is_a_real_image():
    card = ROOT / ir.INCIDENT_CARD
    assert card.is_file() and card.stat().st_size > 4096


def test_word_forms():
    assert ir.is_incident_title("Emergency services called")
    assert ir.is_incident_title("Council handles two EMERGENCIES")
    assert not ir.is_incident_title("Emergent plans for the market")


def test_not_incidents_keep_their_own_section_and_photo():
    # Editor, 9 Nov 2026: these use the word without anything happening.
    for title in (
        "Full house for National Emergency Briefing screening in Falinge",
        "Rochdale Council Portfolio Holders Attend National Emergency Briefing Screening",
        "Bamford Screening of National Emergency Briefing Attracts Full Attendance",
        "Urgent Action Needed to Address Climate Emergency in Rochdale",
        "Labour Considers Emergency Law to Deport Rochdale Rape Gang Leader",
        "Middleton Residents Can Access Local and Emergency Plumbing Services",
        "Emergencies \u2013 Rochdale Borough Council",
        "Rochdale Council Provides Emergency Update Information",
    ):
        assert not ir.is_incident_title(title), title
    for title in (
        "Emergency services respond to incident in Middleton town centre",
        "Woman dies at Tesco in Rochdale after emergency services called",
        "Wildfire emergency alert: an overreaction, or a sign of things to come?",
    ):
        assert ir.is_incident_title(title), title
    import frontpage_pipeline as fp
    assert fp.headline_category_rule("Labour considers emergency law to deport rape gang leader") == "crime"


def test_live_feed_category_and_card_beat_editor_lock():
    import frontpage_pipeline as fp
    assert fp.headline_category_rule(MIDDLETON["title"]) == "community"
    record = fp.apply_category_rules(dict(MIDDLETON, editorial_lock=True, police_matter=True))
    assert record["category"] == "community"
    assert record["image_url"] == ir.INCIDENT_CARD
    assert record["police_matter"] is False


def test_archive_category():
    from editorial_contract import category_for
    assert category_for(dict(MIDDLETON)) == "community"


def test_image_lanes_and_police_photo():
    import ensure_article_images as e
    import image_hierarchy as ih
    import source_presentation as sp
    crime = dict(MIDDLETON, title="Man charged with offence after emergency services called", category="crime",
                 content_html="<p>A man was charged with an offence.</p>")
    assert e.enforce_article(dict(MIDDLETON), ROOT) == "incident-card"
    assert ih.choose_image(dict(MIDDLETON), ROOT, allow_network=False) == "incident"
    assert sp.enforce_police_image(dict(crime))["image_url"] == ir.INCIDENT_CARD


def test_page_render():
    import generate_pages as gp
    page = gp.render_article_page(dict(MIDDLETON, published_at="2026-07-22T16:39:00Z"), [])
    assert '/news/community.html">Community</a>' in page
    assert "incident-card.jpg" in page
    assert "town-photo" not in page


def test_backfill_is_idempotent(tmp_path):
    import apply_incident_rule as backfill
    (tmp_path / "articles").mkdir()
    page = ('<meta property="og:image" content="https://rochdaledaily.co.uk/assets/img/cards/x-town-photo.jpg">'
            '<meta property="article:section" content="Business">'
            '<nav class="article-breadcrumb" aria-label="Breadcrumb"><a href="../">Home</a>'
            '<span aria-hidden="true">›</span><a href="../#business">Business</a></nav>'
            '<h1>' + MIDDLETON["title"] + '</h1><figure class="article-hero-image"><img src="/x.jpg" alt="">'
            '<figcaption>File photo</figcaption></figure><div class="article-copy"><p>x</p></div>')
    (tmp_path / "articles" / "a.html").write_text(page, encoding="utf-8")
    (tmp_path / "articles" / "archive.json").write_text(json.dumps({"articles": [dict(MIDDLETON)]}), encoding="utf-8")
    first = backfill.main(tmp_path)
    assert first == {"records": 1, "index_records": 0, "pages": 1}
    fixed = (tmp_path / "articles" / "a.html").read_text(encoding="utf-8")
    assert '/news/community.html">Community</a>' in fixed and "incident-card.jpg" in fixed
    assert "town-photo" not in fixed and 'content="Community"' in fixed
    assert backfill.main(tmp_path) == {"records": 0, "index_records": 0, "pages": 0}


def test_crashes_and_health_emergencies_get_the_card_in_their_own_section():
    # Editor, 9 Nov 2026: health emergencies, crashes and collisions get the
    # card; they keep their section, and crime crashes keep Crime + police photo.
    import frontpage_pipeline as fp
    crash = {"title": "Two men injured in Heywood crash on Moss Hall Road", "category": "traffic",
             "content_html": "<p>Two men were injured in a crash on Moss Hall Road.</p>",
             "image_url": "assets/img/cards/x-town-photo.jpg"}
    record = fp.apply_category_rules(dict(crash))
    assert record["category"] == "traffic"
    assert record["image_url"] == ir.INCIDENT_CARD
    assert ir.wants_incident_card({"title": "Man collapsed at bus station", "category": "health"})
    assert not ir.wants_incident_card({"title": "Man arrested following two-vehicle collision near Norden",
                                       "category": "crime"})
    assert not ir.wants_incident_card({"title": "Driver crashes into wall", "category": "crime"})
    assert not ir.wants_incident_card({"title": "Traffic incident at Caliber Collision in Middleton",
                                       "category": "traffic"})
    # A stale police flag on an archived traffic record does not block the card.
    assert ir.wants_incident_card({"title": "Appeal after collision in Heywood", "category": "traffic",
                                   "police_matter": True})


def test_crash_page_keeps_its_section(tmp_path):
    import apply_incident_rule as backfill
    (tmp_path / "articles").mkdir()
    page = ('"articleSection": "traffic"<meta property="article:section" content="Traffic">'
            '<nav class="article-breadcrumb" aria-label="Breadcrumb"><a href="../">Home</a>'
            '<span aria-hidden="true">/</span><a href="/news/traffic.html">Traffic</a></nav>'
            '<h1>Crash closes Heywood Old Road</h1><figure class="article-hero-image"><img src="/x.jpg" alt="">'
            '</figure><div class="article-copy"><p>x</p></div>')
    (tmp_path / "articles" / "b.html").write_text(page, encoding="utf-8")
    assert backfill.main(tmp_path)["pages"] == 1
    fixed = (tmp_path / "articles" / "b.html").read_text(encoding="utf-8")
    assert "incident-card.jpg" in fixed and ">Traffic</a>" in fixed and 'content="Traffic"' in fixed
