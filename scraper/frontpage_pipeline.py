"""Post-process Rochdale Daily into a balanced front page and physical event feed.

This module runs after ``scraper/scraper.py`` and before static-page generation.
It deliberately leaves the site's typography untouched. Its responsibilities are:

* make What's Occurrin' Events the only automated event source;
* reject online/virtual events and listings without a physical Rochdale-area venue;
* merge duplicate reports into one larger ONGOING article with a dated timeline;
* retain a 14-day article archive while selecting a balanced 30-36 story front page;
* write ``articles/frontpage.json`` with category, ward and source coverage diagnostics.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
from collections import Counter, defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import dateparser
import requests
from bs4 import BeautifulSoup

from editorial_upgrade import (
    DEFAULT_CATEGORY_MINIMUMS,
    article_word_count as editorial_word_count,
    deterministic_category as editorial_category,
    enforce_category_minimums,
)
from selection_policy import (
    PUBLISH_CATEGORIES,
    balanced_select,
    category_key,
    is_job_or_career_post,
    source_key,
    ward_for_item,
)
from story_identity import (
    build_story_key,
    categories_compatible,
    hours_apart,
    incident_locations,
    incident_tokens,
    merge_article_records,
    named_entities,
    precise_locations,
    same_story,
    strip_publisher_suffix,
)

ARTICLES_PATH = Path(os.getenv("ARTICLES_JSON", "articles.json"))
FRONTPAGE_PATH = Path(os.getenv("FRONTPAGE_JSON", "articles/frontpage.json"))
STATUS_PATH = Path(os.getenv("SCRAPER_STATUS_JSON", "scraper_status.json"))
BLOCKLIST_PATH = Path(os.getenv("STORY_BLOCKLIST_JSON", "story_blocklist.json"))
ARTICLE_PAGES_DIR = Path(os.getenv("ARTICLE_PAGES_DIR", "articles"))
EVENT_SOURCE_URL = os.getenv(
    "EVENT_TICKET_SOURCE_URL",
    "https://www.whatsoccurrinevents.co.uk/ticket-box-office",
)
EVENT_DOMAIN = "whatsoccurrinevents.co.uk"
FRONTPAGE_MIN = int(os.getenv("FRONTPAGE_MIN_ARTICLES", "30"))
FRONTPAGE_TARGET = int(os.getenv("FRONTPAGE_TARGET_ARTICLES", "36"))
PRIMARY_DAYS = int(os.getenv("FRONTPAGE_PRIMARY_DAYS", "7"))
FALLBACK_DAYS = int(os.getenv("FRONTPAGE_FALLBACK_DAYS", "14"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))
UK_TZ = ZoneInfo("Europe/London")

ONLINE_EVENT_RE = re.compile(
    r"\b(?:online|virtual|webinar|web\s*conference|zoom|microsoft\s+teams|"
    r"teams\s+meeting|google\s+meet|live\s*stream|livestream|streamed|"
    r"remote\s+event|digital\s+event|watch\s+online|from\s+home)\b",
    re.IGNORECASE,
)
LOCAL_EVENT_RE = re.compile(
    r"\b(?:rochdale|littleborough|heywood|middleton|milnrow|newhey|wardle|"
    r"norden|castlet(?:on)?|kirkholt|spotland|falinge|deeplish|bamford|"
    r"smallbridge|firgrove|whitworth|shawclough|healey|syke|hopwood|"
    r"balderstone|darnhill|alkrington|boarshaw|smithy\s+bridge|"
    r"hollingworth\s+lake)\b|\bOL\d{1,2}\s*\d[A-Z]{2}\b",
    re.IGNORECASE,
)
AGE_RE = re.compile(
    r"\b(?:(\d{1,3})[-\s]?year[-\s]?old|aged?\s+(\d{1,3})|age\s+(\d{1,3}))\b",
    re.IGNORECASE,
)
GENDER_RE = re.compile(
    r"\b(man|male|woman|female|boy|girl|mother|mum|father|dad)\b",
    re.IGNORECASE,
)
VEHICLE_RE = re.compile(
    r"\b(?:black|white|silver|grey|gray|red|blue|green|yellow|orange|"
    r"dark|light)?\s*(?:[A-Z][A-Za-z0-9-]+\s+){0,2}"
    r"(?:car|van|lorry|truck|motorbike|motorcycle|scooter|taxi|vehicle)\b",
    re.IGNORECASE,
)
SPACE_RE = re.compile(r"\s+")
TAG_RE = re.compile(r"<[^>]+>")


LOW_QUALITY_ARTICLE_RE = re.compile(
    r"\b(?:has published (?:a|an) (?:crime|police|court|public[- ]safety|news) update|"
    r"the update was published by|the source item is titled|has been categorised as|"
    r"further confirmed information will be added|will update this report if the identified source|"
    r"the article remains open to correction|this automated brief does not add|"
    r"readers can use the source link)\b",
    re.IGNORECASE,
)


def is_low_quality_article(article: dict[str, Any]) -> bool:
    route = str(article.get("publication_route") or "").lower()
    if route in {"direct-crime-autopublish", "automatic-attributed-crime-fallback", "source-led-fallback"}:
        return True
    return bool(LOW_QUALITY_ARTICLE_RE.search(article_text(article)))

CATEGORY_CAPS = {
    "crime": 6,
    "events": 4,
    "traffic": 6,
    "transport": 5,
    "politics": 5,
    "education": 5,
    "sport": 4,
    "business": 5,
    "community": 5,
    "health": 5,
    "environment": 5,
    "news": 5,
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def plain_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = TAG_RE.sub(" ", text)
    return SPACE_RE.sub(" ", text).strip()


def article_text(article: dict[str, Any]) -> str:
    return " ".join(
        plain_text(article.get(field))
        for field in (
            "title",
            "excerpt",
            "summary",
            "content_html",
            "event_location",
            "source_url",
        )
        if article.get(field)
    )


def article_category(article: dict[str, Any]) -> str:
    text = article_text(article)
    if re.search(r"\b(?:kirkholt pantry|community pantry|food bank|foodbank|pantry)\b", text, re.IGNORECASE):
        return "community"
    detected = editorial_category(text, str(article.get("category") or "news"))
    if detected != "news":
        return detected
    if str(article.get("source_kind") or "").lower() == "event":
        return "events"
    return detected


def apply_category_rules(article: dict[str, Any]) -> dict[str, Any]:
    article = dict(article)
    category = article_category(article)
    article["category"] = category
    article["types"] = [category]
    if category == "crime":
        article["police_matter"] = True
    return article



def is_event(article: dict[str, Any]) -> bool:
    return (
        article_category(article) == "events"
        or str(article.get("source_kind") or "").lower() == "event"
    )


def source_domain(article: dict[str, Any]) -> str:
    return (urlparse(str(article.get("source_url") or "")).hostname or "").lower().removeprefix("www.")


def approved_event_source(article: dict[str, Any]) -> bool:
    return source_domain(article) == EVENT_DOMAIN


def is_online_event(article: dict[str, Any]) -> bool:
    if not is_event(article):
        return False
    return bool(ONLINE_EVENT_RE.search(article_text(article)))


def has_physical_local_venue(article: dict[str, Any]) -> bool:
    location = plain_text(article.get("event_location"))
    if not location or ONLINE_EVENT_RE.search(location):
        return False
    return bool(LOCAL_EVENT_RE.search(location))


def event_is_current(article: dict[str, Any], now: datetime | None = None) -> bool:
    start = parse_datetime(article.get("event_start_at"))
    if start is None:
        return False
    reference = now or utc_now()
    return start >= reference - timedelta(hours=12)


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:90] or "local-event"


def stable_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def normalise_url(value: str) -> str:
    parsed = urlparse(str(value or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return ""
    return parsed._replace(fragment="", query="").geturl().rstrip("/")


def area_from_location(location: str) -> str:
    lowered = location.lower()
    for area in (
        "littleborough", "heywood", "middleton", "milnrow", "newhey",
        "wardle", "norden", "castleton", "kirkholt", "spotland", "falinge",
        "deeplish", "bamford", "smallbridge", "firgrove", "whitworth",
        "shawclough", "healey", "hopwood", "balderstone", "rochdale",
    ):
        if re.search(rf"\b{re.escape(area)}\b", lowered):
            return area
    return "rochdale"


def _line_list(soup: BeautifulSoup) -> list[str]:
    return [
        SPACE_RE.sub(" ", line).strip()
        for line in soup.get_text("\n").splitlines()
        if SPACE_RE.sub(" ", line).strip()
    ]


def _event_detail_urls(index_html: str) -> list[str]:
    soup = BeautifulSoup(index_html, "html.parser")
    seen: set[str] = set()
    urls: list[str] = []
    for anchor in soup.select('a[href*="/event-details/"]'):
        url = normalise_url(urljoin(EVENT_SOURCE_URL, anchor.get("href", "")))
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _extract_event_datetime(lines: list[str]) -> tuple[datetime | None, int]:
    patterns = (
        re.compile(r"\b\d{1,2}\s+[A-Za-z]{3,9}\s+20\d{2},\s*\d{1,2}:\d{2}\b"),
        re.compile(r"\b[A-Za-z]{3}\s+\d{1,2}\s+[A-Za-z]{3}\s+20\d{2},\s*\d{1,2}:\d{2}\b"),
    )
    for index, line in enumerate(lines):
        for pattern in patterns:
            match = pattern.search(line)
            if not match:
                continue
            parsed = dateparser.parse(
                match.group(0),
                settings={
                    "TIMEZONE": "Europe/London",
                    "RETURN_AS_TIMEZONE_AWARE": True,
                    "PREFER_DATES_FROM": "future",
                },
            )
            if parsed:
                return parsed.astimezone(timezone.utc), index
    return None, -1


def _extract_event_location(lines: list[str], date_index: int) -> str:
    if date_index >= 0:
        for line in lines[date_index + 1 : date_index + 8]:
            lowered = line.lower()
            if lowered in {"about the event", "tickets", "time & location", "show more"}:
                continue
            if LOCAL_EVENT_RE.search(line) and not ONLINE_EVENT_RE.search(line):
                return line
    for line in lines:
        if LOCAL_EVENT_RE.search(line) and not ONLINE_EVENT_RE.search(line):
            if len(line) <= 180:
                return line
    return ""


def _extract_event_summary(soup: BeautifulSoup, lines: list[str]) -> str:
    paragraphs = [plain_text(node.get_text(" ", strip=True)) for node in soup.find_all("p")]
    paragraphs = [
        paragraph for paragraph in paragraphs
        if len(paragraph) >= 45
        and not ONLINE_EVENT_RE.search(paragraph)
        and "privacy" not in paragraph.lower()
        and "newsletter" not in paragraph.lower()
    ]
    if paragraphs:
        return " ".join(paragraphs[:2])[:900]

    try:
        start = next(index for index, line in enumerate(lines) if line.lower() == "about the event")
    except StopIteration:
        start = -1
    if start >= 0:
        chosen: list[str] = []
        for line in lines[start + 1 :]:
            if line.lower() in {"show more", "tickets", "share this event"}:
                break
            if len(line) >= 35:
                chosen.append(line)
            if len(chosen) == 3:
                break
        if chosen:
            return " ".join(chosen)[:900]
    return "Ticketed local event listed by What's Occurrin' Events."


def parse_event_detail(url: str, detail_html: str, now: datetime | None = None) -> dict[str, Any] | None:
    soup = BeautifulSoup(detail_html, "html.parser")
    title_node = soup.find("h1")
    title = plain_text(title_node.get_text(" ", strip=True) if title_node else "")
    if not title:
        meta = soup.find("meta", property="og:title")
        title = plain_text(meta.get("content", "") if meta else "")
    if not title:
        return None

    lines = _line_list(soup)
    event_start, date_index = _extract_event_datetime(lines)
    location = _extract_event_location(lines, date_index)
    summary = _extract_event_summary(soup, lines)
    reference = now or utc_now()

    candidate = {
        "title": title,
        "summary": summary,
        "excerpt": summary,
        "event_location": location,
        "event_start_at": iso_utc(event_start) if event_start else "",
        "source_url": url,
        "source_name": "What's Occurrin' Events",
        "source_kind": "event",
        "category": "events",
    }
    if is_online_event(candidate) or not has_physical_local_venue(candidate):
        return None
    if not event_start or event_start < reference - timedelta(hours=12):
        return None

    image_meta = soup.find("meta", property="og:image")
    source_image_candidate_url = str(image_meta.get("content", "") if image_meta else "").strip()
    # Keep the site's existing local artwork unless image reuse is explicitly licensed.
    image_url = "assets/img/category_events.svg"
    area = area_from_location(location)
    scraped_at = iso_utc(reference)
    date_label = event_start.astimezone(UK_TZ).strftime("%A %-d %B %Y at %H:%M")
    safe_summary = html.escape(summary)
    safe_location = html.escape(location)
    content_html = (
        f"<p>{safe_summary}</p>"
        f"<p><strong>Date and time:</strong> {html.escape(date_label)}</p>"
        f"<p><strong>Venue:</strong> {safe_location}</p>"
        f'<p><a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">View details and buy tickets</a>.</p>'
    )
    event_id = stable_id(url)
    return {
        "id": event_id,
        "story_key": build_story_key(candidate),
        "title": title,
        "slug": slugify(title),
        "excerpt": summary[:320],
        "summary": summary[:320],
        "content_html": content_html,
        "area": area,
        "ward": "",
        "category": "events",
        "types": ["events"],
        "published_at": scraped_at,
        "scraped_at": scraped_at,
        "image_url": image_url,
        "image_credit": "Rochdale Daily event artwork",
        "source_image_candidate_url": source_image_candidate_url,
        "source_image_reuse_status": "permission-required" if source_image_candidate_url else "",
        "event_start_at": iso_utc(event_start),
        "event_end_at": "",
        "event_location": location,
        "source_kind": "event",
        "source_name": "What's Occurrin' Events",
        "source_url": url,
        "source_names": ["What's Occurrin' Events"],
        "source_urls": [url],
        "source_count": 1,
        "sensitive_story": False,
        "police_matter": False,
        "requires_approval": False,
        "legal_disclaimer": "Event details can change. Check the organiser's ticket page before travelling.",
        "right_to_reply": "Organisers may request a correction by emailing news@rochdaledaily.co.uk.",
        "byline": "Rochdale Daily What's On",
        "status": "published",
    }


def collect_ticket_events(session: requests.Session | None = None) -> tuple[list[dict[str, Any]], str]:
    client = session or requests.Session()
    client.headers.update({
        "User-Agent": "RochdaleDaily/1.0 (+https://rochdaledaily.co.uk)",
        "Accept-Language": "en-GB,en;q=0.9",
    })
    try:
        response = client.get(EVENT_SOURCE_URL, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        urls = _event_detail_urls(response.text)
        events: list[dict[str, Any]] = []
        for url in urls[:30]:
            try:
                detail = client.get(url, timeout=REQUEST_TIMEOUT)
                detail.raise_for_status()
                event = parse_event_detail(url, detail.text)
                if event:
                    events.append(event)
            except requests.RequestException:
                continue
        return events, ""
    except requests.RequestException as exc:
        return [], str(exc)



def load_blocklist() -> dict[str, list[str]]:
    payload = read_json(BLOCKLIST_PATH, {})
    if not isinstance(payload, dict):
        payload = {}
    return {
        "title_patterns": [str(value).lower() for value in payload.get("title_patterns", []) if value],
        "source_urls": [normalise_url(str(value)) for value in payload.get("source_urls", []) if value],
        "slugs": [str(value).lower() for value in payload.get("slugs", []) if value],
    }


def is_blocked_article(article: dict[str, Any], blocklist: dict[str, list[str]]) -> bool:
    title = plain_text(article.get("title")).lower()
    slug = str(article.get("slug") or "").lower()
    source_url = normalise_url(str(article.get("source_url") or ""))
    if slug and slug in set(blocklist.get("slugs", [])):
        return True
    if source_url and source_url in set(blocklist.get("source_urls", [])):
        return True
    return any(pattern and pattern in title for pattern in blocklist.get("title_patterns", []))


def cleanup_stale_article_pages(
    articles: list[dict[str, Any]],
    blocklist: dict[str, list[str]] | None = None,
) -> int:
    """Delete article pages ONLY for editorially blocklisted slugs.

    A story dropping out of the live articles.json — through freshness
    pruning, a duplicate merge, or headline/slug drift on a rewrite — must
    NOT remove its page. Published URLs stay online permanently and become
    archive background for newer entries; deleting them 404s already-indexed
    pages and destroys the site's search long tail. (The previous behaviour
    deleted every page whose slug was not in the current articles.json,
    which gave published pages a median lifespan of 4.3 hours.)

    Deletion is reserved for deliberate takedowns via the "slugs" list in
    story_blocklist.json.
    """
    if not ARTICLE_PAGES_DIR.exists():
        return 0
    blocked = {
        str(slug).lower()
        for slug in (blocklist or {}).get("slugs", [])
        if slug
    }
    if not blocked:
        return 0
    removed = 0
    for path in ARTICLE_PAGES_DIR.glob("*.html"):
        if path.stem.lower() in blocked:
            path.unlink()
            removed += 1
    return removed

def _extract_paragraphs(article: dict[str, Any]) -> list[str]:
    soup = BeautifulSoup(str(article.get("content_html") or ""), "html.parser")
    paragraphs = [plain_text(node.get_text(" ", strip=True)) for node in soup.find_all("p")]
    if not paragraphs:
        fallback = plain_text(article.get("excerpt") or article.get("summary"))
        paragraphs = [fallback] if fallback else []
    return [
        paragraph for paragraph in paragraphs
        if paragraph
        and "ongoing story" not in paragraph.lower()
        and "sources used" not in paragraph.lower()
        and not paragraph.lower().startswith("date and time:")
    ]


def _token_set(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.lower()))


def _near_duplicate_text(left: str, right: str) -> bool:
    if plain_text(left).lower() == plain_text(right).lower():
        return True
    left_tokens, right_tokens = _token_set(left), _token_set(right)
    if not left_tokens or not right_tokens:
        return False
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens) >= 0.82


def _unique_paragraphs(records: Iterable[dict[str, Any]], limit: int = 16) -> list[str]:
    output: list[str] = []
    for record in records:
        for paragraph in _extract_paragraphs(record):
            if len(paragraph) < 30:
                continue
            if any(_near_duplicate_text(paragraph, existing) for existing in output):
                continue
            output.append(paragraph)
            if len(output) >= limit:
                return output
    return output


def _ages(article: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for match in AGE_RE.finditer(article_text(article)):
        values.update(value for value in match.groups() if value)
    return values


def _genders(article: dict[str, Any]) -> set[str]:
    canonical = {
        "man": "male", "male": "male", "boy": "male", "father": "male", "dad": "male",
        "woman": "female", "female": "female", "girl": "female", "mother": "female", "mum": "female",
    }
    return {canonical[match.group(1).lower()] for match in GENDER_RE.finditer(article_text(article))}


def _vehicles(article: dict[str, Any]) -> set[str]:
    return {SPACE_RE.sub(" ", match.group(0).lower()).strip() for match in VEHICLE_RE.finditer(article_text(article))}


def extended_incident_match(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Add age/vehicle support without using ethnicity as an identity signal."""
    if not categories_compatible(left, right) or hours_apart(left, right) > 72:
        return False
    shared_incidents = incident_tokens(left) & incident_tokens(right)
    if not shared_incidents:
        return False

    left_precise, right_precise = precise_locations(left), precise_locations(right)
    if left_precise and right_precise:
        shared_location = left_precise & right_precise
    else:
        shared_location = incident_locations(left) & incident_locations(right)
    if not shared_location:
        return False

    shared_people = named_entities(left) & named_entities(right)
    shared_ages = _ages(left) & _ages(right)
    shared_genders = _genders(left) & _genders(right)
    shared_vehicles = _vehicles(left) & _vehicles(right)

    if shared_people or shared_vehicles:
        return True
    return bool(shared_ages and shared_genders)


