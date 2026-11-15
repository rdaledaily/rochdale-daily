"""Follow-up desk: top stories updated in place only on a verified development."""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import top_story_followups as fu  # noqa: E402

NOW = datetime(2026, 11, 15, 18, 10, tzinfo=timezone.utc)
GMP = "https://www.gmp.police.uk/news/greater-manchester/news/news/2026/november/man-charged-heywood/"
MEN = "https://www.manchestereveningnews.co.uk/news/greater-manchester-news/heywood-charged-123"
MEN_ROAD = "https://www.manchestereveningnews.co.uk/news/greater-manchester-news/m62-reopens-456"
GMP_TEXT = ("Menu Home News A man has been charged following a burglary at a house on York Street in Heywood. "
            "Daniel Smith, 34, of Bury Road, has been charged with burglary and will appear at Manchester and "
            "Salford Magistrates Court on 16 November 2026. Detective Constable Jo Brown said: \"We are grateful "
            "to the community in Heywood for their help.\"")
ROAD_TEXT = ("The M62 has reopened near Milnrow after a lorry hit the central reservation. National Highways said "
             "all lanes between junction 21 and junction 22 reopened shortly after 7pm on Sunday evening.")


def site(tmp: Path, manual: bool = True) -> None:
    (tmp / "articles").mkdir()
    (tmp / "reports").mkdir()
    (tmp / "manual_articles.d").mkdir()
    rows = [
        {"slug": "heywood-burglary-york-street", "title": "Burglary at house on York Street in Heywood",
         "category": "crime", "published_at": "2026-11-14T10:00:00Z", "manual_article": manual,
         "source_url": GMP, "source_urls": [GMP], "source_name": "Greater Manchester Police",
         "content_html": "<p>Police are investigating a burglary at a house on York Street in Heywood.</p><p>Officers want to hear from witnesses.</p>"},
        {"slug": "morning-briefing-15-november-2026", "title": "Morning Briefing", "briefing_slot": "morning",
         "published_at": "2026-11-15T09:00:00Z"},
        {"slug": "m62-closed-near-milnrow-lorry-central-reservation", "title": "M62 closed near Milnrow after lorry hits central reservation",
         "category": "traffic", "published_at": "2026-11-15T17:28:00Z", "manual_article": True,
         "source_url": "https://www.lancashiretelegraph.co.uk/news/1/", "source_urls": ["https://www.lancashiretelegraph.co.uk/news/1/"]},
    ]
    (tmp / "articles" / "frontpage.json").write_text(json.dumps({"articles": rows}))
    (tmp / "articles.json").write_text(json.dumps(rows))
    if manual:
        entry = {k: rows[0][k] for k in ("slug", "title", "category", "published_at", "source_url", "source_urls")}
        entry.update({"id": "rd-1", "manual_article": True,
                      "body": "Police are investigating a burglary at a house on York Street in Heywood.\n\nOfficers want to hear from witnesses."})
        (tmp / "manual_articles.d" / "2026-11-14-heywood-burglary.json").write_text(json.dumps(entry))
    m62 = {"id": "rd-2", "slug": rows[2]["slug"], "title": rows[2]["title"], "category": "traffic",
           "manual_article": True, "source_urls": rows[2]["source_urls"],
           "body": "The M62 was closed near junction 21 at Milnrow on Sunday afternoon.\n\nSource: Lancashire Telegraph."}
    (tmp / "manual_articles.d" / "2026-11-15-m62.json").write_text(json.dumps(m62))


class FakeClient:
    def __init__(self, answers):
        self.answers = answers
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        payload = json.loads(kwargs["messages"][1]["content"])
        self.calls += 1
        title = payload["story"]["title"]
        devs = self.answers.get(title, [])
        msg = SimpleNamespace(content=json.dumps({"developments": devs}))
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def fetcher(pages):
    def fetch(url):
        if url not in pages:
            raise IOError("no page")
        return pages[url]
    return fetch


