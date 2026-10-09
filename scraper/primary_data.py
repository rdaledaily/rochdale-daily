#!/usr/bin/env python3
"""Primary-data sources on a rota: official records nobody else turns into news.

Why this exists
---------------
Measured 9 October 2026: a newsroom run collected 140 raw items, which merged
into 38 stories, almost all already covered; between 0 and 3 were new. The
paper is limited by supply, not by its gates. On the same day the evidence
guard began (claim_evidence.py): an automated story is published only when its
source is an ordinary HTML page on an approved official host and every claim
can be quoted from that page. Roughly three quarters of the old supply (other
outlets) can no longer publish on its own.

So new supply has to be official records, each with its own page on an approved
host. 75 candidate sources were surveyed on 9 October 2026. Most failed a hard
requirement (JavaScript-only listings, spreadsheets, logins, robots.txt, or a
host that is not approved). These passed and are built here:

  council_roadworks   rochdale.gov.uk roadworks directory     about 4-7 a week
  gazette_insolvency  The Gazette, corporate insolvency       about 2-3 a week
  written_answers     Parliament written answers naming the borough   about 1 a week when sitting
  gmca_decisions      GMCA decisions naming a borough place   under 1 a week
  ons_housing         ONS house price and rent page           1 a month

The rota
--------
Each source has an interval (how often its listing is fetched) and a daily cap
(how many stories it may offer in one London day). Both are held in a state
file committed with the newsroom snapshot, so a source is not re-read by every
15-minute run and a backlog is released as a steady drip, not a flood. An item
is marked seen only when it is offered, so anything over the cap waits for the
next day.

This module only NOTICES that a record exists. Each record's source_url is the
official page; the pipeline fetches that page itself, grounds the rewrite on it
and fact-checks against it, exactly as it does for an Ofsted report.

No third-party dependencies. Network access is injected as `get`, so the tests
never touch the internet.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from typing import Any, Callable

try:
    from zoneinfo import ZoneInfo
    LONDON = ZoneInfo("Europe/London")
except Exception:  # pragma: no cover
    LONDON = timezone.utc

TIMEOUT = 15
SEEN_LIMIT = 3000

# source key: (interval in hours, stories offered per London day)
ROTA: dict[str, tuple[int, int]] = {
    "council_roadworks": (6, 4),
    "gazette_insolvency": (12, 2),
    "written_answers": (6, 3),
    "gmca_decisions": (12, 1),
    "ons_housing": (24, 1),
}

# Most specific first; "rochdale" last, because it is also the postal town.
BOROUGH_TOWNS = (
    "littleborough", "smithy bridge", "smallbridge", "castleton", "middleton",
    "alkrington", "firgrove", "heywood", "hopwood", "darnhill", "milnrow",
    "newhey", "wardle", "norden", "bamford", "kirkholt", "balderstone",
    "rochdale",
)
AREA_KEYS = {"smithy bridge": "smithy_bridge"}

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_MONTHS = {name: index for index, name in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"), start=1)}


def plain(value: Any) -> str:
    return _WS_RE.sub(" ", unescape(_TAG_RE.sub(" ", str(value or "")))).strip()


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def detect_town(text: str, default: str = "rochdale") -> str:
    lowered = str(text or "").lower()
    for town in BOROUGH_TOWNS:
        if re.search(rf"\b{re.escape(town)}\b", lowered):
            return AREA_KEYS.get(town, town)
    return default


def names_borough_place(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(re.search(rf"\b{re.escape(town)}\b", lowered) for town in BOROUGH_TOWNS)


# --------------------------------------------------------------------------
# State and rota
# --------------------------------------------------------------------------

def load_state(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"sources": {}}
    if not isinstance(data, dict) or not isinstance(data.get("sources"), dict):
        return {"sources": {}}
    return data


def save_state(path: Path, state: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _slot(state: dict[str, Any], key: str) -> dict[str, Any]:
    slot = state.setdefault("sources", {}).setdefault(key, {})
    slot.setdefault("seen", [])
    return slot


def is_due(state: dict[str, Any], key: str, now: datetime) -> bool:
    last = _slot(state, key).get("last_checked")
    if not last:
        return True
    try:
        checked = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
    except ValueError:
        return True
    return now - checked >= timedelta(hours=ROTA[key][0])


def remaining_today(state: dict[str, Any], key: str, now: datetime) -> int:
    slot = _slot(state, key)
    today = now.astimezone(LONDON).strftime("%Y-%m-%d")
    if slot.get("day") != today:
        slot["day"] = today
        slot["offered_today"] = 0
    return max(0, ROTA[key][1] - int(slot.get("offered_today") or 0))


def mark_seen(state: dict[str, Any], key: str, identity: str) -> None:
    seen = _slot(state, key)["seen"]
    if identity not in seen:
        seen.append(identity)
    if len(seen) > SEEN_LIMIT:
        del seen[: len(seen) - SEEN_LIMIT]


def is_seen(state: dict[str, Any], key: str, identity: str) -> bool:
    return identity in _slot(state, key)["seen"]


def record(key: str, identity: str, *, name: str, url: str, title: str, summary: str,
           published: datetime, area: str, category: str, also_seen: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "source_key": key,
        "identity": identity,
        "also_seen": list(also_seen),
        "source_name": name,
        "source_url": url,
        "source_title": plain(title)[:160],
        "source_summary": plain(summary)[:900],
        "source_published_at": iso(published),
        "area": area,
        "category": category,
    }


# --------------------------------------------------------------------------
# Rochdale Borough Council roadworks directory
# --------------------------------------------------------------------------

ROADWORKS_LISTINGS = (
    "https://www.rochdale.gov.uk/directory/22/search-for-roadworks-in-rochdale-borough/category/140",
    "https://www.rochdale.gov.uk/directory/22/search-for-roadworks-in-rochdale-borough/category/140/2",
)
_ROADWORKS_LINK_RE = re.compile(
    r'<a[^>]+href="(?P<href>/directory-record/(?P<id>\d+)/[^"#?]+)"[^>]*>(?P<body>.*?)</a>', re.I | re.S)
_ROADWORKS_DATE_RE = re.compile(
    r"\b(?:from|on)\s+(?P<day>\d{1,2})\s+(?P<month>[A-Za-z]+)\s+(?P<year>20\d{2})\b", re.I)
# A closure is news shortly before it starts and for a day or two after. Works
# that began weeks ago are not, and works months away are offered nearer the time.
ROADWORKS_DAYS_AHEAD = 14
ROADWORKS_DAYS_BEHIND = 2


def parse_roadworks_listing(html: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    found: set[str] = set()
    for match in _ROADWORKS_LINK_RE.finditer(html or ""):
        record_id = match.group("id")
        title = plain(match.group("body"))
        if record_id in found or not title:
            continue
        found.add(record_id)
        start = None
        dated = _ROADWORKS_DATE_RE.search(title)
        if dated and dated.group("month").lower() in _MONTHS:
            try:
                start = datetime(int(dated.group("year")), _MONTHS[dated.group("month").lower()],
                                 int(dated.group("day")), tzinfo=LONDON)
            except ValueError:
                start = None
        rows.append({"id": record_id, "title": title, "start": start,
                     "url": "https://www.rochdale.gov.uk" + match.group("href")})
    return rows


def council_roadworks(get: Callable[..., Any], state: dict[str, Any], now: datetime, limit: int) -> tuple[list[dict[str, Any]], dict[str, int]]:
    key = "council_roadworks"
    rows: list[dict[str, Any]] = []
    for url in ROADWORKS_LISTINGS:
        response = get(url, timeout=TIMEOUT)
        response.raise_for_status()
        page = parse_roadworks_listing(response.text)
        rows.extend(page)
        if len(page) < 50:      # the directory lists fifty to a page
            break
    today = now.astimezone(LONDON).replace(hour=0, minute=0, second=0, microsecond=0)
    stats = {"listed": len(rows), "already_seen": 0, "started_long_ago": 0, "too_far_ahead": 0, "undated": 0, "in_window": 0}
    wanted: list[dict[str, Any]] = []
    for row in rows:
        if is_seen(state, key, row["id"]):
            stats["already_seen"] += 1
            continue
        if row["start"] is None:
            stats["undated"] += 1
            continue
        days = (row["start"] - today).days
        if days < -ROADWORKS_DAYS_BEHIND:
            stats["started_long_ago"] += 1
            mark_seen(state, key, row["id"])     # never news now; stop re-reading it
            continue
        if days > ROADWORKS_DAYS_AHEAD:
            stats["too_far_ahead"] += 1          # left unseen: offered nearer the time
            continue
        stats["in_window"] += 1
        wanted.append(row)
    wanted.sort(key=lambda row: row["start"])    # soonest first
    out = [record(
        key, row["id"], name="Rochdale Borough Council", url=row["url"], title=row["title"],
        summary=f"Rochdale Borough Council roadworks notice: {row['title']}.",
        published=now, area=detect_town(row["title"]), category="traffic",
    ) for row in wanted[:limit]]
    return out, stats


# --------------------------------------------------------------------------
# The Gazette: corporate insolvency notices for the borough
# --------------------------------------------------------------------------

GAZETTE_FEED = "https://www.thegazette.co.uk/insolvency/notice/data.json"
# Company notices that record something that HAS happened. Deliberately left
# out: petitions to wind up (2450), which are a creditor's application and not
# an outcome, and every notice about a private individual (bankruptcy 25xx,
# deceased estates 29xx). The paper does not report people's personal insolvency.
GAZETTE_NOTICE_CODES = {
    "2441": "Resolutions for Winding-up",
    "2443": "Appointment of Liquidators",
    "2452": "Winding-Up Orders",
}
GAZETTE_LOOKBACK_DAYS = 10


def _company_key(name: str) -> str:
    return "company:" + re.sub(r"[^a-z0-9]+", "", str(name or "").lower())


def gazette_insolvency(get: Callable[..., Any], state: dict[str, Any], now: datetime, limit: int) -> tuple[list[dict[str, Any]], dict[str, int]]:
    key = "gazette_insolvency"
    today = now.astimezone(LONDON)
    response = get(GAZETTE_FEED, params={
        "location-local-authority-1": "rochdale",
        "start-publish-date": (today - timedelta(days=GAZETTE_LOOKBACK_DAYS)).strftime("%Y-%m-%d"),
        "end-publish-date": today.strftime("%Y-%m-%d"),
        "results-page-size": "50",
        "sort-by": "latest-date",
    }, timeout=TIMEOUT)
    response.raise_for_status()
    entries = response.json().get("entry") or []
    if isinstance(entries, dict):
        entries = [entries]
    stats = {"listed": len(entries), "other_notice_types": 0, "already_seen": 0, "new": 0}
    out: list[dict[str, Any]] = []
    offered_companies: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        code = str(entry.get("f:notice-code") or "")
        if code not in GAZETTE_NOTICE_CODES:
            stats["other_notice_types"] += 1
            continue
        notice_id = str(entry.get("id") or "").rstrip("/").rsplit("/", 1)[-1]
        company = plain(entry.get("title"))
        if not notice_id.isdigit() or not company:
            continue
        company_key = _company_key(company)
        # One company produces two or three notices; it is one story.
        if is_seen(state, key, notice_id) or is_seen(state, key, company_key) or company_key in offered_companies:
            stats["already_seen"] += 1
            mark_seen(state, key, notice_id)
            continue
        stats["new"] += 1
        if len(out) >= limit:
            continue
        offered_companies.add(company_key)
        try:
            published = datetime.fromisoformat(str(entry.get("published"))).replace(tzinfo=LONDON)
        except ValueError:
            published = now
        kind = GAZETTE_NOTICE_CODES[code]
        out.append(record(
            key, notice_id, name="The Gazette", url=f"https://www.thegazette.co.uk/notice/{notice_id}",
            title=f"{company}: {kind}", summary=f"Official notice in The Gazette ({kind}). {plain(entry.get('content'))}",
            published=published, area=detect_town(plain(entry.get("content"))), category="business",
            also_seen=(company_key,),
        ))
    return out, stats


# --------------------------------------------------------------------------
# Parliament: written answers to the borough's MPs
# --------------------------------------------------------------------------

QUESTIONS_API = "https://questions-statements-api.parliament.uk/api/writtenquestions/questions"
# Member IDs and constituencies verified against the Members API, 9 October 2026.
# This list must be checked after every general election or by-election.
LOCAL_MPS = (
    {"member_id": 5071, "name": "Paul Waugh", "seat": "Rochdale", "area": "rochdale"},
    {"member_id": 5084, "name": "Elsie Blundell", "seat": "Heywood and Middleton North", "area": "heywood"},
)
QUESTIONS_LOOKBACK_DAYS = 14


def written_answers(get: Callable[..., Any], state: dict[str, Any], now: datetime, limit: int) -> tuple[list[dict[str, Any]], dict[str, int]]:
    key = "written_answers"
    since = (now.astimezone(LONDON) - timedelta(days=QUESTIONS_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    stats = {"listed": 0, "unanswered_or_holding": 0, "not_about_the_borough": 0, "already_seen": 0, "new": 0}
    fresh: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    for mp in LOCAL_MPS:
        response = get(QUESTIONS_API, params={
            "askingMemberId": str(mp["member_id"]), "answeredWhenFrom": since, "take": "40",
        }, timeout=TIMEOUT)
        response.raise_for_status()
        for item in response.json().get("results") or []:
            value = item.get("value") if isinstance(item, dict) else None
            if not isinstance(value, dict):
                continue
            stats["listed"] += 1
            uin = str(value.get("uin") or "").strip()
            tabled = str(value.get("dateTabled") or "")[:10]
            answered = str(value.get("dateAnswered") or "")[:10]
            if (not uin or not tabled or not answered or not plain(value.get("heading"))
                    or not plain(value.get("answerText"))
                    or value.get("isWithdrawn") or value.get("answerIsHolding")):
                stats["unanswered_or_holding"] += 1
                continue
            identity = f"{tabled}/{uin}"
            if is_seen(state, key, identity):
                stats["already_seen"] += 1
                continue
            # An MP asks about everything from water bills to prisons. Only an
            # exchange that names a place in the borough is local news, and
            # only that can pass the paper's locality rule.
            exchange = " ".join(plain(value.get(field)) for field in ("heading", "questionText", "answerText"))
            if not names_borough_place(exchange):
                stats["not_about_the_borough"] += 1
                mark_seen(state, key, identity)
                continue
            stats["new"] += 1
            fresh.append((answered, mp, value))
    fresh.sort(key=lambda row: row[0], reverse=True)       # newest answer first
    out: list[dict[str, Any]] = []
    for answered, mp, value in fresh[:limit]:
        tabled = str(value["dateTabled"])[:10]
        uin = str(value["uin"]).strip()
        department = plain(value.get("answeringBodyName")) or "the government"
        try:
            published = datetime.fromisoformat(answered).replace(tzinfo=LONDON)
        except ValueError:
            published = now
        out.append(record(
            key, f"{tabled}/{uin}", name="UK Parliament",
            url=f"https://questions-statements.parliament.uk/written-questions/detail/{tabled}/{uin}",
            title=f"{mp['seat']} MP {mp['name']} gets written answer on {plain(value.get('heading'))}",
            summary=(f"{mp['name']}, MP for {mp['seat']}, asked: {plain(value.get('questionText'))} "
                     f"{department} answered: {plain(value.get('answerText'))}"),
            published=published, area=mp["area"], category="politics",
        ))
    return out, stats


# --------------------------------------------------------------------------
# Greater Manchester Combined Authority decisions naming a borough place
# --------------------------------------------------------------------------

GMCA_HOST = "https://democracy.greatermanchester-ca.gov.uk"
GMCA_RSS = GMCA_HOST + "/mgRss.aspx?XXR=0&M=0"
_RSS_ITEM_RE = re.compile(r"<item\b[^>]*>(?P<body>.*?)</item>", re.I | re.S)
_RSS_FIELD_RE = {name: re.compile(rf"<{name}\b[^>]*>(?P<v>.*?)</{name}>", re.I | re.S) for name in ("title", "link", "pubDate")}
_GMCA_DECISION_RE = re.compile(r"ieDecisionDetails\.aspx\?(?:[^\"'<>\s]*?&(?:amp;)?)?ID=(?P<id>\d+)", re.I)
_CDATA_RE = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.S)


def _rss_field(body: str, name: str) -> str:
    match = _RSS_FIELD_RE[name].search(body)
    if not match:
        return ""
    return plain(_CDATA_RE.sub(lambda m: m.group(1), match.group("v")))


def gmca_decisions(get: Callable[..., Any], state: dict[str, Any], now: datetime, limit: int) -> tuple[list[dict[str, Any]], dict[str, int]]:
    key = "gmca_decisions"
    response = get(GMCA_RSS, timeout=TIMEOUT)
    response.raise_for_status()
    stats = {"listed": 0, "not_decisions": 0, "no_borough_place": 0, "already_seen": 0, "new": 0}
    out: list[dict[str, Any]] = []
    in_this_feed: set[str] = set()
    for item in _RSS_ITEM_RE.finditer(response.text or ""):
        body = item.group("body")
        stats["listed"] += 1
        decision = _GMCA_DECISION_RE.search(body)
        if not decision:
            stats["not_decisions"] += 1
            continue
        decision_id = decision.group("id")
        if decision_id in in_this_feed:      # the feed repeats a decision once per signatory
            continue
        in_this_feed.add(decision_id)
        title = _rss_field(body, "title")
        if is_seen(state, key, decision_id):
            stats["already_seen"] += 1
            continue
        if not names_borough_place(title):
            stats["no_borough_place"] += 1
            mark_seen(state, key, decision_id)
            continue
        stats["new"] += 1
        if len(out) >= limit:
            continue
        out.append(record(
            key, decision_id, name="Greater Manchester Combined Authority",
            url=f"{GMCA_HOST}/ieDecisionDetails.aspx?ID={decision_id}",
            title=f"GMCA decision: {title}",
            summary=f"Decision published by the Greater Manchester Combined Authority: {title}.",
            published=now, area=detect_town(title), category="politics",
        ))
    return out, stats


# --------------------------------------------------------------------------
# ONS: house prices and private rents in Rochdale (monthly)
# --------------------------------------------------------------------------

ONS_HOUSING_URL = "https://www.ons.gov.uk/visualisations/housingpriceslocal/E08000005/"
_ONS_UPDATED_RE = re.compile(r"Last updated:\s*(?P<date>\d{1,2}\s+[A-Za-z]+\s+20\d{2})")
_ONS_PRICE_RE = re.compile(r"The average house price in Rochdale was[^.]*?\d[^.]*\.(?:\d[^.]*\.)?")
_ONS_RENT_RE = re.compile(r"Private rents (?:rose|fell|were unchanged)[^.]*?\d[^.]*\.(?:\d[^.]*\.)?")
_SCRIPT_RE = re.compile(r"<(script|style)\b.*?</\1>", re.I | re.S)


def ons_housing(get: Callable[..., Any], state: dict[str, Any], now: datetime, limit: int) -> tuple[list[dict[str, Any]], dict[str, int]]:
    key = "ons_housing"
    response = get(ONS_HOUSING_URL, timeout=TIMEOUT)
    response.raise_for_status()
    text = plain(_SCRIPT_RE.sub(" ", response.text or ""))
    updated = _ONS_UPDATED_RE.search(text)
    price = _ONS_PRICE_RE.search(text)
    stats = {"listed": 1 if updated else 0, "already_seen": 0, "new": 0}
    if not updated or not price:
        # The page changed shape. Say nothing rather than guess a figure.
        stats["unreadable"] = 1
        return [], stats
    stamp = _WS_RE.sub("-", updated.group("date").strip().lower())
    if is_seen(state, key, stamp):
        stats["already_seen"] = 1
        return [], stats
    stats["new"] = 1
    if limit < 1:
        return [], stats
    rent = _ONS_RENT_RE.search(text)
    summary = price.group(0) + (" " + rent.group(0) if rent else "")
    # The address is the same every month. The fragment makes each month's
    # release a different source to the rewrite ledger, as the FSA roundup does.
    return [record(
        key, stamp, name="Office for National Statistics", url=f"{ONS_HOUSING_URL}#updated-{stamp}",
        title=f"Rochdale house prices and rents: ONS figures updated {updated.group('date')}",
        summary=summary, published=now, area="rochdale", category="business",
    )], stats


# --------------------------------------------------------------------------
# The rota itself
# --------------------------------------------------------------------------

SOURCES: dict[str, Callable[..., tuple[list[dict[str, Any]], dict[str, int]]]] = {
    "council_roadworks": council_roadworks,
    "gazette_insolvency": gazette_insolvency,
    "written_answers": written_answers,
    "gmca_decisions": gmca_decisions,
    "ons_housing": ons_housing,
}


def collect(get: Callable[..., Any], state: dict[str, Any], now: datetime | None = None,
            only: set[str] | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read every source that is due. Returns (records to offer, a report per source).

    One source failing never stops the others: it is reported as an error and
    tried again on its next interval. A source at its daily cap is still read,
    so its report shows what is waiting, but offers nothing.
    """
    now = now or datetime.now(timezone.utc)
    offered: list[dict[str, Any]] = []
    report: dict[str, Any] = {}
    for key, source in SOURCES.items():
        if only is not None and key not in only:
            continue
        if not is_due(state, key, now):
            report[key] = {"status": "not due", "last_checked": _slot(state, key).get("last_checked"),
                           "interval_hours": ROTA[key][0]}
            continue
        allowance = remaining_today(state, key, now)
        try:
            records, stats = source(get, state, now, allowance)
        except Exception as exc:                      # report it; do not take the run down
            report[key] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"[:200]}
            # Wait a full interval before retrying, so a broken source is not hit every run.
            _slot(state, key)["last_checked"] = iso(now)
            continue
        slot = _slot(state, key)
        slot["last_checked"] = iso(now)
        for item in records:
            mark_seen(state, key, item["identity"])
            for extra in item.get("also_seen") or []:
                mark_seen(state, key, extra)
        slot["offered_today"] = int(slot.get("offered_today") or 0) + len(records)
        offered.extend(records)
        report[key] = {"status": "ok", "offered": len(records), "daily_cap": ROTA[key][1],
                       "offered_today": slot["offered_today"], **stats}
    return offered, report
