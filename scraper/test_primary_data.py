#!/usr/bin/env python3
"""Primary-data sources: parsers, the rota and the editorial exclusions.

Fixtures follow the real responses read on 9 October 2026 (the council
roadworks directory, The Gazette's notice feed, Parliament's written questions
API, a ModernGov RSS feed and the ONS local housing page).

Run:  PYTHONPATH=scraper python scraper/test_primary_data.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import primary_data as pd  # noqa: E402

NOW = datetime(2026, 10, 9, 19, 30, tzinfo=timezone.utc)


def road(record_id: int, slug: str, title: str) -> str:
    return (f'<li class="list__item"><a class="list__link" href="/directory-record/{record_id}/{slug}">'
            f'<span class="icon icon--small icon-ui-arrow-right"></span>'
            f'<span class="list__link-text">{title}</span></a></li>')


ROADWORKS_HTML = "<ul>" + "".join([
    road(2467, "a58-manchester-road", "A58 Manchester Road, Bolton Road and Silk Street, roadworks in Rochdale from 23 May 2026"),
    road(2580, "brandlehow-drive", "Brandlehow Drive, roadworks in Middleton on 12 October 2026"),
    road(2628, "todmorden-road", "Todmorden Road, roadworks in Littleborough from 10 October 2026"),
    road(2625, "norman-road", "Norman Road, temporary one-way working in Rochdale from 8 October 2026"),
    road(2626, "christmas-lights", "Littleborough Christmas Lights Event 2026, road closures in Littleborough on 28 November 2026"),
    road(2627, "church-street", "Church Street, roadworks in Littleborough from 12 October 2026"),
    road(2630, "no-date", "Smith Street, roadworks in Rochdale"),
    road(2631, "queensway", "Queensway, roadworks in Castleton from 14 October 2026"),
    road(2632, "hollin-lane", "Hollin Lane, roadworks in Middleton from 15 October 2026"),
]) + "</ul>"


def notice(notice_id: int, code: str, company: str, term: str, content: str = "") -> dict:
    return {"id": f"https://www.thegazette.co.uk/id/notice/{notice_id}", "f:status": "published",
            "f:notice-code": code, "title": company, "published": "2026-10-09T01:05:09",
            "category": {"@term": term},
            "content": f"<div><p>Name of Company: {company} Company Number: 16697327 {content}</p></div>"}


GAZETTE_JSON = {"f:total": "6", "entry": [
    notice(5227571, "2443", "KAM PAYROLL LTD", "Appointment of Liquidators", "Registered office: Heywood OL10 2TA"),
    notice(5227556, "2441", "KAM PAYROLL LTD", "Resolutions for Winding-up"),
    notice(5226083, "2450", "DRIVE 2000 LIMITED", "Petitions to Wind Up (Companies)"),
    notice(5220998, "2452", "RICO FACILITIES LTD", "Winding-Up Orders", "Castleton, Rochdale OL11 2QQ"),
    notice(5220001, "2503", "A PRIVATE PERSON", "Bankruptcy Orders"),
    notice(5220002, "2903", "ANOTHER PRIVATE PERSON", "Deceased Estates"),
]}


def question(uin: str, heading: str | None, answered: str | None, **extra) -> dict:
    value = {"id": 1, "askingMemberId": 5084, "dateTabled": "2026-09-07T00:00:00", "uin": uin,
             "questionText": "To ask the Secretary of State for Justice, how many delays were reported.",
             "answeringBodyName": "Ministry of Justice", "isWithdrawn": False, "answerIsHolding": False,
             "dateAnswered": answered, "answerText": "<p>There were 22 reports.</p>" if answered else None,
             "heading": heading}
    value.update(extra)
    return {"value": value}


QUESTIONS_BLUNDELL = {"totalResults": 4, "results": [
    question("27614", "Prisoner Escorts: Greater Manchester", "2026-09-15T00:00:00"),
    question("22752", "Water Charges", "2026-09-17T00:00:00"),
    question("22758", "LGBT+ People: Heywood and Middleton North", "2026-09-10T00:00:00"),
    question("22760", "Flood Control: Littleborough", "2026-09-16T00:00:00",
             questionText="To ask the Secretary of State what funding is allocated to the Littleborough flood scheme."),
    question("30963", None, None),
    question("30001", "Holding", "2026-09-18T00:00:00", answerIsHolding=True),
]}
QUESTIONS_WAUGH = {"totalResults": 0, "results": []}

GMCA_RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>GMCA</title>
<item><title>Middleton Mayoral Development Corporation Consultation Outcome - Approval to Designate</title>
<link>https://democracy.greatermanchester-ca.gov.uk/ieDecisionDetails.aspx?ID=4147</link><pubDate>Fri, 25 Sep 2026 10:00:00 GMT</pubDate></item>
<item><title><![CDATA[Middleton Mayoral Development Corporation Consultation Outcome - Approval to Designate]]></title>
<link>https://democracy.greatermanchester-ca.gov.uk/ieDecisionDetails.aspx?ID=4147</link></item>
<item><title>Rough Sleeping Funding 2026/27</title>
<link>https://democracy.greatermanchester-ca.gov.uk/ieDecisionDetails.aspx?ID=4142</link></item>
<item><title>Agenda published: Bee Network Committee</title>
<link>https://democracy.greatermanchester-ca.gov.uk/ieListDocuments.aspx?CId=136&amp;MId=5500</link></item>
</channel></rss>"""