def search(results):
    return lambda query: results.get("all", [])


CHARGE = {"type": "charged", "source_url": GMP, "same_incident": True, "already_in_story": False,
          "source_quote": "Daniel Smith, 34, of Bury Road, has been charged with burglary",
          "update": "Greater Manchester Police said Daniel Smith, 34, of Bury Road, has been charged with burglary and will appear at Manchester and Salford Magistrates Court on 16 November.",
          "headline": "Man, 34, charged after burglary on York Street in Heywood"}


def test_official_charge_applies_on_second_look_when_gmp_page_changes():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        site(tmp)
        title = "Burglary at house on York Street in Heywood"
        client = FakeClient({title: [CHARGE]})
        # First run: baseline fingerprint of the GMP page, nothing new.
        fu.run(True, 5, client, fetcher({GMP: "Police are investigating a burglary on York Street in Heywood."}),
               search({}), approvals=set(), root=tmp, when=NOW)
        assert client.calls == 0
        # An hour later GMP has updated the same page with a charge.
        counts = fu.run(True, 5, client, fetcher({GMP: GMP_TEXT}), search({}), approvals=set(), root=tmp,
                        when=NOW + timedelta(minutes=61))
        assert counts["updated"] == 1, counts
        entry = json.loads((tmp / "manual_articles.d" / "2026-11-14-heywood-burglary.json").read_text())
        paras = entry["body"].split("\n\n")
        assert paras[0].startswith("Police are investigating"), paras
        assert paras[1].startswith("Update, 15 November 2026, 7.11pm: Greater Manchester Police said Daniel Smith"), paras[1]
        assert entry["title"] == CHARGE["headline"]
        assert entry["previous_titles"] == [title]
        assert entry["last_updated_at"] == "2026-11-15T19:11:00Z"


def test_charge_reported_only_by_news_outlet_is_held_then_applied_after_approval():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        site(tmp)
        title = "Burglary at house on York Street in Heywood"
        men_charge = {**CHARGE, "source_url": MEN,
                      "update": "The Manchester Evening News reported that Daniel Smith, 34, of Bury Road, has been charged with burglary."}
        client = FakeClient({title: [men_charge]})
        results = {"all": [{"link": MEN, "source_href": "https://www.manchestereveningnews.co.uk",
                            "published": NOW - timedelta(hours=1), "title": "Man charged"}]}
        pages = {MEN: "Burglary York Street Heywood house " + GMP_TEXT, GMP: "Police are investigating a burglary."}
        fu.run(True, 5, client, fetcher(pages), search(results), approvals=set(), root=tmp, when=NOW)
        report = json.loads((tmp / "reports" / "top_story_followups.json").read_text())
        assert len(report["held_for_editor"]) == 1
        held = report["held_for_editor"][0]
        assert "update" not in held and "Daniel" not in json.dumps(held), "draft wording must not be public"
        entry = json.loads((tmp / "manual_articles.d" / "2026-11-14-heywood-burglary.json").read_text())
        assert "Update," not in entry["body"]
        # The editor approves it on /checked; the next run applies it.
        fu.run(True, 5, client, fetcher(pages), search(results), approvals={held["id"]}, root=tmp,
               when=NOW + timedelta(minutes=61))
        entry = json.loads((tmp / "manual_articles.d" / "2026-11-14-heywood-burglary.json").read_text())
        assert "Update, 15 November 2026" in entry["body"]
        report = json.loads((tmp / "reports" / "top_story_followups.json").read_text())
        assert report["held_for_editor"] == []


