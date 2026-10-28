#!/usr/bin/env python3
"""Send "The borough in your inbox": the day's Morning Briefing as a Brevo campaign.

Why this exists
---------------
Newsletter sign-ups are stored by functions/api/newsletter.js and copied to a
Brevo contact list, but that file says it "never sends a campaign", and
nothing else did. Readers who signed up received nothing. This is the sender.

What it sends
-------------
Once a day, between 09:00 and 13:00 London, the Morning Briefing the paper has
already published, to the Brevo list sign-ups join. No model call and nothing
written specially for email, so the newsletter cannot say anything the site
does not. Brevo handles delivery, the unsubscribe link and suppressions, so
anyone who has unsubscribed or bounced is never mailed again.

What it needs (GitHub repository secrets / variables)
-----------------------------------------------------
  BREVO_API_KEY         secret: the same Brevo key the site uses
  BREVO_LIST_ID         secret or variable: the list sign-ups join
  NEWSLETTER_SENDER     variable: a sender address verified in Brevo
                        (default news@rochdaledaily.co.uk, verified and
                        DKIM-authenticated in Brevo on 28 Oct 2026)
Optional: NEWSLETTER_SENDER_NAME, NEWSLETTER_DRY_RUN=true.

Until the key and list exist it sends nothing and says which is missing.

Safe to run many times a day: each day's campaign has a fixed name, and if a
campaign with that name already exists nothing new is created or sent.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html import escape
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
BREVO = "https://api.brevo.com/v3"
DEFAULT_SENDER = "news@rochdaledaily.co.uk"
DEFAULT_SENDER_NAME = "Rochdale Daily"
# A morning newsletter goes out in the morning. If the briefing is published
# late, or Brevo is down past lunchtime, that day is skipped.
SEND_FROM_HOUR = 9
SEND_UNTIL_HOUR = 13

Request = Callable[..., tuple[int, str]]


def todays_briefing(articles: list[dict[str, Any]], today: datetime) -> dict[str, Any] | None:
    """The Morning Briefing first published today (London date), or None."""
    wanted = today.astimezone(LONDON).strftime("%Y-%m-%d")
    for article in articles:
        if not isinstance(article, dict):
            continue
        # briefing_slot was dropped by the manual-article loader until
        # 20 Oct 2026, so the briefing is also recognised by its address.
        if article.get("briefing_slot") != "morning" and not str(article.get("slug") or "").startswith("morning-briefing-"):
            continue
        stamp = str(article.get("first_published_at") or article.get("published_at") or "")
        try:
            moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        if moment.astimezone(LONDON).strftime("%Y-%m-%d") == wanted:
            return article
    return None


def campaign_name(day: str) -> str:
    return f"Rochdale Daily briefing {day}"


def absolutise(html: str) -> str:
    """Email clients have no site to resolve /articles/... against."""
    return re.sub(r'(href|src)="/(?!/)', rf'\1="{SITE}/', html or "")


def build_html(briefing: dict[str, Any]) -> str:
    title = str(briefing.get("title") or "Morning Briefing")
    body = absolutise(str(briefing.get("content_html") or ""))
    # The site's own footer line talks about the website; the email has its own.
    body = re.sub(r'<p class="brief-foot">.*?</p>', "", body, flags=re.S)
    page = f"{SITE}/articles/{briefing.get('slug')}.html"
    return (
        '<!doctype html><html><body style="margin:0;background:#f6f5f1">'
        '<div style="max-width:640px;margin:0 auto;padding:24px;font-family:Georgia,serif;color:#2b2824;line-height:1.5;background:#ffffff">'
        '<p style="font-family:Arial,sans-serif;font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:#6b5a46">'
        'Rochdale Daily &middot; The borough in your inbox</p>'
        f'<h1 style="font-size:26px;margin:0 0 16px">{escape(title)}</h1>'
        f'{body}'
        f'<p><a href="{page}">Read this briefing on rochdaledaily.co.uk</a></p>'
        '<hr style="border:0;border-top:1px solid #dcdad4;margin:28px 0 14px">'
        '<p style="font-family:Arial,sans-serif;font-size:12px;color:#5b5952">'
        'You are receiving this because you signed up for the Rochdale Daily newsletter at rochdaledaily.co.uk. '
        '<a href="{{ unsubscribe }}">Unsubscribe</a> at any time. Got a story? '
        f'<a href="{SITE}/contact.html">Tell the newsdesk</a>.</p>'
        '</div></body></html>'
    )


def http(url: str, *, method: str = "GET", headers: dict[str, str] | None = None, body: bytes | None = None) -> tuple[int, str]:
    request = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")


def brevo(request: Request, key: str, path: str, method: str = "GET", payload: Any = None) -> tuple[int, Any]:
    headers = {"api-key": key, "Accept": "application/json"}
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    status, text = request(BREVO + path, method=method, headers=headers, body=body)
    try:
        data = json.loads(text) if text.strip() else {}
    except ValueError:
        data = {"raw": text[:200]}
    return status, data


def already_created(request: Request, key: str, name: str) -> bool | None:
    """True if today's campaign exists, False if not, None if Brevo would not say."""
    status, data = brevo(request, key, "/emailCampaigns?limit=50&offset=0&sort=desc")
    if status != 200:
        return None
    return any(str(row.get("name")) == name for row in data.get("campaigns") or [])


