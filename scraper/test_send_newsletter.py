#!/usr/bin/env python3
"""The newsletter sends the day's briefing once, through Brevo, to the sign-up list.

Before 19 October 2026 sign-ups were collected and copied to Brevo, but no
campaign was ever sent.

Run:  PYTHONPATH=scraper python scraper/test_send_newsletter.py
"""
from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import send_newsletter as mail  # noqa: E402

MORNING = datetime(2026, 10, 20, 8, 30, tzinfo=timezone.utc)      # 09:30 London
ENV = {"BREVO_API_KEY": "xkeysib-test", "BREVO_LIST_ID": "7"}
BRIEFING = {
    "slug": "morning-briefing-20-october-2026", "title": "Morning Briefing: Tuesday 20 October 2026",
    "briefing_slot": "morning", "first_published_at": "2026-10-20T08:11:12Z",
    "content_html": '<p>3 new stories.</p><ul><li><a href="/articles/a-story.html"><strong>A story</strong></a></li></ul>'
                    '<p class="brief-foot">The Morning Briefing is published every day at 9am.</p>',
}


class Brevo:
    def __init__(self, existing=(), list_status=200, create_status=201, send_status=204):
        self.existing, self.list_status = list(existing), list_status
        self.create_status, self.send_status = create_status, send_status
        self.created: list[dict] = []
        self.sent: list[str] = []
        self.calls: list[str] = []

    def __call__(self, url, *, method="GET", headers=None, body=None):
        self.calls.append(f"{method} {url}")
        assert headers["api-key"] == "xkeysib-test"
        if url.startswith(mail.BREVO + "/emailCampaigns?"):
            return self.list_status, json.dumps({"campaigns": [{"name": n} for n in self.existing]})
        if url == mail.BREVO + "/emailCampaigns" and method == "POST":
            self.created.append(json.loads(body))
            return self.create_status, json.dumps({"id": 42} if self.create_status == 201 else {"message": "sender not valid"})
        if url.endswith("/sendNow"):
            self.sent.append(url)
            return self.send_status, ""
        raise AssertionError(url)


def run(web=None, env=ENV, now=MORNING, articles=None):
    web = web or Brevo()
    return mail.run(dict(env), now, web, [BRIEFING] if articles is None else articles), web


class Sending(unittest.TestCase):
    def test_todays_briefing_is_created_and_sent_to_the_signup_list(self):
        report, web = run()
        self.assertTrue(report["sent"], report)
        campaign = web.created[0]
        self.assertEqual(campaign["name"], "Rochdale Daily briefing 2026-10-20")
        self.assertEqual(campaign["subject"], "Morning Briefing: Tuesday 20 October 2026")
        self.assertEqual(campaign["recipients"], {"listIds": [7]})
        # Clean address plus utm tags, so Analytics counts what the email brings back.
        self.assertIn('href="https://rochdaledaily.co.uk/articles/a-story?utm_source=newsletter&amp;utm_medium=email&amp;utm_campaign=morning-briefing"', campaign["htmlContent"])
        self.assertIn('width="600"', campaign["htmlContent"])
        self.assertIn("{{ unsubscribe }}", campaign["htmlContent"])
        self.assertNotIn("published every day at 9am", campaign["htmlContent"])
        self.assertEqual(web.sent, [mail.BREVO + "/emailCampaigns/42/sendNow"])

    def test_a_second_run_the_same_day_sends_nothing(self):
        report, web = run(Brevo(existing=["Rochdale Daily briefing 2026-10-20"]))
        self.assertEqual((web.created, web.sent), ([], []))
        self.assertIn("already been created", report["status"])

    def test_a_refused_sender_is_reported_as_an_error(self):
        report, web = run(Brevo(create_status=400))
        self.assertFalse(report["sent"])
        self.assertTrue(report.get("error"))
        self.assertIn("sender not valid", report["status"])


class NotSending(unittest.TestCase):
    def test_without_configuration_nothing_is_contacted_and_the_gap_is_named(self):
        report, web = run(env={})
        self.assertEqual(web.calls, [])
        self.assertIn("BREVO_API_KEY", report["status"])
        self.assertIn("BREVO_LIST_ID", report["status"])
        self.assertFalse(report.get("error"), "an unconfigured newsletter must not fail the workflow")

    def test_no_briefing_today_means_no_email(self):
        report, web = run(articles=[dict(BRIEFING, first_published_at="2026-10-19T08:10:00Z")])
        self.assertEqual(web.calls, [])
        self.assertIn("no Morning Briefing", report["status"])

    def test_a_morning_newsletter_is_not_sent_in_the_afternoon(self):
        report, web = run(now=datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc))
        self.assertEqual(web.calls, [])
        self.assertIn("outside the sending window", report["status"])

    def test_dry_run_checks_brevo_but_sends_nothing(self):
        report, web = run(env=dict(ENV, NEWSLETTER_DRY_RUN="true"))
        self.assertEqual((web.created, web.sent), ([], []))
        self.assertIn("would send", report["status"])

    def test_a_bad_key_is_an_error_not_a_silent_skip(self):
        report, web = run(Brevo(list_status=401))
        self.assertEqual(web.created, [])
        self.assertTrue(report.get("error"))


if __name__ == "__main__":
    unittest.main()
