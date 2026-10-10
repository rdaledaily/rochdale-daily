#!/usr/bin/env python3
"""Send "The borough in your inbox": the day's Morning Briefing, by email.

Why this exists
---------------
The homepage has taken newsletter sign-ups since the summer and stored them
(functions/api/newsletter.js), but nothing was ever sent: that file says so in
its own header ("Until then nothing is sent"). Readers who signed up received
nothing at all. This script is the missing half.

What it sends
-------------
One email a day to every subscriber: the Morning Briefing that the paper has
already published, with links back to each story. No model call and nothing
written specially for email, so the newsletter can never say something the
site does not.

What it needs (GitHub repository secrets)
-----------------------------------------
  RESEND_API_KEY          from a Resend account with rochdaledaily.co.uk verified
  NEWSLETTER_ADMIN_TOKEN  the same value as the site's EVENTS_ADMIN_TOKEN, so the
                          subscriber list can be read from /api/newsletter
Optional: NEWSLETTER_FROM (default below), NEWSLETTER_REPLY_TO, NEWSLETTER_DRY_RUN=true.

Until both secrets exist it sends nothing and says exactly which one is
missing. It never guesses a recipient and never falls back to another sender.

Safe to run twice: every message carries an idempotency key made of the date
and the subscriber, so a re-run on the same day cannot deliver a second copy.

Every email carries an unsubscribe link and the one-click unsubscribe headers
that Gmail and Yahoo require of bulk senders. The link is
/api/newsletter?unsubscribe=<sha256 of the address>, handled by the same
function that stores the sign-up.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html import escape, unescape
from pathlib import Path
from typing import Any, Callable

try:
    from zoneinfo import ZoneInfo
    LONDON = ZoneInfo("Europe/London")
except Exception:  # pragma: no cover
    LONDON = timezone.utc

ROOT = Path(__file__).resolve().parent.parent
ARTICLES = ROOT / "articles.json"
SITE = "https://rochdaledaily.co.uk"
SUBSCRIBERS_URL = f"{SITE}/api/newsletter?export=csv"
RESEND_URL = "https://api.resend.com/emails"
DEFAULT_FROM = "Rochdale Daily <newsletter@rochdaledaily.co.uk>"
USER_AGENT = "RochdaleDailyNewsletter/1.0 (+https://rochdaledaily.co.uk)"
# A morning newsletter goes out in the morning. If the briefing is published
# late, or a provider outage lasts past lunchtime, that day is skipped.
SEND_FROM_HOUR = 9
SEND_UNTIL_HOUR = 13
EMAIL_RE = re.compile(r"^[^\s@,]+@[^\s@,]+\.[^\s@,]{2,}$")


def todays_briefing(articles: list[dict[str, Any]], today: datetime) -> dict[str, Any] | None:
    """The Morning Briefing published today (London date), or None."""
    wanted = today.astimezone(LONDON).strftime("%Y-%m-%d")
    for article in articles:
        if not isinstance(article, dict) or article.get("briefing_slot") != "morning":
            continue
        stamp = str(article.get("first_published_at") or article.get("published_at") or "")
        try:
            moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        if moment.astimezone(LONDON).strftime("%Y-%m-%d") == wanted:
            return article
    return None


def absolutise(html: str) -> str:
    """Email clients have no site to resolve /articles/... against."""
    return re.sub(r'(href|src)="/(?!/)', rf'\1="{SITE}/', html or "")


def unsubscribe_url(email: str) -> str:
    return f"{SITE}/api/newsletter?unsubscribe={hashlib.sha256(email.encode('utf-8')).hexdigest()}"


def plain_text(html: str) -> str:
    text = re.sub(r"<li[^>]*>", "\n- ", html or "")
    text = re.sub(r"</(p|h1|h2|h3|ul|li)>|<br\s*/?>", "\n", text)
    text = re.sub(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', r"\2 (\1)", text, flags=re.S)
    text = unescape(re.sub(r"<[^>]+>", "", text))
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()


def build_email(briefing: dict[str, Any], email: str) -> dict[str, str]:
    title = str(briefing.get("title") or "Morning Briefing")
    body = absolutise(str(briefing.get("content_html") or ""))
    # The site's own footer line talks about the website; the email has its own.
    body = re.sub(r'<p class="brief-foot">.*?</p>', "", body, flags=re.S)
    page = f"{SITE}/articles/{briefing.get('slug')}.html"
    leave = unsubscribe_url(email)
    html = (
        '<div style="max-width:640px;margin:0 auto;font-family:Georgia,serif;color:#2b2824;line-height:1.5">'
        f'<p style="font-family:Arial,sans-serif;font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:#6b5a46">'
        f'Rochdale Daily &middot; The borough in your inbox</p>'
        f'<h1 style="font-size:26px;margin:0 0 16px">{escape(title)}</h1>'
        f'{body}'
        f'<p><a href="{page}">Read this briefing on rochdaledaily.co.uk</a></p>'
        '<hr style="border:0;border-top:1px solid #dcdad4;margin:28px 0 14px">'
        '<p style="font-family:Arial,sans-serif;font-size:12px;color:#5b5952">'
        'You are receiving this because you signed up for the Rochdale Daily newsletter at rochdaledaily.co.uk. '
        f'<a href="{leave}">Unsubscribe</a> at any time. Got a story? Reply to this email or '
        f'<a href="{SITE}/contact.html">tell the newsdesk</a>.</p></div>'
    )
    text = (
        f"ROCHDALE DAILY - The borough in your inbox\n\n{title}\n\n{plain_text(body)}\n\n"
        f"Read this briefing on the site: {page}\n\n--\n"
        "You are receiving this because you signed up for the Rochdale Daily newsletter at rochdaledaily.co.uk.\n"
        f"Unsubscribe: {leave}\n"
    )
    return {"subject": title, "html": html, "text": text}


def http(url: str, *, method: str = "GET", headers: dict[str, str] | None = None, body: bytes | None = None) -> tuple[int, str]:
    request = urllib.request.Request(url, data=body, method=method, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")


def fetch_subscribers(token: str, request: Callable[..., tuple[int, str]] = http) -> list[str]:
    status, body = request(SUBSCRIBERS_URL, headers={"x-admin-token": token})
    if status != 200:
        raise RuntimeError(f"subscriber list could not be read (HTTP {status}); check NEWSLETTER_ADMIN_TOKEN")
    emails: list[str] = []
    seen: set[str] = set()
    for row in csv.DictReader(io.StringIO(body)):
        email = str(row.get("email") or "").strip().lower()
        if EMAIL_RE.match(email) and email not in seen:
            seen.add(email)
            emails.append(email)
    return emails


def send_one(api_key: str, sender: str, reply_to: str, email: str, message: dict[str, str], day: str,
             request: Callable[..., tuple[int, str]] = http) -> tuple[bool, str]:
    leave = unsubscribe_url(email)
    payload: dict[str, Any] = {
        "from": sender,
        "to": [email],
        "subject": message["subject"],
        "html": message["html"],
        "text": message["text"],
        "headers": {
            "List-Unsubscribe": f"<{leave}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        },
    }
    if reply_to:
        payload["reply_to"] = reply_to
    key = "rd-newsletter-" + day + "-" + hashlib.sha256(email.encode("utf-8")).hexdigest()[:24]
    status, body = request(RESEND_URL, method="POST", headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Idempotency-Key": key,
    }, body=json.dumps(payload).encode("utf-8"))
    return 200 <= status < 300, f"HTTP {status}: {body[:160]}"


def run(env: dict[str, str], now: datetime, request: Callable[..., tuple[int, str]] = http,
        articles: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Send today's briefing. Returns a report; raises nothing a workflow must catch."""
    report: dict[str, Any] = {"date": now.astimezone(LONDON).strftime("%Y-%m-%d"), "sent": 0, "failed": 0, "status": ""}
    if articles is None:
        try:
            articles = json.loads(ARTICLES.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            articles = []
    hour = now.astimezone(LONDON).hour
    if not (SEND_FROM_HOUR <= hour < SEND_UNTIL_HOUR) and env.get("NEWSLETTER_FORCE", "").lower() != "true":
        report["status"] = f"outside the sending window ({SEND_FROM_HOUR:02d}:00 to {SEND_UNTIL_HOUR:02d}:00 London); nothing sent"
        return report
    briefing = todays_briefing(articles or [], now)
    if briefing is None:
        report["status"] = "no Morning Briefing has been published today; nothing to send"
        return report
    report["briefing"] = briefing.get("slug")

    missing = [name for name in ("RESEND_API_KEY", "NEWSLETTER_ADMIN_TOKEN") if not env.get(name, "").strip()]
    if missing:
        report["status"] = "not configured: missing repository secret(s) " + ", ".join(missing) + "; nothing sent"
        return report

    token = env["NEWSLETTER_ADMIN_TOKEN"].strip()
    status, body = request(f"{SITE}/api/newsletter?last_sent=1", headers={"x-admin-token": token})
    try:
        last_sent = str(json.loads(body).get("last_sent") or "") if status == 200 else ""
    except ValueError:
        last_sent = ""
    if status != 200:
        report["status"] = f"could not read the last-sent date (HTTP {status}); check NEWSLETTER_ADMIN_TOKEN; nothing sent"
        report["error"] = True
        return report
    if last_sent == report["date"]:
        report["status"] = "today's newsletter has already been sent"
        return report

    try:
        subscribers = fetch_subscribers(token, request)
    except RuntimeError as error:
        report["status"] = str(error)
        report["error"] = True
        return report
    report["subscribers"] = len(subscribers)
    if not subscribers:
        report["status"] = "nobody has signed up yet; nothing sent"
        return report

    if env.get("NEWSLETTER_DRY_RUN", "").lower() == "true":
        report["status"] = f"dry run: would send {briefing.get('title')!r} to {len(subscribers)} subscriber(s)"
        return report

    sender = env.get("NEWSLETTER_FROM", "").strip() or DEFAULT_FROM
    reply_to = env.get("NEWSLETTER_REPLY_TO", "").strip()
    first_error = ""
    for email in subscribers:
        ok, detail = send_one(env["RESEND_API_KEY"].strip(), sender, reply_to, email,
                              build_email(briefing, email), report["date"], request)
        if ok:
            report["sent"] += 1
        else:
            report["failed"] += 1
            first_error = first_error or detail
    report["status"] = f"sent to {report['sent']} of {len(subscribers)} subscriber(s)"
    if report["sent"]:
        # Recorded even when a few addresses failed: sending the whole list
        # again tomorrow morning is right, sending it again in an hour is not.
        request(f"{SITE}/api/newsletter?mark_sent={report['date']}", method="POST",
                headers={"x-admin-token": token, "Content-Type": "application/json"}, body=b"{}")
    if report["failed"]:
        # Never print an address: workflow logs on a public repository are public.
        report["status"] += f"; {report['failed']} failed, first error: {first_error}"
        report["error"] = True
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    report = run(dict(os.environ), datetime.now(timezone.utc))
    print("Newsletter: " + report["status"])
    return 1 if report.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