def test_road_reopening_from_outlet_applies_and_gates_reject_invention():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        site(tmp)
        title = "M62 closed near Milnrow after lorry hits central reservation"
        good = {"type": "road_reopened", "source_url": MEN_ROAD, "same_incident": True, "already_in_story": False,
                "source_quote": "all lanes between junction 21 and junction 22 reopened shortly after 7pm",
                "update": "The Manchester Evening News reported that National Highways said all lanes between junction 21 and junction 22 reopened shortly after 7pm on Sunday.",
                "headline": "M62 reopens near Milnrow after lorry hit central reservation"}
        invented = {**good, "type": "official_statement",
                    "source_quote": "the driver was taken to hospital with minor injuries today",
                    "update": "The Manchester Evening News reported that the driver, 52, was taken to hospital."}
        client = FakeClient({title: [invented, good]})
        results = {"all": [{"link": MEN_ROAD, "source_href": "https://www.manchestereveningnews.co.uk",
                            "published": NOW, "title": "M62 reopens"}]}
        counts = fu.run(True, 5, client, fetcher({MEN_ROAD: ROAD_TEXT}), search(results), approvals=set(),
                        root=tmp, when=NOW + timedelta(minutes=5))
        assert counts["updated"] == 1 and counts["rejected"] == 1, counts
        entry = json.loads((tmp / "manual_articles.d" / "2026-11-15-m62.json").read_text())
        assert entry["title"] == good["headline"]
        assert MEN_ROAD in entry["source_urls"] and "Manchester Evening News" in entry["source_names"]
        events = json.loads((tmp / "reports" / "top_story_followups_events.json").read_text())
        rejected = [r for e in events for r in e.get("rejected", [])][0]
        report = json.loads((tmp / "reports" / "top_story_followups.json").read_text())
        assert report["updates_made"][0]["slug"] == "m62-closed-near-milnrow-lorry-central-reservation"
        assert "reasons" not in json.dumps(report) and "52" not in json.dumps(report), "rejection detail stays out of the public report"
        md = fu.summary(tmp)
        assert "APPLIED road_reopened" in md and "rejected official_statement" in md
        assert any("not verbatim" in r for r in rejected["reasons"])
        assert any("figure 52" in r for r in rejected["reasons"])


def test_briefings_skipped_cadence_respected_and_dry_run_writes_nothing():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        site(tmp)
        slugs = [r["slug"] for r in fu.load_targets(tmp, when=NOW)]
        assert "morning-briefing-15-november-2026" not in slugs and len(slugs) == 2
        title = "M62 closed near Milnrow after lorry hits central reservation"
        good = {"type": "road_reopened", "source_url": MEN_ROAD, "same_incident": True, "already_in_story": False,
                "source_quote": "all lanes between junction 21 and junction 22 reopened shortly after 7pm",
                "update": "The Manchester Evening News reported that all lanes between junction 21 and junction 22 reopened shortly after 7pm.",
                "headline": ""}
        results = {"all": [{"link": MEN_ROAD, "source_href": "https://www.manchestereveningnews.co.uk",
                            "published": NOW, "title": "M62 reopens"}]}
        before = (tmp / "manual_articles.d" / "2026-11-15-m62.json").read_text()
        counts = fu.run(False, 5, FakeClient({title: [good]}), fetcher({MEN_ROAD: ROAD_TEXT}), search(results),
                        approvals=set(), root=tmp, when=NOW)
        assert counts["checked"] == 2
        assert (tmp / "manual_articles.d" / "2026-11-15-m62.json").read_text() == before
        again = fu.run(False, 5, FakeClient({}), fetcher({}), search({}), approvals=set(), root=tmp,
                       when=NOW + timedelta(minutes=20))
        assert again["checked"] == 0, "checked within the hour: not due"


def test_non_manual_story_gets_override_file():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        site(tmp, manual=False)
        row = fu.load_targets(tmp, when=NOW)[0]
        source = {"url": GMP, "publisher": "Greater Manchester Police", "text": GMP_TEXT, "official": True}
        path = fu.apply_update(row, CHARGE, source, NOW, tmp)
        entry = json.loads(Path(path).read_text())
        assert Path(path).name == "followup-heywood-burglary-york-street.json"
        assert entry["manual_article"] and entry["editorial_lock"] and "content_html" not in entry
        assert entry["body"].split("\n\n")[1].startswith("Update, 15 November 2026, 6.10pm:")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