ONS_HTML = """<html><head><script>var x = "Last updated: 1 January 2020";</script></head><body>
<h1>Housing prices in Rochdale</h1><p>Last updated: 16 September 2026</p>
<p>The average house price in Rochdale was £209,000 in July 2026 (provisional), up 4.5% from July 2025. This was similar to the rise in the North West.</p>
<p>Private rents rose to an average of £855 in August 2026, an annual increase of 8.5% from £788 in August 2025.</p></body></html>"""


class Response:
    def __init__(self, text: str = "", payload=None, status: int = 200):
        self.text, self._payload, self.status_code = text, payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class FakeWeb:
    def __init__(self, broken: tuple[str, ...] = ()):
        self.calls: list[str] = []
        self.broken = broken

    def __call__(self, url, params=None, timeout=None, **_):
        self.calls.append(url)
        if any(part in url for part in self.broken):
            return Response(status=503)
        if "directory/22" in url:
            return Response(ROADWORKS_HTML if not url.endswith("/2") else "<ul></ul>")
        if "thegazette" in url:
            assert params["location-local-authority-1"] == "rochdale"
            return Response(payload=GAZETTE_JSON)
        if "questions-statements-api" in url:
            return Response(payload=QUESTIONS_BLUNDELL if params["askingMemberId"] == "5084" else QUESTIONS_WAUGH)
        if "greatermanchester-ca" in url:
            return Response(GMCA_RSS)
        if "ons.gov.uk" in url:
            return Response(ONS_HTML)
        raise AssertionError(f"unexpected request: {url}")


def run(state=None, now=NOW, web=None, only=None):
    state = state if state is not None else {"sources": {}}
    records, report = pd.collect(web or FakeWeb(), state, now, only=only)
    return records, report, state


def by_source(records, key):
    return [r for r in records if r["source_key"] == key]


