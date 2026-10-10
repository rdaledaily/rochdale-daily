#!/usr/bin/env python3
"""The newsletter sends the day's briefing once, to consenting readers only.

Before 10 October 2026 the site collected newsletter sign-ups and sent nothing.

Run:  PYTHONPATH=scraper python scraper/test_send_newsletter.py
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import send_newsletter as mail  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
MORNING = datetime(2026, 10, 10, 8, 30, tzinfo=timezone.utc)      # 09:30 London
ENV = {"RESEND_API_KEY": "re_test", "NEWSLETTER_ADMIN_TOKEN": "admin-token"}
BRIEFING = {
    "slug": "morning-briefing-10-october-2026", "title": "Morning Briefing: Saturday 10 October 2026",
    "briefing_slot": "morning", "first_published_at": "2026-10-10T08:11:12Z",
    "content_html": '<p>3 new stories.</p><ul><li><a href="/articles/a-story.html"><strong>A story</strong></a></li></ul>'
                    '<p class="brief-foot">The Morning Briefing is published every day at 9am.</p>',
}
CSV = "email,consented_at,source\nreader@example.org,2026-09-01T10:00:00Z,homepage\nReader@Example.org,x,rail\nnot-an-address,x,y\nsecond@example.org,x,rail\n"


class Web:
    def __init__(self, last_sent: str = "", fail_for: str = "", list_status: int = 200):
        self.last_sent, self.fail_for, self.list_status = last_sent, fail_for, list_status
        self.sent: list[dict] = []
        self.marked: list[str] = []
        self.calls: list[str] = []

    def __call__(self, url, *, method="GET", headers=None, body=None):
        self.calls.append(f"{method} {url}")
        if "last_sent=1" in url:
            assert headers["x-admin-token"] == "admin-token"
            return self.list_status, json.dumps({"ok": True, "last_sent": self.last_sent})
        if "export=csv" in url:
            return self.list_status, CSV
        if "mark_sent=" in url:
            self.marked.append(url.rsplit("=", 1)[-1])
            return 200, "{}"
        if url == mail.RESEND_URL:
            payload = json.loads(body)
            payload["_key"] = headers["Idempotency-Key"]
            assert headers["Authorization"] == "Bearer re_test"
            if payload["to"][0] == self.fail_for:
                return 422, '{"message":"invalid"}'
            self.sent.append(payload)
            return 200, '{"id":"x"}'
        raise AssertionError(url)


def run(web=None, env=ENV, now=MORNING, articles=None):
    web = web or Web()
    return mail.run(dict(env), now, web, [BRIEFING] if articles is None else articles), web


class Sending(unittest.TestCase):
    def test_each_consenting_reader_gets_todays_briefing_once(self):
        report, web = run()
        self.assertEqual((report["sent"], report["failed"], report["subscribers"]), (2, 0, 2))
        self.assertEqual([m["to"] for m in web.sent], [["reader@example.org"], ["second@example.org"]])
        self.assertEqual(web.marked, ["2026-10-10"])
        message = web.sent[0]
        self.assertEqual(message["subject"], "Morning Briefing: Saturday 10 October 2026")
        self.assertIn('href="https://rochdaledaily.co.uk/articles/a-story.html"', message["html"])
        self.assertNotIn("published every day at 9am", message["html"])

    def test_every_email_can_be_left_with_one_click(self):
        _, web = run()
        message = web.sent[0]
        link = "https://rochdaledaily.co.uk/api/newsletter?unsubscribe=" + hashlib.sha256(b"reader@example.org").hexdigest()
        self.assertIn(link, message["html"])
        self.assertIn(link, message["text"])
        self.assertEqual(message["headers"]["List-Unsubscribe"], f"<{link}>")
        self.assertEqual(message["headers"]["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click")

    def test_a_second_run_the_same_day_sends_nothing(self):
        report, web = run(Web(last_sent="2026-10-10"))
        self.assertEqual(web.sent, [])
        self.assertIn("already been sent", report["status"])

    def test_a_rerun_after_a_crash_cannot_deliver_a_second_copy(self):
        _, first = run()
        _, second = run()
        self.assertEqual([m["_key"] for m in first.sent], [m["_key"] for m in second.sent])

    def test_one_bad_address_does_not_stop_the_rest_and_is_not_printed(self):
        report, web = run(Web(fail_for="reader@example.org"))
        self.assertEqual((report["sent"], report["failed"]), (1, 1))
        self.assertNotIn("reader@example.org", report["status"])
        self.assertTrue(report.get("error"))


class NotSending(unittest.TestCase):
    def test_without_the_secrets_nothing_is_contacted_and_the_missing_one_is_named(self):
        report, web = run(env={"RESEND_API_KEY": ""})
        self.assertEqual(web.calls, [])
        self.assertIn("RESEND_API_KEY", report["status"])
        self.assertIn("NEWSLETTER_ADMIN_TOKEN", report["status"])
        self.assertFalse(report.get("error"), "an unconfigured newsletter must not fail the workflow")

    def test_no_briefing_today_means_no_email(self):
        yesterday = dict(BRIEFING, first_published_at="2026-10-09T08:10:00Z")
        report, web = run(articles=[yesterday])
        self.assertEqual(web.calls, [])
        self.assertIn("no Morning Briefing", report["status"])

    def test_a_morning_newsletter_is_not_sent_in_the_afternoon(self):
        report, web = run(now=datetime(2026, 10, 10, 15, 0, tzinfo=timezone.utc))
        self.assertEqual(web.calls, [])
        self.assertIn("outside the sending window", report["status"])

    def test_dry_run_counts_but_sends_nothing(self):
        report, web = run(env=dict(ENV, NEWSLETTER_DRY_RUN="true"))
        self.assertEqual(web.sent, [])
        self.assertIn("would send", report["status"])
        self.assertEqual(web.marked, [])

    def test_a_refused_admin_token_is_an_error_not_a_silent_skip(self):
        report, web = run(Web(list_status=401))
        self.assertEqual(web.sent, [])
        self.assertTrue(report.get("error"))


class UnsubscribeEndpoint(unittest.TestCase):
    def test_the_link_deletes_the_reader_without_a_token_and_admin_routes_stay_locked(self):
        script = r"""