def run(env: dict[str, str], now: datetime, request: Request = http,
        articles: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    day = now.astimezone(LONDON).strftime("%Y-%m-%d")
    report: dict[str, Any] = {"date": day, "sent": False, "status": ""}
    hour = now.astimezone(LONDON).hour
    if not (SEND_FROM_HOUR <= hour < SEND_UNTIL_HOUR) and env.get("NEWSLETTER_FORCE", "").lower() != "true":
        report["status"] = f"outside the sending window ({SEND_FROM_HOUR:02d}:00 to {SEND_UNTIL_HOUR:02d}:00 London); nothing sent"
        return report

    if articles is None:
        try:
            articles = json.loads(ARTICLES.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            articles = []
    briefing = todays_briefing(articles or [], now)
    if briefing is None:
        report["status"] = "no Morning Briefing has been published today; nothing to send"
        return report
    report["briefing"] = briefing.get("slug")

    key = env.get("BREVO_API_KEY", "").strip()
    list_id = env.get("BREVO_LIST_ID", "").strip()
    missing = [n for n, v in (("BREVO_API_KEY", key), ("BREVO_LIST_ID", list_id)) if not v]
    if missing:
        report["status"] = "not configured: missing " + ", ".join(missing) + " (GitHub repository secrets); nothing sent"
        return report
    if not list_id.isdigit():
        report["status"] = "BREVO_LIST_ID must be a number; nothing sent"
        report["error"] = True
        return report

    name = campaign_name(day)
    exists = already_created(request, key, name)
    if exists is None:
        report["status"] = "Brevo would not list campaigns (check BREVO_API_KEY); nothing sent"
        report["error"] = True
        return report
    if exists:
        report["status"] = "today's newsletter has already been created"
        return report

    if env.get("NEWSLETTER_DRY_RUN", "").lower() == "true":
        report["status"] = f"dry run: would send {briefing.get('title')!r} to Brevo list {list_id}"
        return report

    payload = {
        "name": name,
        "subject": str(briefing.get("title") or "Morning Briefing"),
        "sender": {"name": env.get("NEWSLETTER_SENDER_NAME", "").strip() or DEFAULT_SENDER_NAME,
                   "email": env.get("NEWSLETTER_SENDER", "").strip() or DEFAULT_SENDER},
        "htmlContent": build_html(briefing),
        "recipients": {"listIds": [int(list_id)]},
    }
    status, data = brevo(request, key, "/emailCampaigns", "POST", payload)
    campaign = data.get("id") if isinstance(data, dict) else None
    if status != 201 or not campaign:
        report["status"] = f"Brevo refused the campaign (HTTP {status}): {str(data.get('message') or data)[:160]}"
        report["error"] = True
        return report
    status, data = brevo(request, key, f"/emailCampaigns/{campaign}/sendNow", "POST")
    if status != 204:
        report["status"] = f"campaign {campaign} created but Brevo refused to send it (HTTP {status}): {str(data.get('message') or data)[:160]}"
        report["error"] = True
        return report
    report["sent"] = True
    report["campaign"] = campaign
    report["status"] = f"sent campaign {campaign} ({briefing.get('title')}) to Brevo list {list_id}"
    return report


def main() -> int:
    report = run(dict(os.environ), datetime.now(timezone.utc))
    print("Newsletter: " + report["status"])
    return 1 if report.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