def records_match(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return (
        build_story_key(left) == build_story_key(right)
        or same_story(left, right)
        or extended_incident_match(left, right)
    )


def _timeline_label(article: dict[str, Any]) -> str:
    value = parse_datetime(article.get("published_at") or article.get("scraped_at"))
    if value is None:
        return "Date unavailable"
    return value.astimezone(UK_TZ).strftime("%-d %B %Y, %H:%M")


def merge_group(group: list[dict[str, Any]]) -> dict[str, Any]:
    if len(group) == 1:
        single = dict(group[0])
        single["story_key"] = build_story_key(single)
        return single

    ordered = sorted(
        group,
        key=lambda item: parse_datetime(item.get("published_at")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    merged = dict(group[0])
    for record in group[1:]:
        merged = merge_article_records(merged, record)

    merged["title"] = strip_publisher_suffix(str(merged.get("title") or ordered[0].get("title") or "Local news update"))
    paragraphs = _unique_paragraphs(ordered)
    overview = plain_text(merged.get("excerpt") or merged.get("summary") or (paragraphs[0] if paragraphs else ""))
    latest = paragraphs[:4]
    earlier = paragraphs[4:12]
    update_count = max(
        len(group),
        int(merged.get("source_count") or 1),
        int(merged.get("update_count") or 1),
    )
    updated = max(
        (parse_datetime(item.get("published_at") or item.get("scraped_at")) for item in group),
        default=utc_now(),
        key=lambda value: value or datetime.min.replace(tzinfo=timezone.utc),
    ) or utc_now()

    parts = [
        f'<p class="ongoing-label"><strong>ONGOING STORY</strong> — Updated {html.escape(updated.astimezone(UK_TZ).strftime("%-d %B %Y at %H:%M"))}. {update_count} source updates have been combined into this article.</p>'
    ]
    if overview:
        parts.append(f"<p>{html.escape(overview)}</p>")
    if latest:
        parts.append("<h2>Latest update</h2>")
        parts.extend(f"<p>{html.escape(paragraph)}</p>" for paragraph in latest)
    if earlier:
        parts.append("<h2>Earlier developments</h2>")
        parts.extend(f"<p>{html.escape(paragraph)}</p>" for paragraph in earlier)

    parts.append("<h2>Update timeline</h2><ul>")
    seen_timeline: set[tuple[str, str]] = set()
    for record in ordered:
        label = _timeline_label(record)
        title = strip_publisher_suffix(str(record.get("title") or "Update"))
        key = (label, title.lower())
        if key in seen_timeline:
            continue
        seen_timeline.add(key)
        parts.append(f"<li><strong>{html.escape(label)}:</strong> {html.escape(title)}</li>")
    parts.append("</ul>")

    merged["content_html"] = "".join(parts)
    merged["excerpt"] = overview[:320] if overview else plain_text(merged.get("excerpt"))[:320]
    merged["summary"] = merged["excerpt"]
    merged["is_ongoing"] = True
    merged["ongoing_label"] = "ONGOING"
    merged["update_count"] = update_count
    merged["last_updated_at"] = iso_utc(updated)
    merged["story_key"] = build_story_key(merged)
    return merged


def merge_duplicate_articles(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records = [dict(item) for item in items]
    count = len(records)
    parent = list(range(count))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for left in range(count):
        for right in range(left + 1, count):
            if records_match(records[left], records[right]):
                union(left, right)

    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for index, record in enumerate(records):
        groups[find(index)].append(record)
    return [merge_group(group) for group in groups.values()]


def clean_and_integrate_events(
    articles: list[dict[str, Any]],
    scraped_events: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    existing_approved: dict[str, dict[str, Any]] = {}
    retained: list[dict[str, Any]] = []
    removed_other_source = 0
    removed_online = 0
    removed_no_venue = 0

    for article in articles:
        if not is_event(article):
            retained.append(article)
            continue
        if not approved_event_source(article):
            removed_other_source += 1
            continue
        if is_online_event(article):
            removed_online += 1
            continue
        if not has_physical_local_venue(article) or not event_is_current(article):
            removed_no_venue += 1
            continue
        existing_approved[normalise_url(str(article.get("source_url") or ""))] = article

    for event in scraped_events:
        key = normalise_url(str(event.get("source_url") or ""))
        previous = existing_approved.get(key)
        if previous:
            event["id"] = previous.get("id") or event["id"]
            event["slug"] = previous.get("slug") or event["slug"]
            event["published_at"] = previous.get("published_at") or event["published_at"]
        existing_approved[key] = event

    retained.extend(existing_approved.values())
    return retained, {
        "events_removed_other_source": removed_other_source,
        "online_events_rejected": removed_online,
        "events_rejected_missing_physical_local_venue": removed_no_venue,
        "approved_ticket_events": len(existing_approved),
    }


def _age_eligible(article: dict[str, Any], cutoff: datetime) -> bool:
    if is_event(article):
        return approved_event_source(article) and not is_online_event(article) and has_physical_local_venue(article) and event_is_current(article)
    published = parse_datetime(article.get("published_at") or article.get("scraped_at"))
    return published is not None and published >= cutoff


def _article_rank(article: dict[str, Any], now: datetime) -> tuple[Any, ...]:
    category = article_category(article)
    published = parse_datetime(article.get("published_at") or article.get("scraped_at")) or datetime.min.replace(tzinfo=timezone.utc)
    age_hours = max(0.0, (now - published).total_seconds() / 3600)
    importance = {
        "crime": 100,
        "traffic": 80,
        "transport": 75,
        "politics": 72,
        "health": 70,
        "education": 65,
        "community": 60,
        "business": 55,
        "environment": 52,
        "sport": 50,
        "events": 35,
        "news": 58,
    }.get(category, 50)
    if editorial_word_count(article) >= 200 or is_event(article):
        importance += 18
    else:
        importance -= 25
    if article.get("is_ongoing"):
        importance += 12
    importance += min(12, int(article.get("source_count") or 1) * 2)
    importance -= min(40, age_hours / 12)
    return (importance, published)


def _cap_selected(items: list[dict[str, Any]], target: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    category_counts: Counter[str] = Counter()
    ward_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()

    for item in items:
        category = category_key(item)
        ward = ward_for_item(item) or "borough-wide"
        source = source_key(item)
        if category_counts[category] >= CATEGORY_CAPS.get(category, 5):
            continue
        if source_counts[source] >= 4:
            continue
        if ward_counts[ward] >= 3 and len({ward_for_item(x) for x in selected if ward_for_item(x)}) < 10:
            continue
        selected.append(item)
        category_counts[category] += 1
        ward_counts[ward] += 1
        source_counts[source] += 1
        if len(selected) >= target:
            return selected

    # Relax ward/source caps before relaxing category caps.
    for item in items:
        if item in selected:
            continue
        category = category_key(item)
        if category_counts[category] >= CATEGORY_CAPS.get(category, 5):
            continue
        selected.append(item)
        category_counts[category] += 1
        if len(selected) >= target:
            return selected

    for item in items:
        if item not in selected:
            selected.append(item)
        if len(selected) >= target:
            break
    return selected


def arrange_frontpage(items: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    if not items:
        return []
    ranked = sorted(items, key=lambda item: _article_rank(item, now), reverse=True)
    lead = ranked[0]
    remaining = ranked[1:]
    by_category: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
    for item in remaining:
        by_category[category_key(item)].append(item)

    category_order = deque(
        category for category in PUBLISH_CATEGORIES
        if by_category.get(category)
    )
    arranged = [lead]
    while category_order:
        category = category_order.popleft()
        queue = by_category[category]
        if queue:
            arranged.append(queue.popleft())
        if queue:
            category_order.append(category)

    for index, article in enumerate(arranged):
        article["frontpage_rank"] = index
        article["frontpage_priority"] = max(1, 1000 - index)
        if index == 0:
            article["slot"] = "lead"
        elif index == 1:
            article["slot"] = "secondary-1"
        elif index == 2:
            article["slot"] = "secondary-2"
        else:
            article["slot"] = ""
    return arranged


def select_frontpage(articles: list[dict[str, Any]], now: datetime | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    reference = now or utc_now()
    base = [
        article for article in articles
        if str(article.get("status") or "published") == "published"
        and not is_job_or_career_post(article)
    ]
    primary_cutoff = reference - timedelta(days=PRIMARY_DAYS)
    fallback_cutoff = reference - timedelta(days=FALLBACK_DAYS)
    primary = [article for article in base if _age_eligible(article, primary_cutoff)]
    pool = primary if len(primary) >= FRONTPAGE_MIN else [article for article in base if _age_eligible(article, fallback_cutoff)]
    pool = sorted(pool, key=lambda item: _article_rank(item, reference), reverse=True)
    longform_pool = [
        item for item in pool
        if is_event(item) or editorial_word_count(item) >= 200
    ]
    if len(longform_pool) >= FRONTPAGE_MIN:
        pool = longform_pool

    balanced, diagnostics = balanced_select(
        pool,
        limit=min(FRONTPAGE_TARGET, len(pool)),
        max_per_source=4,
        max_per_category=6,
    )
    target = min(FRONTPAGE_TARGET, len(pool))
    capped = _cap_selected(
        balanced + [item for item in pool if item not in balanced],
        target,
    )
    capped = enforce_category_minimums(
        capped,
        pool,
        target,
        category_key,
        DEFAULT_CATEGORY_MINIMUMS,
    )
    arranged = arrange_frontpage(capped, reference)
    diagnostics = dict(diagnostics)
    diagnostics.update({
        "pool_size": len(pool),
        "primary_pool_size": len(primary),
        "selection_window_days": PRIMARY_DAYS if len(primary) >= FRONTPAGE_MIN else FALLBACK_DAYS,
        "frontpage_count": len(arranged),
        "selected_by_category": dict(Counter(category_key(item) for item in arranged)),
        "selected_by_ward": dict(Counter(ward_for_item(item) or "borough-wide" for item in arranged)),
        "selected_by_source": dict(Counter(source_key(item) for item in arranged)),
    })
    return arranged, diagnostics


def _dedupe_by_url(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        key = str(item.get("story_key") or build_story_key(item) or item.get("source_url") or item.get("title")).lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def update_status(status: dict[str, Any], payload: dict[str, Any]) -> None:
    status.update(payload)
    write_json_atomic(STATUS_PATH, status)


def main() -> int:
    now = utc_now()
    articles = read_json(ARTICLES_PATH, [])
    if not isinstance(articles, list):
        raise RuntimeError("articles.json must contain a JSON list")
    blocklist = load_blocklist()
    blocked_before_processing = sum(1 for article in articles if is_blocked_article(article, blocklist))
    articles = [article for article in articles if not is_blocked_article(article, blocklist)]
    low_quality_before_processing = sum(1 for article in articles if is_low_quality_article(article))
    articles = [article for article in articles if not is_low_quality_article(article)]
    articles = [apply_category_rules(article) for article in articles]

    events, event_error = collect_ticket_events()
    cleaned, event_diagnostics = clean_and_integrate_events(articles, events)
    cleaned = [apply_category_rules(article) for article in cleaned]
    merged = merge_duplicate_articles(cleaned)
    merged = [apply_category_rules(article) for article in merged]
    merged = _dedupe_by_url(merged)
    merged.sort(
        key=lambda article: parse_datetime(article.get("published_at")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    write_json_atomic(ARTICLES_PATH, merged)
    stale_article_pages_removed = cleanup_stale_article_pages(merged, blocklist)

    frontpage, coverage = select_frontpage(merged, now)
    previous = read_json(FRONTPAGE_PATH, {})
    previous_articles = previous.get("articles", []) if isinstance(previous, dict) else []
    safe_previous_articles = [
        article for article in previous_articles
        if isinstance(article, dict)
        and not is_blocked_article(article, blocklist)
        and not is_low_quality_article(article)
        and (not is_event(article) or (approved_event_source(article) and not is_online_event(article) and has_physical_local_venue(article)))
    ] if isinstance(previous_articles, list) else []
    if len(frontpage) < FRONTPAGE_MIN:
        if len(safe_previous_articles) >= FRONTPAGE_MIN:
            frontpage = safe_previous_articles
            coverage["used_previous_frontpage_because_new_selection_below_minimum"] = True
        else:
            raise RuntimeError(
                f"Only {len(frontpage)} valid unique stories are available; "
                f"the front page requires at least {FRONTPAGE_MIN}."
            )

    approved_events = [
        article for article in merged
        if is_event(article)
        and approved_event_source(article)
        and not is_online_event(article)
        and has_physical_local_venue(article)
        and event_is_current(article, now)
    ]
    approved_events.sort(
        key=lambda article: parse_datetime(article.get("event_start_at")) or datetime.max.replace(tzinfo=timezone.utc)
    )

    crime_headlines = [
        article.get("title") for article in frontpage
        if article_category(article) == "crime" and article.get("title")
    ][:5]
    payload = {
        "generated_at": iso_utc(now),
        "minimum_articles": FRONTPAGE_MIN,
        "target_articles": FRONTPAGE_TARGET,
        "count": len(frontpage),
        "breaking": "     •     BREAKING     •     ".join(crime_headlines),
        "articles": frontpage,
        "events": approved_events[:12],
        "coverage": coverage,
        "event_source": EVENT_SOURCE_URL,
        "online_events_rejected": True,
    }
    write_json_atomic(FRONTPAGE_PATH, payload)

    status = read_json(STATUS_PATH, {})
    if not isinstance(status, dict):
        status = {}
    update_status(status, {
        "frontpage_generated_at": iso_utc(now),
        "frontpage_article_count": len(frontpage),
        "frontpage_minimum_met": len(frontpage) >= FRONTPAGE_MIN,
        "frontpage_coverage": coverage,
        "event_ticket_source": EVENT_SOURCE_URL,
        "event_ticket_source_error": event_error,
        "ticket_events_collected_this_run": len(events),
        **event_diagnostics,
        "duplicate_articles_after_postprocessing": len(merged),
        "blocked_articles_removed": blocked_before_processing,
        "low_quality_articles_removed": low_quality_before_processing,
        "stale_article_pages_removed": stale_article_pages_removed,
        "online_events_allowed": False,
        "automated_event_sources_allowed": [EVENT_DOMAIN],
    })
    print(
        f"Front page: {len(frontpage)} unique balanced stories; "
        f"approved physical ticket events: {len(approved_events)}; "
        f"archive records after merging: {len(merged)}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