const path = process.argv[process.argv.length - 1];
import(path + '/functions/api/newsletter.js').then(async (fn) => {
  const store = new Map();
  const kv = { get: async (k, o) => { const v = store.get(k); if (v == null) return null; return o && o.type === 'json' ? JSON.parse(v) : v; },
               put: async (k, v) => { store.set(k, v); }, delete: async (k) => { store.delete(k); } };
  const env = { EVENTS_KV: kv, EVENTS_ADMIN_TOKEN: 'secret', EVENTS_IP_SALT: 's' };
  const post = (url, body, headers) => fn.onRequestPost({ env, request: new Request(url, { method: 'POST', headers: Object.assign({ 'Content-Type': 'application/json' }, headers || {}), body: JSON.stringify(body || {}) }) });
  const get = (url, headers) => fn.onRequestGet({ env, request: new Request(url, { headers: headers || {} }) });
  const base = 'https://example.test/api/newsletter';
  await post(base, { email: 'reader@example.org', consent: true });
  await post(base, { email: 'second@example.org', consent: true });
  const index = JSON.parse(store.get('newsletter:index'));
  const hash = index[index.length - 1];
  const page = await get(base + '?unsubscribe=' + hash);
  const html = await page.text();
  const after = JSON.parse(store.get('newsletter:index'));
  const oneClick = await post(base + '?unsubscribe=' + after[0]);
  const bad = await get(base + '?unsubscribe=nothex');
  const noToken = await post(base + '?mark_sent=2026-10-10');
  const marked = await post(base + '?mark_sent=2026-10-10', {}, { 'x-admin-token': 'secret' });
  const last = await (await get(base + '?last_sent=1', { 'x-admin-token': 'secret' })).json();
  console.log(JSON.stringify({ pageStatus: page.status, type: page.headers.get('content-type'), said: html.includes('You have been unsubscribed'),
    left: after.length, stillStored: store.has('newsletter:sub:' + hash), oneClick: oneClick.status,
    remaining: JSON.parse(store.get('newsletter:index')).length, bad: bad.status, noToken: noToken.status, marked: marked.status, last: last.last_sent }));
}).catch((e) => { console.error(e); process.exit(1); });
"""
        done = subprocess.run(["node", "--input-type=module", "-e", script, "--", str(REPO)], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        result = json.loads(done.stdout.strip().splitlines()[-1])
        self.assertEqual(result, {"pageStatus": 200, "type": "text/html; charset=utf-8", "said": True, "left": 1,
                                  "stillStored": False, "oneClick": 200, "remaining": 0, "bad": 401,
                                  "noToken": 401, "marked": 200, "last": "2026-10-10"})


if __name__ == "__main__":
    unittest.main()
