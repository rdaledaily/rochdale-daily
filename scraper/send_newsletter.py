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


# --- The email itself --------------------------------------------------------
# Built for email clients, not browsers: one 600px table, every style inline,
# no web fonts, no CSS classes, images with width set and alt text, so it reads
# the same in Gmail, Outlook and Apple Mail and on a phone. Each story links
# back with utm tags so Google Analytics can count what the newsletter brings
# back (the measure that matters: Medill found visit frequency predicts a
# loyal reader far better than anything else).
PAPER = "#f6f5f1"
INK = "#2b2824"
MUTED = "#6b675f"
RULE = "#dcdad4"
ACCENT = "#8c3a25"
SERIF = "Georgia,'Times New Roman',serif"
SANS = "Arial,Helvetica,sans-serif"
UTM = "utm_source=newsletter&utm_medium=email&utm_campaign=morning-briefing"
LOGO = f"{SITE}/assets/img/logo.png"
FIXTURES = ROOT / "afc_fixtures.json"


def _link(slug: str) -> str:
    return f"{SITE}/articles/{slug}?{UTM}"


def _image(url: str) -> str:
    url = str(url or "").strip()
    if not url:
        return ""
    return url if url.startswith("https://") else f"{SITE}/{url.lstrip('/')}"


def _plain(html_text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html_text or "")).strip()


def briefing_parts(briefing: dict[str, Any], articles: list[dict[str, Any]]) -> dict[str, Any]:
    """The stories, intro line and weather from the published briefing, with
    each story's own photo, section and place looked up from the feed."""
    body = str(briefing.get("content_html") or "")
    by_slug = {str(a.get("slug")): a for a in articles if isinstance(a, dict) and a.get("slug")}
    stories: list[dict[str, str]] = []
    seen: set[str] = set()
    for href, inner in re.findall(r'<a href="(?:https://rochdaledaily\.co\.uk)?/articles/([a-z0-9-]+)(?:\.html)?"[^>]*>(.*?)</a>', body, re.S):
        if href in seen:
            continue
        seen.add(href)
        record = by_slug.get(href, {})
        title = _plain(str(record.get("title") or inner))
        if not title:
            continue
        stories.append({
            "slug": href,
            "title": title,
            "summary": _plain(str(record.get("excerpt") or "")),
            # Real photographs only: a generated headline card is a grey box
            # with a place name on it, which reads as a broken image in email.
            "image": "" if ("generated-card" in str(record.get("image_url") or "")
                            or str(record.get("image_status") or "") == "place-generated-card")
                     else _image(record.get("image_url") or record.get("img")),
            "alt": _plain(str(record.get("image_alt") or title)),
            "section": str(record.get("kicker") or record.get("category") or "News").replace("_", " ").title(),
            "area": str(record.get("area") or "").replace("_", " ").title(),
        })
    intro = ""
    first = re.search(r"<p>(.*?)</p>", body, re.S)
    if first and "Weather" not in first.group(1):
        intro = _plain(first.group(1))
    weather = ""
    match = re.search(r"<strong>Weather:</strong>\s*(.*?)</p>", body, re.S)
    if match:
        weather = _plain(match.group(1))
    return {"stories": stories, "intro": intro, "weather": weather}


def next_afc_fixture(now: datetime, path: Path = FIXTURES) -> str:
    """'Sat 31 Oct, 12:30: Port Vale v Rochdale (League Two)' within a week, verified only."""
    try:
        rows = json.loads(path.read_text(encoding="utf-8")).get("fixtures") or []
    except (OSError, ValueError, AttributeError):
        return ""
    today = now.astimezone(LONDON).date()
    for row in sorted(rows, key=lambda r: str(r.get("date"))):
        if row.get("verified") is not True or not str(row.get("source_url") or "").startswith("https://") or row.get("result"):
            continue
        try:
            day = datetime.strptime(str(row.get("date")), "%Y-%m-%d").date()
        except ValueError:
            continue
        if not (today <= day <= today.fromordinal(today.toordinal() + 7)):
            continue
        home = str(row.get("venue")).lower() == "home"
        vs = f"Rochdale v {row.get('opponent')}" if home else f"{row.get('opponent')} v Rochdale"
        when = day.strftime("%a %-d %b") + (f", {row.get('kickoff')}" if row.get("kickoff") else "")
        extra = " · ".join(x for x in (str(row.get("competition") or ""), str(row.get("tv") or "")) if x)
        return f"{when}: {vs}" + (f" ({extra})" if extra else "")
    return ""


