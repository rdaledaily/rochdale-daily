"""Monday "Rochdale arrests this week" round-up (editor, 17 Nov 2026).

Fixtures are real Rochdale Daily headlines measured on 17 Nov 2026, including
the false hits the first draft of the classifier produced.
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import manual_articles  # noqa: E402
import story_identity  # noqa: E402
import weekly_arrests as w  # noqa: E402


def crime(title, excerpt="", category="crime"):
    return {"title": title, "excerpt": excerpt, "category": category}


def test_stages_from_real_headlines():
    cases = {
        "Man arrested after suspected air pistol found near Rochdale Armistice Day ceremony": "arrested",
        "Middleton man charged with attempted murder and three aggravated burglaries": "charged",
        "Kyle Howard pleads guilty to murder of wife Keeley Aspinall in Rochdale": "court",
        "Rochdale man who managed 'Adam' drug line dealers jailed for 10 and a half years": "sentenced",
        "Heywood Man Receives Suspended Sentence for Cocaine Supply": "sentenced",
        "Rochdale man loses appeal against murder conviction at Court of Appeal": "appeal",
        "Eighth arrest in property damage investigation covering Rochdale": "arrested",
    }
    for title, stage in cases.items():
        assert w.stage_of(crime(title)) == stage, title


def test_furthest_stage_wins():
    # Charged AND remanded AND jailed in one headline: listed once, as sentenced.
    assert w.stage_of(crime("Man arrested, charged and jailed after Heywood raid")) == "sentenced"


def test_not_a_case():
    false_hits = [
        crime("Police search for man who helped woman after alleged sexual assault in Rochdale"),
        crime("Police appeal for help finding Kibriya Ahmed linked to missing children"),
        crime("Dunelm Rochdale shoppers fill store with Christmas gifts for Delivering Joy appeal", category="business"),
        crime("Rochdale council deputy leader detained briefly in Pakistan during civic visit", category="politics"),
        crime("Hopwood Hall: DePree's appeal deadline nears after High Court defeat", category="news"),
        crime("Inquest reveals details surrounding death of former rugby player", "arrested", category="sport"),
        crime("Warning issued over e-bikes and e-scooters ahead of Christmas"),
    ]
    for story in false_hits:
        assert w.stage_of(story) is None, story["title"]


def test_week_window_is_previous_monday_to_sunday_london():
    now = datetime(2026, 11, 16, 8, 5, tzinfo=w.LONDON)
    start, end = w.week_window(now)
    assert (start.isoformat(), end.isoformat()) == (
        "2026-11-09T00:00:00+00:00", "2026-11-16T00:00:00+00:00")
    summer = datetime(2026, 7, 6, 8, 5, tzinfo=w.LONDON)
    start, end = w.week_window(summer)
    assert start.utcoffset().total_seconds() == 3600 and start.day == 29 and end.day == 6


def test_due_only_monday_morning_london():
    assert w.is_due(datetime(2026, 11, 16, 8, 0, tzinfo=w.LONDON))
    assert w.is_due(datetime(2026, 7, 6, 8, 0, tzinfo=w.LONDON))      # BST
    assert not w.is_due(datetime(2026, 11, 16, 7, 59, tzinfo=w.LONDON))
    assert not w.is_due(datetime(2026, 11, 16, 12, 0, tzinfo=w.LONDON))
    assert not w.is_due(datetime(2026, 11, 17, 8, 0, tzinfo=w.LONDON))


def _fake_week(monkeypatch, stories):
    monkeypatch.setattr(w, "load", lambda path, default: stories if path == w.ARTICLES else default)


def test_build_groups_and_counts(monkeypatch):
    _fake_week(monkeypatch, [
        {"slug": "a", "title": "Man arrested after Castleton break-in", "category": "crime",
         "area": "castleton", "excerpt": "A 30-year-old man was arrested.", "first_published_at": "2026-11-10T09:00:00Z"},
        {"slug": "b", "title": "Middleton man charged with burglary", "category": "crime",
         "area": "middleton", "first_published_at": "2026-11-11T09:00:00Z"},
        {"slug": "c", "title": "Heywood man jailed for robbery", "category": "crime",
         "first_published_at": "2026-11-12T09:00:00Z"},
        {"slug": "old", "title": "Man arrested last month", "category": "crime",
         "first_published_at": "2026-10-01T09:00:00Z"},
        {"slug": "gone", "title": "Man charged", "category": "crime", "status": "removed",
         "first_published_at": "2026-11-12T09:00:00Z"},
        {"slug": "morning-briefing-x", "id": "briefing-x", "title": "Man arrested in briefing",
         "category": "crime", "first_published_at": "2026-11-12T09:00:00Z"},
    ])
    a = w.build(datetime(2026, 11, 16, 8, 5, tzinfo=w.LONDON))
    assert a["week_counts"] == {"arrested": 1, "charged": 1, "court": 0, "sentenced": 1, "appeal": 0}
    assert a["title"] == "Rochdale arrests this week: 16 November 2026"
    assert a["slug"] == "rochdale-arrests-this-week-16-november-2026"
    assert "1 arrest, 1 charge and 1 sentencing" in a["excerpt"]
    assert "Monday 9 November to Sunday 15 November 2026" in a["excerpt"]
    assert a["content_html"].index("<h2>Arrested</h2>") < a["content_html"].index("<h2>Sentenced</h2>")
    assert "presumed innocent" in a["content_html"]
    assert "/articles/old.html" not in a["content_html"]
    assert "/articles/gone.html" not in a["content_html"]
    assert a["category"] == "crime" and a["related_article_slugs"]


def test_quiet_week_says_so(monkeypatch):
    _fake_week(monkeypatch, [])
    a = w.build(datetime(2026, 11, 16, 8, 5, tzinfo=w.LONDON))
    assert "reported no arrests, charges, court cases, sentencings or appeals" in a["excerpt"]
    assert "<h2>" not in a["content_html"]


def test_html_survives_manual_publication(monkeypatch):
    _fake_week(monkeypatch, [
        {"slug": "a", "title": "Man arrested after Castleton break-in", "category": "crime",
         "area": "castleton", "excerpt": "A man was arrested.", "first_published_at": "2026-11-10T09:00:00Z"},
    ])
    a = w.build(datetime(2026, 11, 16, 8, 5, tzinfo=w.LONDON))
    monkeypatch.setattr(manual_articles, "taken_down_slugs", lambda: set())
    assert manual_articles._briefing_html(a) == a["content_html"]


def test_roundup_never_merges_with_a_story_it_lists():
    record = {"id": "briefing-arrests-rochdale-arrests-this-week-16-november-2026",
              "slug": "rochdale-arrests-this-week-16-november-2026"}
    assert story_identity._is_roundup(record)
    assert story_identity._is_roundup_like({"slug": record["slug"]})