class Roadworks(unittest.TestCase):
    def test_listing_is_parsed_with_ids_titles_and_start_dates(self):
        rows = pd.parse_roadworks_listing(ROADWORKS_HTML)
        self.assertEqual(len(rows), 9)
        self.assertEqual(rows[2]["id"], "2628")
        self.assertEqual(rows[2]["url"], "https://www.rochdale.gov.uk/directory-record/2628/todmorden-road")
        self.assertEqual((rows[2]["start"].year, rows[2]["start"].month, rows[2]["start"].day), (2026, 10, 10))
        self.assertIsNone(rows[6]["start"])

    def test_only_works_starting_soon_are_offered_soonest_first_up_to_the_daily_cap(self):
        records, report, state = run(only={"council_roadworks"})
        self.assertEqual([r["identity"] for r in records], ["2625", "2628", "2580", "2627"])
        self.assertEqual(records[1]["area"], "littleborough")
        self.assertEqual(records[0]["category"], "traffic")
        stats = report["council_roadworks"]
        self.assertEqual((stats["listed"], stats["in_window"], stats["offered"]), (9, 6, 4))
        self.assertEqual(stats["started_long_ago"], 1, "works running since May are not news")
        self.assertEqual(stats["too_far_ahead"], 1, "the November closure waits until nearer the time")
        self.assertEqual(stats["undated"], 1)
        seen = state["sources"]["council_roadworks"]["seen"]
        self.assertIn("2467", seen)
        self.assertNotIn("2626", seen, "must stay unseen so it is offered in November")
        self.assertNotIn("2631", seen, "over the cap: waits for tomorrow")

    def test_the_rest_follow_the_next_day_and_nothing_is_offered_twice(self):
        _, _, state = run(only={"council_roadworks"})
        same_day, report, _ = run(state, NOW + timedelta(hours=1), only={"council_roadworks"})
        self.assertEqual(same_day, [])
        self.assertEqual(report["council_roadworks"]["status"], "not due")
        next_day, _, _ = run(state, NOW + timedelta(hours=20), only={"council_roadworks"})
        self.assertEqual([r["identity"] for r in next_day], ["2631", "2632"])

    def test_a_far_off_closure_is_offered_when_it_comes_into_the_window(self):
        _, _, state = run(only={"council_roadworks"})
        later, _, _ = run(state, datetime(2026, 11, 16, 9, 0, tzinfo=timezone.utc), only={"council_roadworks"})
        self.assertIn("2626", [r["identity"] for r in later])


class Gazette(unittest.TestCase):
    def test_company_outcomes_only_one_story_per_company_and_no_private_individuals(self):
        records, report, state = run(only={"gazette_insolvency"})
        self.assertEqual([r["source_title"] for r in records],
                         ["KAM PAYROLL LTD: Appointment of Liquidators", "RICO FACILITIES LTD: Winding-Up Orders"])
        self.assertEqual(records[0]["source_url"], "https://www.thegazette.co.uk/notice/5227571")
        self.assertEqual(records[0]["area"], "heywood")
        text = json.dumps(records)
        for excluded in ("PRIVATE PERSON", "DRIVE 2000", "Bankruptcy", "Deceased", "Petition"):
            self.assertNotIn(excluded, text)
        self.assertEqual(report["gazette_insolvency"]["other_notice_types"], 3)
        again, _, _ = run(state, NOW + timedelta(days=1), only={"gazette_insolvency"})
        self.assertEqual(again, [], "the company's second notice is not a second story")

    def test_only_reviewed_notice_types_are_enabled(self):
        self.assertEqual(set(pd.GAZETTE_NOTICE_CODES), {"2441", "2443", "2452"})
        self.assertFalse([code for code in pd.GAZETTE_NOTICE_CODES if code.startswith(("25", "29"))])


class WrittenAnswers(unittest.TestCase):
    def test_answered_questions_become_records_with_the_official_page_address(self):
        records, report, _ = run(only={"written_answers"})
        self.assertEqual([r["identity"] for r in records], ["2026-09-07/22760", "2026-09-07/22758"],
                         "newest answer first; only exchanges that name a place in the borough")
        first = records[0]
        self.assertEqual(first["source_url"],
                         "https://questions-statements.parliament.uk/written-questions/detail/2026-09-07/22760")
        self.assertIn("Heywood and Middleton North MP Elsie Blundell", first["source_title"])
        self.assertIn("There were 22 reports.", first["source_summary"])
        self.assertEqual((first["area"], first["category"]), ("heywood", "politics"))
        stats = report["written_answers"]
        self.assertEqual(stats["unanswered_or_holding"], 2)
        self.assertEqual(stats["not_about_the_borough"], 2, "water bills and Manchester prison escorts are not borough news")


class GmcaDecisions(unittest.TestCase):
    def test_only_decisions_naming_a_borough_place_once_each(self):
        records, report, state = run(only={"gmca_decisions"})
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["source_url"],
                         "https://democracy.greatermanchester-ca.gov.uk/ieDecisionDetails.aspx?ID=4147")
        self.assertEqual(records[0]["area"], "middleton")
        stats = report["gmca_decisions"]
        self.assertEqual((stats["no_borough_place"], stats["not_decisions"]), (1, 1))
        self.assertIn("4142", state["sources"]["gmca_decisions"]["seen"])