def build_html(briefing: dict[str, Any], articles: list[dict[str, Any]] | None = None,
               now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    parts = briefing_parts(briefing, articles or [])
    title = str(briefing.get("title") or "Morning Briefing")
    stories = parts["stories"]
    date_line = now.astimezone(LONDON).strftime("%A %-d %B %Y")
    preheader = stories[0]["title"] if stories else "Today's news from the Rochdale borough"
    e = escape

    def label(text: str) -> str:
        return (f'<p style="margin:0 0 6px;font-family:{SANS};font-size:11px;font-weight:bold;'
                f'letter-spacing:1.5px;text-transform:uppercase;color:{ACCENT}">{e(text)}</p>')

    rows: list[str] = []
    if stories:
        lead = stories[0]
        img = (f'<a href="{e(_link(lead["slug"]))}"><img src="{e(lead["image"])}" width="552" alt="{e(lead["alt"])}" '
               f'style="display:block;width:100%;max-width:552px;height:auto;border:0;margin:0 0 14px"></a>') if lead["image"] else ""
        place = f' · {e(lead["area"])}' if lead["area"] else ""
        rows.append(
            f'<tr><td style="padding:24px 24px 8px">{img}{label(lead["section"] + place)}'
            f'<h2 style="margin:0 0 8px;font-family:{SERIF};font-size:26px;line-height:1.2;font-weight:bold">'
            f'<a href="{e(_link(lead["slug"]))}" style="color:{INK};text-decoration:none">{e(lead["title"])}</a></h2>'
            + (f'<p style="margin:0 0 12px;font-family:{SERIF};font-size:17px;line-height:1.5;color:{INK}">{e(lead["summary"])}</p>' if lead["summary"] else "")
            + f'<p style="margin:0 0 8px;font-family:{SANS};font-size:14px;font-weight:bold">'
            f'<a href="{e(_link(lead["slug"]))}" style="color:{ACCENT};text-decoration:none">Read the full story &rarr;</a></p></td></tr>'
        )
    for story in stories[1:]:
        thumb = (f'<td width="96" valign="top" style="padding:0 14px 0 0"><a href="{e(_link(story["slug"]))}">'
                 f'<img src="{e(story["image"])}" width="96" height="72" alt="" style="display:block;width:96px;height:72px;object-fit:cover;border:0"></a></td>'
                 ) if story["image"] else ""
        place = f' · {e(story["area"])}' if story["area"] else ""
        rows.append(
            f'<tr><td style="padding:16px 24px 0"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="border-top:1px solid {RULE}"><tr><td style="padding-top:16px"><table role="presentation" cellpadding="0" cellspacing="0"><tr>{thumb}'
            f'<td valign="top">{label(story["section"] + place)}'
            f'<h3 style="margin:0 0 6px;font-family:{SERIF};font-size:19px;line-height:1.25;font-weight:bold">'
            f'<a href="{e(_link(story["slug"]))}" style="color:{INK};text-decoration:none">{e(story["title"])}</a></h3>'
            + (f'<p style="margin:0;font-family:{SANS};font-size:14px;line-height:1.5;color:{MUTED}">{e(story["summary"])}</p>' if story["summary"] else "")
            + '</td></tr></table></td></tr></table></td></tr>'
        )

    extras = []
    if parts["weather"]:
        extras.append(("Weather", parts["weather"]))
    fixture = next_afc_fixture(now)
    if fixture:
        extras.append(("Rochdale AFC", fixture))
    if extras:
        cells = "".join(
            f'<tr><td style="padding:10px 0;border-top:1px solid {RULE};font-family:{SANS};font-size:14px;color:{INK}">'
            f'<strong style="color:{ACCENT}">{e(name)}:</strong> {e(text)}</td></tr>' for name, text in extras)
        rows.append(f'<tr><td style="padding:24px 24px 0"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
                    f'style="background:{PAPER}"><tr><td style="padding:4px 16px">'
                    f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{cells}</table></td></tr></table></td></tr>')

    briefing_url = _link(str(briefing.get("slug") or ""))
    rows.append(
        f'<tr><td style="padding:24px 24px 28px;text-align:center">'
        f'<a href="{e(briefing_url)}" style="display:inline-block;background:{INK};color:#ffffff;font-family:{SANS};font-size:15px;'
        f'font-weight:bold;text-decoration:none;padding:14px 22px">Read today&rsquo;s paper</a>'
        f'<p style="margin:16px 0 0;font-family:{SANS};font-size:14px;color:{MUTED}">Seen something in your street? '
        f'<a href="mailto:news@rochdaledaily.co.uk?subject=News%20tip" style="color:{ACCENT}">Tell the newsdesk</a></p></td></tr>'
    )

    intro = (f'<p style="margin:12px 0 0;font-family:{SERIF};font-size:16px;line-height:1.5;color:{INK}">{e(parts["intro"])}</p>'
             if parts["intro"] else "")
    return (
        '<!doctype html><html lang="en-GB"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light only"><meta name="supported-color-schemes" content="light">'
        f'<title>{e(title)}</title></head>'
        f'<body style="margin:0;padding:0;background:{PAPER}">'
        f'<div style="display:none;max-height:0;overflow:hidden;opacity:0">{e(preheader)}&#8199;&#65279;&#847;&#8199;&#65279;&#847;</div>'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{PAPER}"><tr><td align="center" style="padding:16px 8px">'
        f'<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="width:100%;max-width:600px;background:#ffffff;border-top:4px solid {INK}">'
        f'<tr><td style="padding:22px 24px 16px;text-align:center;border-bottom:1px solid {RULE}">'
        f'<a href="{SITE}/?{UTM}"><img src="{LOGO}" width="180" alt="Rochdale Daily" style="display:inline-block;width:180px;height:auto;border:0"></a>'
        f'<p style="margin:10px 0 0;font-family:{SANS};font-size:11px;letter-spacing:1.5px;text-transform:uppercase;color:{MUTED}">'
        f'The Morning Briefing &middot; {e(date_line)}</p>{intro}</td></tr>'
        + "".join(rows) +
        f'<tr><td style="padding:20px 24px;background:{INK};text-align:center;font-family:{SANS};font-size:12px;line-height:1.6;color:#d8d4cc">'
        f'<a href="https://www.facebook.com/1240511409139789" style="color:#ffffff;font-weight:bold">Follow us on Facebook</a> &middot; '
        f'<a href="{SITE}/write-a-column?{UTM}" style="color:#ffffff;font-weight:bold">Write for us</a> &middot; '
        f'<a href="{SITE}/rochdale-afc?{UTM}" style="color:#ffffff;font-weight:bold">Dale matchday</a><br><br>'
        'You are receiving this because you signed up for the Rochdale Daily newsletter at rochdaledaily.co.uk.<br>'
        f'<a href="{{{{ unsubscribe }}}}" style="color:#ffffff">Unsubscribe</a> at any time &middot; '
        f'<a href="{SITE}/privacy" style="color:#ffffff">Privacy</a><br>Rochdale Daily, independent local news for the Rochdale borough.'
        '</td></tr></table></td></tr></table></body></html>'
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
        "htmlContent": build_html(briefing, articles or [], now),
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