class OnsHousing(unittest.TestCase):
    def test_one_story_per_release_with_the_ons_sentences_as_its_summary(self):
        records, _, state = run(only={"ons_housing"})
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertTrue(record["source_url"].endswith("/E08000005/#updated-16-september-2026"))
        self.assertIn("£209,000 in July 2026 (provisional), up 4.5% from July 2025.", record["source_summary"])
        self.assertIn("£855 in August 2026, an annual increase of 8.5% from £788 in August 2025.", record["source_summary"])
        again, report, _ = run(state, NOW + timedelta(days=2), only={"ons_housing"})
        self.assertEqual(again, [])
        self.assertEqual(report["ons_housing"]["already_seen"], 1)

    def test_a_changed_page_offers_nothing_rather_than_a_guess(self):
        class Changed(FakeWeb):
            def __call__(self, url, params=None, timeout=None, **_):
                return Response("<html><body><p>Last updated: 16 October 2026</p><p>New layout.</p></body></html>")
        records, report, state = run(web=Changed(), only={"ons_housing"})
        self.assertEqual(records, [])
        self.assertEqual(report["ons_housing"]["unreadable"], 1)
        self.assertEqual(state["sources"]["ons_housing"]["seen"], [])


class Rota(unittest.TestCase):
    def test_every_source_has_an_interval_and_a_cap(self):
        self.assertEqual(set(pd.ROTA), set(pd.SOURCES))
        for interval, cap in pd.ROTA.values():
            self.assertGreaterEqual(interval, 6, "no source needs reading more than four times a day")
            self.assertGreaterEqual(cap, 1)

    def test_a_source_is_not_fetched_again_until_its_interval_has_passed(self):
        web = FakeWeb()
        _, _, state = run(web=web)
        first_calls = len(web.calls)
        _, report, _ = run(state, NOW + timedelta(minutes=15), web=web)
        self.assertEqual(len(web.calls), first_calls, "a 15-minute newsroom run must not re-read anything")
        self.assertTrue(all(row["status"] == "not due" for row in report.values()))

    def test_one_broken_source_is_reported_and_the_others_still_run(self):
        records, report, state = run(web=FakeWeb(broken=("thegazette",)))
        self.assertEqual(report["gazette_insolvency"]["status"], "error")
        self.assertIn("503", report["gazette_insolvency"]["error"])
        self.assertTrue(by_source(records, "council_roadworks"))
        self.assertTrue(by_source(records, "written_answers"))
        self.assertFalse(pd.is_due(state, "gazette_insolvency", NOW + timedelta(hours=1)),
                         "a failing source waits a full interval, it is not retried every run")

    def test_state_survives_a_round_trip_and_an_unreadable_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reports" / "primary_data_state.json"
            _, _, state = run()
            pd.save_state(path, state)
            again, _, _ = run(pd.load_state(path), NOW + timedelta(minutes=30))
            self.assertEqual(again, [])
            path.write_text("{ not json", encoding="utf-8")
            self.assertEqual(pd.load_state(path), {"sources": {}})

    def test_every_offered_page_is_on_an_approved_official_host(self):
        from claim_evidence import is_primary
        records, _, _ = run()
        self.assertGreaterEqual(len(records), 9)
        for record in records:
            self.assertTrue(is_primary(record["source_url"]), record["source_url"])


class Wiring(unittest.TestCase):
    def test_collector_is_registered_reported_and_its_state_is_committed(self):
        root = Path(__file__).resolve().parent
        scraper = (root / "scraper.py").read_text(encoding="utf-8")
        self.assertIn("'primary_data': safe_collect('primary_data', collect_primary_data_candidates", scraper)
        self.assertIn("'primary_data': dict(PRIMARY_DATA_REPORT)", scraper)
        publish = (root / "publish_newsroom_snapshot.sh").read_text(encoding="utf-8")
        self.assertIn("reports/primary_data_state.json", publish.split("stage_newsroom() {", 1)[1].split("\n}", 1)[0])

    def test_flood_warnings_point_at_the_readable_page_not_the_json_record(self):
        scraper = (Path(__file__).resolve().parent / "scraper.py").read_text(encoding="utf-8")
        self.assertIn("https://check-for-flooding.service.gov.uk/target-area/", scraper)


if __name__ == "__main__":
    unittest.main()
