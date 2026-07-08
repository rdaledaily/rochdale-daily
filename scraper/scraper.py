#!/usr/bin/env python3
"""
Rochdale Daily autonomous local-news pipeline.

The pipeline:
- checks public RSS feeds, public news pages and Google News RSS searches
  every scheduled run;
- searches the borough, townships, wards and named neighbourhoods;
- keeps the original source date and rejects stale or undated material;
- cross-references similar reports before asking OpenAI for an original article;
- automatically anonymises crime, court, safeguarding and allegation stories;
- removes names of suspects/defendants, exact residential addresses, postcodes,
  victim-identifying information and details that may prejudice proceedings;
- publishes suitable sensitive stories instead of placing them in a review queue;
- adds a legal/editorial note and a standing right-to-reply invitation;
- uses locally stored category artwork by default, avoiding unlicensed image reuse.

This is a technical risk-control system, not a substitute for qualified media-law
advice. A disclaimer cannot make unlawful content lawful, so items that remain
unsafe or too thin after redaction are skipped rather than published.
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import os
import re
import time
import urllib.parse
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote_plus, urljoin, urlparse, urlunparse

import feedparser
import requests
from bs4 import BeautifulSoup
from openai import OpenAI
from dateparser.search import search_dates
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_FILE = ROOT / "articles.json"
LOG_FILE = ROOT / "scraper" / "scraper.log"

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
MAX_NEWS_AGE_HOURS = int(os.getenv("MAX_NEWS_AGE_HOURS", "168"))
RETENTION_DAYS = int(os.getenv("ARTICLE_RETENTION_DAYS", "14"))
MAX_PUBLISHED_ARTICLES = int(os.getenv("MAX_PUBLISHED_ARTICLES", "100"))
MAX_AI_ARTICLES_PER_RUN = int(os.getenv("MAX_AI_ARTICLES_PER_RUN", "12"))
MAX_AI_ARTICLES_INITIAL = int(os.getenv("MAX_AI_ARTICLES_INITIAL", "35"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))
RESPECT_ROBOTS = os.getenv("RESPECT_ROBOTS", "true").lower() not in {"0", "false", "no"}
USE_SOURCE_IMAGES = os.getenv("USE_SOURCE_IMAGES", "false").lower() in {"1", "true", "yes"}
RIGHT_TO_REPLY_EMAIL = os.getenv("RIGHT_TO_REPLY_EMAIL", "news@rochdaledaily.co.uk")

FACEBOOK_EVENTS_DISCOVERY_URL = os.getenv(
    "FACEBOOK_EVENTS_DISCOVERY_URL",
    "https://www.facebook.com/events/?date_filter_option=ANY_DATE&discover_tab=CUSTOM&location_id=108023932551149",
).strip()
FACEBOOK_EVENTS_MAX = int(os.getenv("FACEBOOK_EVENTS_MAX", "18"))
FACEBOOK_EVENTS_BROWSER_TIMEOUT_MS = int(
    os.getenv("FACEBOOK_EVENTS_BROWSER_TIMEOUT_MS", "30000")
)
FACEBOOK_EVENT_IMAGE_REUSE = os.getenv(
    "FACEBOOK_EVENT_IMAGE_REUSE", "false"
).lower() in {"1", "true", "yes"}

IMAGE_REUSE_SOURCE_DOMAINS = {
    item.strip().lower()
    for item in os.getenv(
        "IMAGE_REUSE_SOURCE_DOMAINS",
        "rochdale.gov.uk,gmp.police.uk,manchesterfire.gov.uk,rochdaleafc.co.uk,"
        "rochdalehornets.co.uk,tfgm.com,gmca.gov.uk,nationalhighways.co.uk,"
        "hopwood.ac.uk,northerncarealliance.nhs.uk,penninecare.nhs.uk",
    ).split(",")
    if item.strip()
}

RSS_SOURCES = [
    {"name": "Rochdale Borough Council", "url": "https://www.rochdale.gov.uk/news/rss.xml", "default_area": "rochdale"},
    {"name": "Greater Manchester Police", "url": "https://www.gmp.police.uk/news/rss.xml", "default_area": "rochdale"},
    {"name": "BBC Manchester", "url": "https://feeds.bbci.co.uk/news/england/manchester/rss.xml", "default_area": "rochdale"},
    {"name": "Greater Manchester Fire and Rescue Service", "url": "https://www.manchesterfire.gov.uk/news-events/news/feed/", "default_area": "rochdale"},
    {"name": "Rochdale AFC", "url": "https://www.rochdaleafc.co.uk/news/feed", "default_area": "rochdale"},
]

DISCOVERY_PAGES = [
    # Rochdale Borough Council, democracy, planning, consultations and events
    {"name": "Rochdale Borough Council News", "url": "https://www.rochdale.gov.uk/news", "default_area": "rochdale", "link_pattern": r"/news/article/"},
    {"name": "Rochdale Council Your News", "url": "https://www.rochdale.gov.uk/yournews", "default_area": "rochdale", "link_pattern": r"/news/|/directory-record/|/events/"},
    {"name": "Rochdale Council Service Updates", "url": "https://www.rochdale.gov.uk/serviceupdates", "default_area": "rochdale", "link_pattern": r"/"},
    {"name": "Rochdale Council Events", "url": "https://www.rochdale.gov.uk/events", "default_area": "rochdale", "link_pattern": r"/events/event/"},
    {"name": "Rochdale Council Your Events", "url": "https://www.rochdale.gov.uk/yourevents", "default_area": "rochdale", "link_pattern": r"/events/|/directory-record/"},
    {"name": "Rochdale Council Consultations", "url": "https://consultations.rochdale.gov.uk/consultation_finder/?advanced=1", "default_area": "rochdale", "link_pattern": r"/"},
    {"name": "Rochdale Council Committees", "url": "https://democracy.rochdale.gov.uk/mgCalendarMonthView.aspx?GL=1&bcr=1", "default_area": "rochdale", "link_pattern": r"mgMeetingAttendance|ieListDocuments|mgCommitteeDetails"},
    {"name": "Rochdale Planning Applications", "url": "https://www.rochdale.gov.uk/planningapplications", "default_area": "rochdale", "link_pattern": r"planning|application|publicaccess"},
    {"name": "Rochdale Development Agency", "url": "https://investinrochdale.co.uk/news", "default_area": "rochdale", "link_pattern": r"/news/"},
    {"name": "Visit Rochdale", "url": "https://www.visitrochdale.com/whats-on", "default_area": "rochdale", "link_pattern": r"/whats-on/"},

    # Community, culture and voluntary-sector sources
    {"name": "Action Together Rochdale News", "url": "https://www.actiontogether.org.uk/rochdale-news", "default_area": "rochdale", "link_pattern": r"/"},
    {"name": "Action Together Latest News", "url": "https://www.actiontogether.org.uk/whats-happening", "default_area": "rochdale", "link_pattern": r"/"},
    {"name": "Your Trust Rochdale News", "url": "https://www.yourtrustrochdale.co.uk/news/", "default_area": "rochdale", "link_pattern": r"/news/|/category/news/"},
    {"name": "Your Trust Rochdale News Archive", "url": "https://www.yourtrustrochdale.co.uk/category/news/", "default_area": "rochdale", "link_pattern": r"/"},
    {"name": "Roch Valley Radio Local News", "url": "https://www.rochvalleyradio.com/news/local-news/", "default_area": "rochdale", "link_pattern": r"/news/local-news/"},
    {"name": "Roch Valley Radio Notices", "url": "https://www.rochvalleyradio.com/news/notices/", "default_area": "rochdale", "link_pattern": r"/news/notices/|/news/local-news/"},

    # Emergency, transport, utility and public-service sources
    {"name": "Greater Manchester Police", "url": "https://www.gmp.police.uk/news/", "default_area": "rochdale", "link_pattern": r"/news/"},
    {"name": "Greater Manchester Fire and Rescue Service", "url": "https://www.manchesterfire.gov.uk/news-events/news/", "default_area": "rochdale", "link_pattern": r"/news"},
    {"name": "TfGM Newsroom", "url": "https://news.tfgm.com/", "default_area": "rochdale", "link_pattern": r"/press-releases/"},
    {"name": "TfGM Travel Alerts", "url": "https://tfgm.com/travel-updates/travel-alerts", "default_area": "rochdale", "link_pattern": r"/travel-updates/"},
    {"name": "Northern News", "url": "https://media.northernrailway.co.uk/news/", "default_area": "rochdale", "link_pattern": r"/news/"},
    {"name": "Northern Service Updates", "url": "https://www.northernrailway.co.uk/service-updates", "default_area": "rochdale", "link_pattern": r"/service-updates|/news/"},
    {"name": "National Highways North West", "url": "https://nationalhighways.co.uk/our-roads/north-west/north-west-maintenance-schemes/", "default_area": "rochdale", "link_pattern": r"/"},
    {"name": "United Utilities Incidents", "url": "https://www.unitedutilities.com/emergencies/up-my-street/", "default_area": "rochdale", "link_pattern": r"/emergencies/|/incident/"},
    {"name": "GMCA News", "url": "https://www.greatermanchester-ca.gov.uk/news/", "default_area": "rochdale", "link_pattern": r"/news/"},

    # Local and regional publishers
    {"name": "Rochdale Online", "url": "https://www.rochdaleonline.co.uk/news-features/2/news", "default_area": "rochdale", "link_pattern": r"/news-features/2/news-headlines/"},
    {"name": "Manchester Evening News", "url": "https://www.manchestereveningnews.co.uk/all-about/rochdale", "default_area": "rochdale", "link_pattern": r"/news/"},
    {"name": "BBC Manchester", "url": "https://www.bbc.co.uk/news/england/manchester", "default_area": "rochdale", "link_pattern": r"/news/"},
    {"name": "About Manchester", "url": "https://aboutmanchester.co.uk/?s=Rochdale", "default_area": "rochdale", "link_pattern": r"/"},

    # Health and education
    {"name": "Northern Care Alliance Rochdale", "url": "https://www.northerncarealliance.nhs.uk/news/rochdale-news", "default_area": "rochdale", "link_pattern": r"/news/"},
    {"name": "Pennine Care NHS", "url": "https://www.penninecare.nhs.uk/about-us/latest-news", "default_area": "rochdale", "link_pattern": r"/latest-news/|/news/"},
    {"name": "Hopwood Hall College", "url": "https://www.hopwood.ac.uk/news-and-events/latest-news/", "default_area": "rochdale", "link_pattern": r"/news-and-events/"},
    {"name": "Rochdale Sixth Form College", "url": "https://www.rochdalesfc.ac.uk/news/", "default_area": "rochdale", "link_pattern": r"/news/"},

    # Sport
    {"name": "Rochdale AFC", "url": "https://rochdaleafc.co.uk/news/", "default_area": "rochdale", "link_pattern": r"/news/"},
    {"name": "Rochdale Hornets", "url": "https://www.rochdalehornets.co.uk/news", "default_area": "rochdale", "link_pattern": r"/news"},
]

SEARCH_GROUPS = [
    '"Rochdale" OR "Heywood" OR "Middleton"',
    '"Littleborough" OR "Milnrow" OR "Newhey" OR "Wardle"',
    '"Norden" OR "Bamford" OR "Castleton" OR "Kirkholt"',
    '"Spotland" OR "Falinge" OR "Deeplish" OR "Balderstone"',
    '"Shawclough" OR "Healey" OR "Smallbridge" OR "Smithy Bridge"',
    '"Darnhill" OR "Hopwood" OR "Alkrington" OR "Langley" OR "Boarshaw"',
    'Rochdale police OR court OR crime OR fire',
    'Rochdale traffic OR M62 OR roadworks OR Bee Network OR Northern',
    'Rochdale council OR planning OR consultation OR ward',
    'Rochdale sport OR Rochdale AFC OR Rochdale Hornets',
    'Rochdale community OR events OR school OR NHS',
    '"Roch Valley Radio" Rochdale',
    '"Action Together" Rochdale',
    '"Your Trust" Rochdale',
    'site:facebook.com/rochvalleyradio Rochdale',
    'site:facebook.com/rochdalecouncil Rochdale',
    'site:facebook.com/beenetworkgm Rochdale',
]

FACEBOOK_GRAPH_VERSION = os.getenv("FACEBOOK_GRAPH_VERSION", "v22.0")
FACEBOOK_PAGE_ACCESS_TOKEN = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN", "").strip()

# Third-party public Page reading requires the appropriate Meta app review/access.
# Additional pages can be supplied without code changes through FACEBOOK_PAGES_JSON.
PUBLIC_FACEBOOK_PAGES = [
    {"name": "Roch Valley Radio Facebook", "handle": "rochvalleyradio", "url": "https://www.facebook.com/rochvalleyradio", "default_area": "rochdale"},
    {"name": "Rochdale Borough Council Facebook", "handle": "rochdalecouncil", "url": "https://www.facebook.com/rochdalecouncil", "default_area": "rochdale"},
    {"name": "Bee Network Facebook", "handle": "beenetworkgm", "url": "https://www.facebook.com/beenetworkgm", "default_area": "rochdale"},
    {"name": "Rochdale Sixth Form College Facebook", "handle": "rochdalesfc", "url": "https://www.facebook.com/rochdalesfc", "default_area": "rochdale"},
]

try:
    extra_facebook_pages = json.loads(os.getenv("FACEBOOK_PAGES_JSON", "[]"))
    if isinstance(extra_facebook_pages, list):
        PUBLIC_FACEBOOK_PAGES.extend(
            page for page in extra_facebook_pages
            if isinstance(page, dict) and page.get("handle") and page.get("name")
        )
except json.JSONDecodeError:
    pass

LOCAL_TERMS = {
    "rochdale", "rochdale town centre", "heywood", "middleton",
    "littleborough", "milnrow", "newhey", "norden", "bamford",
    "kirkholt", "shawclough", "healey", "whitworth", "wardle",
    "smithy bridge", "castleton", "spotland", "falinge", "balderstone",
    "deeplish", "smallbridge", "firgrove", "syke", "cutgate",
    "darnhill", "hopwood", "alkrington", "langley", "boarshaw",
    "belfield", "wardleworth", "sudden", "buersil", "cloverhall",
    "lowerplace", "meanwood", "mandale park", "summit",
    "hollingworth lake", "slattocks", "birch", "caldershaw",
}

AREA_KEYWORDS = {
    "darnhill": {"darnhill"}, "hopwood": {"hopwood"},
    "alkrington": {"alkrington"}, "langley": {"langley"}, "boarshaw": {"boarshaw"},
    "newhey": {"newhey"}, "smithy_bridge": {"smithy bridge"}, "wardle": {"wardle"},
    "smallbridge": {"smallbridge"}, "norden": {"norden"}, "bamford": {"bamford"},
    "cutgate": {"cutgate", "caldershaw"}, "kirkholt": {"kirkholt"},
    "castleton": {"castleton"}, "spotland": {"spotland"}, "falinge": {"falinge"},
    "deeplish": {"deeplish"}, "balderstone": {"balderstone"}, "firgrove": {"firgrove"},
    "shawclough": {"shawclough"}, "healey": {"healey"}, "syke": {"syke"},
    "wardleworth": {"wardleworth"}, "sudden": {"sudden"},
    "lowerplace": {"lowerplace"}, "meanwood": {"meanwood"},
    "littleborough": {"littleborough", "hollingworth lake", "summit"},
    "milnrow": {"milnrow", "slattocks"}, "heywood": {"heywood"},
    "middleton": {"middleton"}, "whitworth": {"whitworth"},
    "rochdale": {"rochdale", "rochdale town centre", "town centre"},
}

CATEGORY_KEYWORDS = {
    "crime": {"arrest", "police", "charged", "court", "burglary", "robbery", "assault", "stabbing", "theft", "fraud", "wanted", "jailed", "murder"},
    "traffic": {"traffic", "roadworks", "road closure", "collision", "crash", "m62", "a627", "junction", "lane closure", "diversion", "congestion"},
    "transport": {"bus", "train", "tram", "metrolink", "bee network", "station", "timetable", "public transport"},
    "politics": {"council", "councillor", "election", "cabinet", "committee", "planning", "consultation", "mayor", "mp "},
    "education": {"school", "college", "university", "ofsted", "teacher", "pupil", "student", "education"},
    "sport": {"football", "rochdale afc", "hornets", "dale", "match", "fixture", "league", "rugby", "cricket", "boxing"},
    "events": {"festival", "concert", "event", "fair", "market", "open day", "exhibition", "gig", "performance", "parade"},
    "business": {"business", "shop", "restaurant", "pub", "company", "jobs", "investment", "opening", "closure"},
    "community": {"community", "charity", "fundraiser", "volunteer", "library", "support group", "appeal"},
    "health": {"nhs", "hospital", "health", "doctor", "gp", "clinic", "care service", "mental health"},
    "environment": {"flood", "weather", "environment", "recycling", "litter", "climate", "wildlife", "park"},
}

SENSITIVE_PATTERNS = [
    r"\b(alleged|allegedly|accused|suspect|suspected|charged|arrested|court|trial|jury|inquest|coroner)\b",
    r"\b(murder|manslaughter|rape|sexual|assault|abuse|grooming|stabbing|death|died|killed)\b",
    r"\b(child|children|minor|youth|under[- ]?18|schoolgirl|schoolboy)\b",
    r"\b(suicide|self-harm|domestic abuse|domestic violence)\b",
]

DROP_PATTERNS = [
    r"\b(opinion|comment|column|editorial)\b",
    r"\bfor sale\b|\bfor rent\b|\broom to let\b|\bjob vacancy\b",
    r"\brecommendations please\b|\bdoes anyone know\b|\bgetting rid of\b",
]

PLACEHOLDER_PATTERNS = [
    r"\[(?:insert|relevant|contact|date|number|details|link)[^\]]*\]",
    r"\babout this article\b.*$", r"\brelated topics\b.*$",
    r"#rochdalenews|#greatermanchester", r"\bfact-checked local journalism\b",
]

CATEGORY_STOCK_IMAGES = {
    category: f"assets/img/stock_{category}.jpg"
    for category in [
        "news", "crime", "traffic", "transport", "politics", "education",
        "sport", "events", "business", "community", "health", "environment",
    ]
}

ARTICLE_SCHEMA = {
    "name": "rochdale_daily_article",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "publishable": {"type": "boolean"},
            "title": {"type": "string"},
            "excerpt": {"type": "string"},
            "paragraphs": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 8},
            "category": {"type": "string", "enum": list(CATEGORY_STOCK_IMAGES)},
            "area": {"type": "string", "enum": list(AREA_KEYWORDS)},
            "legal_disclaimer": {"type": "string"},
            "right_to_reply": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": [
            "publishable", "title", "excerpt", "paragraphs", "category",
            "area", "legal_disclaimer", "right_to_reply", "reason",
        ],
    },
}

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger("rochdale_daily")

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "RochdaleDaily/3.0 (+https://rochdaledaily.co.uk; contact: news@rochdaledaily.co.uk)",
    "Accept-Language": "en-GB,en;q=0.9",
})

ROBOTS_CACHE: dict[str, urllib.robotparser.RobotFileParser] = {}

@dataclass
class Candidate:
    source_name: str
    source_url: str
    source_title: str
    source_summary: str
    source_published_at: str
    area: str
    category: str
    image_candidate_url: str = ""
    source_body_excerpt: str = ""
    event_start_at: str = ""
    event_end_at: str = ""
    event_location: str = ""
    source_kind: str = "article"
    related_sources: list[dict[str, str]] = field(default_factory=list)

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def domain_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host

def canonicalise_url(url: str) -> str:
    parsed = urlparse(url)
    query_parts = []
    for part in parsed.query.split("&"):
        low = part.lower()
        if part and not low.startswith(("utm_", "at_medium=", "at_campaign=", "fbclid=", "gclid=")):
            query_parts.append(part)
    return urlunparse((parsed.scheme or "https", parsed.netloc.lower(), parsed.path, "", "&".join(query_parts), ""))

def stable_id(url: str) -> str:
    return hashlib.sha256(canonicalise_url(url).encode("utf-8")).hexdigest()[:18]

def normalise_ws(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()

def strip_markdown(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"(\*\*|__)(.*?)\1", r"\2", text, flags=re.DOTALL)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", text)
    text = re.sub(r"(?<!_)_([^_\n]+)_(?!_)", r"\1", text)
    text = re.sub(r"`{1,3}([^`]+)`{1,3}", r"\1", text)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    for pattern in PLACEHOLDER_PATTERNS:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.MULTILINE)
    return normalise_ws(text).strip("*_#- ")

def make_slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", strip_markdown(title).lower()).strip("-")[:80] or "local-news-update"

def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        try:
            result = parsedate_to_datetime(str(value).strip())
        except (TypeError, ValueError, OverflowError):
            return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)

def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

def is_fresh(value: datetime | None) -> bool:
    if value is None:
        return False
    age = utc_now() - value
    return timedelta(minutes=-30) <= age <= timedelta(hours=MAX_NEWS_AGE_HOURS)

def detect_area(text: str, fallback: str = "rochdale") -> str:
    low = text.lower()
    for area, terms in AREA_KEYWORDS.items():
        if any(term in low for term in terms):
            return area
    return fallback

def categorise(text: str) -> str:
    low = text.lower()
    scores = {category: sum(1 for keyword in keywords if keyword in low) for category, keywords in CATEGORY_KEYWORDS.items()}
    category, score = max(scores.items(), key=lambda item: item[1])
    return category if score else "news"

def is_local(text: str, source_name: str) -> bool:
    low = text.lower()
    if source_name.startswith(("Rochdale Borough Council", "Rochdale AFC", "Rochdale Hornets", "Rochdale Development Agency")):
        return True
    return any(term in low for term in LOCAL_TERMS)

def should_drop(text: str) -> bool:
    low = text.lower()
    return any(re.search(pattern, low) for pattern in DROP_PATTERNS)

def is_sensitive(text: str, category: str) -> bool:
    return category == "crime" or any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in SENSITIVE_PATTERNS)

def robots_allows(url: str) -> bool:
    if not RESPECT_ROBOTS:
        return True
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    robot = ROBOTS_CACHE.get(base)
    if robot is None:
        robot = urllib.robotparser.RobotFileParser()
        robot.set_url(urljoin(base, "/robots.txt"))
        try:
            robot.read()
        except Exception:
            log.warning("Could not read robots.txt for %s; allowing a standard public-page request.", base)
            return True
        ROBOTS_CACHE[base] = robot
    try:
        return robot.can_fetch(SESSION.headers["User-Agent"], url)
    except Exception:
        return True

def fetch_html(url: str) -> tuple[str, str]:
    if not robots_allows(url):
        raise PermissionError(f"robots.txt does not permit fetching {url}")
    response = SESSION.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if "html" not in content_type and "<html" not in response.text[:500].lower():
        raise ValueError(f"Not an HTML page: {content_type}")
    return response.url, response.text

def first_meta(soup: BeautifulSoup, selectors: Iterable[tuple[str, dict[str, str]]]) -> str:
    for tag, attrs in selectors:
        node = soup.find(tag, attrs=attrs)
        if node and node.get("content"):
            return normalise_ws(node.get("content"))
    return ""

def extract_jsonld(soup: BeautifulSoup) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for node in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = node.string or node.get_text()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        queue = payload if isinstance(payload, list) else [payload]
        for item in queue:
            if isinstance(item, dict) and isinstance(item.get("@graph"), list):
                queue.extend(item["@graph"])
            elif isinstance(item, dict):
                objects.append(item)
    return objects

def image_from_jsonld(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value:
        return image_from_jsonld(value[0])
    if isinstance(value, dict):
        return str(value.get("url") or value.get("contentUrl") or "")
    return ""

def page_metadata(url: str) -> dict[str, str]:
    final_url, raw_html = fetch_html(url)
    soup = BeautifulSoup(raw_html, "lxml")
    jsonld = extract_jsonld(soup)
    title = first_meta(soup, [("meta", {"property": "og:title"}), ("meta", {"name": "twitter:title"})])
    if not title:
        h1 = soup.find("h1")
        title = normalise_ws(h1.get_text(" ", strip=True) if h1 else "")
    if not title and soup.title:
        title = normalise_ws(soup.title.get_text(" ", strip=True))
    description = first_meta(soup, [
        ("meta", {"property": "og:description"}),
        ("meta", {"name": "description"}),
        ("meta", {"name": "twitter:description"}),
    ])
    image_url = first_meta(soup, [
        ("meta", {"property": "og:image:secure_url"}),
        ("meta", {"property": "og:image"}),
        ("meta", {"name": "twitter:image"}),
    ])
    published = first_meta(soup, [
        ("meta", {"property": "article:published_time"}),
        ("meta", {"name": "article:published_time"}),
        ("meta", {"name": "date"}),
        ("meta", {"name": "pubdate"}),
    ])
    body_parts: list[str] = []
    for item in jsonld:
        kind = item.get("@type")
        kinds = set(kind if isinstance(kind, list) else [kind])
        if kinds.intersection({"NewsArticle", "Article", "ReportageNewsArticle", "Event"}):
            title = title or normalise_ws(item.get("headline") or item.get("name"))
            description = description or normalise_ws(item.get("description"))
            published = published or normalise_ws(item.get("datePublished") or item.get("startDate"))
            image_url = image_url or image_from_jsonld(item.get("image"))
            article_body = normalise_ws(item.get("articleBody"))
            if article_body:
                body_parts.append(article_body[:3500])
    if not body_parts:
        paragraphs = [normalise_ws(p.get_text(" ", strip=True)) for p in soup.select("article p, main p")]
        body_parts.extend([p for p in paragraphs if len(p) >= 40][:6])
    return {
        "url": canonicalise_url(final_url),
        "title": strip_markdown(title),
        "description": strip_markdown(description),
        "published": published,
        "image": urljoin(final_url, image_url) if image_url else "",
        "body_excerpt": normalise_ws(" ".join(body_parts))[:4500],
    }

def entry_datetime(entry: Any) -> datetime | None:
    for key in ("published", "updated", "created"):
        parsed = parse_datetime(getattr(entry, key, None))
        if parsed:
            return parsed
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = getattr(entry, key, None)
        if value:
            try:
                return datetime(*value[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None

def rss_image(entry: Any) -> str:
    for attr in ("media_content", "media_thumbnail"):
        for item in getattr(entry, attr, None) or []:
            if isinstance(item, dict) and item.get("url"):
                return str(item["url"])
    for item in getattr(entry, "enclosures", None) or []:
        if isinstance(item, dict) and str(item.get("type") or "").startswith("image/") and item.get("href"):
            return str(item["href"])
    return ""

def google_news_sources() -> list[dict[str, str]]:
    return [
        {
            "name": f"Google News search {index + 1}",
            "url": f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-GB&gl=GB&ceid=GB:en",
            "default_area": "rochdale",
            "aggregator": "google",
        }
        for index, query in enumerate(SEARCH_GROUPS)
    ]

def collect_rss_candidates() -> list[Candidate]:
    candidates: list[Candidate] = []
    for source in RSS_SOURCES + google_news_sources():
        log.info("Reading RSS: %s", source["name"])
        feed = feedparser.parse(source["url"])
        if getattr(feed, "bozo", False):
            log.warning("RSS warning for %s: %s", source["name"], getattr(feed, "bozo_exception", "unknown"))
        for entry in list(feed.entries)[:40]:
            source_url = canonicalise_url(str(getattr(entry, "link", "") or ""))
            source_title = strip_markdown(getattr(entry, "title", ""))
            summary_html = str(getattr(entry, "summary", "") or getattr(entry, "description", "") or "")
            summary = strip_markdown(BeautifulSoup(summary_html, "lxml").get_text(" ", strip=True))
            published = entry_datetime(entry)
            source_name = source["name"]
            entry_source = getattr(entry, "source", None)
            if isinstance(entry_source, dict):
                source_name = strip_markdown(entry_source.get("title")) or source_name
            text = f"{source_title} {summary}"
            if not source_url or not source_title or not is_fresh(published):
                continue
            if should_drop(text) or not is_local(text, source_name):
                continue
            image_url = rss_image(entry)
            body_excerpt = summary
            if source.get("aggregator") != "google" and (not image_url or len(summary) < 100):
                try:
                    meta = page_metadata(source_url)
                    source_title = meta["title"] or source_title
                    summary = meta["description"] or summary
                    image_url = image_url or meta["image"]
                    body_excerpt = meta["body_excerpt"] or body_excerpt
                    page_date = parse_datetime(meta["published"])
                    if page_date:
                        published = page_date
                except Exception as exc:
                    log.debug("Metadata fallback failed for %s: %s", source_url, exc)
            if not is_fresh(published):
                continue
            combined = f"{source_title} {summary} {body_excerpt}"
            candidates.append(Candidate(
                source_name=source_name,
                source_url=source_url,
                source_title=source_title,
                source_summary=summary,
                source_published_at=iso_utc(published),
                area=detect_area(combined, source["default_area"]),
                category=categorise(combined),
                image_candidate_url=image_url,
                source_body_excerpt=body_excerpt,
            ))
    return candidates

def discovery_links(source: dict[str, str]) -> list[str]:
    try:
        final_url, raw_html = fetch_html(source["url"])
    except Exception as exc:
        log.warning("Discovery page failed for %s: %s", source["name"], exc)
        return []
    soup = BeautifulSoup(raw_html, "lxml")
    pattern = re.compile(source["link_pattern"], re.IGNORECASE)
    links, seen = [], set()
    for anchor in soup.find_all("a", href=True):
        url = canonicalise_url(urljoin(final_url, anchor["href"]))
        if url in seen or domain_of(url) != domain_of(final_url):
            continue
        if not pattern.search(urlparse(url).path + "?" + urlparse(url).query):
            continue
        seen.add(url)
        links.append(url)
        if len(links) >= 20:
            break
    return links

def collect_discovery_candidates() -> list[Candidate]:
    candidates: list[Candidate] = []
    for source in DISCOVERY_PAGES:
        log.info("Discovering pages: %s", source["name"])
        for url in discovery_links(source):
            try:
                meta = page_metadata(url)
            except PermissionError as exc:
                log.info("%s", exc)
                continue
            except Exception as exc:
                log.debug("Page metadata failed for %s: %s", url, exc)
                continue
            published = parse_datetime(meta["published"])
            text = f"{meta['title']} {meta['description']} {meta['body_excerpt']}"
            if not meta["title"] or not is_fresh(published):
                continue
            if should_drop(text) or not is_local(text, source["name"]):
                continue
            candidates.append(Candidate(
                source_name=source["name"],
                source_url=meta["url"],
                source_title=meta["title"],
                source_summary=meta["description"],
                source_published_at=iso_utc(published),
                area=detect_area(text, source["default_area"]),
                category=categorise(text),
                image_candidate_url=meta["image"],
                source_body_excerpt=meta["body_excerpt"],
            ))
            time.sleep(0.15)
    return candidates



def extract_future_event_date(text: str) -> str:
    """
    Extract a likely future event date from visible Facebook event-card text.

    Facebook's discovery UI changes frequently, so this is intentionally
    conservative. It returns an empty string if no plausible date is found.
    """
    cleaned = normalise_ws(text)
    if not cleaned:
        return ""
    try:
        matches = search_dates(
            cleaned,
            languages=["en"],
            settings={
                "PREFER_DATES_FROM": "future",
                "RELATIVE_BASE": utc_now(),
                "RETURN_AS_TIMEZONE_AWARE": True,
                "TIMEZONE": "Europe/London",
                "TO_TIMEZONE": "UTC",
            },
        ) or []
    except Exception:
        return ""

    for matched_text, value in matches[:5]:
        if value is None:
            continue
        value_utc = value.astimezone(timezone.utc)
        if utc_now() - timedelta(hours=12) <= value_utc <= utc_now() + timedelta(days=550):
            return iso_utc(value_utc)
    return ""


def clean_facebook_event_title(value: str) -> str:
    title = strip_markdown(value)
    title = re.sub(
        r"^(?:Facebook|Events?|Interested|Going|Share)\s*[-:|]\s*",
        "",
        title,
        flags=re.IGNORECASE,
    )
    return title[:180]


def collect_facebook_event_discovery_candidates() -> list[Candidate]:
    """
    Read the exact Rochdale Facebook Events discovery page supplied by the
    publisher using a logged-out public browser session.

    The collector does not bypass a login wall, use private groups, inject
    cookies or defeat anti-bot controls. If Facebook does not expose the
    discovery page publicly during a run, it logs the limitation and returns
    no events.

    Event cover-image URLs are recorded as source-image candidates. They are
    not automatically republished unless FACEBOOK_EVENT_IMAGE_REUSE=true,
    because public visibility does not itself grant copyright permission.
    """
    if not FACEBOOK_EVENTS_DISCOVERY_URL:
        return []

    log.info("Reading Facebook Events discovery source: %s", FACEBOOK_EVENTS_DISCOVERY_URL)
    raw_cards: list[dict[str, str]] = []

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=[
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            context = browser.new_context(
                locale="en-GB",
                timezone_id="Europe/London",
                viewport={"width": 1440, "height": 1100},
                user_agent=SESSION.headers["User-Agent"],
            )
            page = context.new_page()
            page.set_default_timeout(FACEBOOK_EVENTS_BROWSER_TIMEOUT_MS)

            try:
                page.goto(
                    FACEBOOK_EVENTS_DISCOVERY_URL,
                    wait_until="domcontentloaded",
                    timeout=FACEBOOK_EVENTS_BROWSER_TIMEOUT_MS,
                )
            except PlaywrightTimeoutError:
                log.warning("Facebook Events discovery page timed out during initial load.")

            # Best-effort dismissal of cookie banners that may obscure the page.
            for label in (
                "Allow all cookies",
                "Decline optional cookies",
                "Only allow essential cookies",
                "Close",
                "Not now",
            ):
                try:
                    button = page.get_by_role("button", name=re.compile(label, re.I))
                    if button.count():
                        button.first.click(timeout=1500)
                except Exception:
                    pass

            page.wait_for_timeout(3500)
            for _ in range(4):
                page.mouse.wheel(0, 1500)
                page.wait_for_timeout(900)

            body_text = normalise_ws(page.locator("body").inner_text(timeout=5000))
            if re.search(r"\blog in\b|\bsign up\b", body_text, flags=re.IGNORECASE):
                # Do not fail immediately: Facebook sometimes displays login prompts
                # alongside public results. We still inspect any public event links.
                log.info("Facebook displayed a login prompt; checking for public event cards.")

            raw_cards = page.evaluate(
                """
                () => {
                  const results = [];
                  const seen = new Set();
                  const links = Array.from(document.querySelectorAll('a[href*="/events/"]'));

                  for (const link of links) {
                    const rawHref = link.href || link.getAttribute('href') || '';
                    const match = rawHref.match(/facebook\\.com\\/events\\/(\\d+)/i);
                    if (!match) continue;

                    const eventUrl = `https://www.facebook.com/events/${match[1]}/`;
                    if (seen.has(eventUrl)) continue;
                    seen.add(eventUrl);

                    let card = link.closest('[role="article"]');
                    if (!card) {
                      let current = link;
                      for (let depth = 0; depth < 7 && current; depth += 1) {
                        if (current.querySelector && current.querySelector('img')) {
                          card = current;
                        }
                        current = current.parentElement;
                      }
                    }
                    card = card || link.parentElement || link;

                    const text = (card.innerText || link.innerText || '').trim();
                    const aria = (link.getAttribute('aria-label') || '').trim();
                    const image = card.querySelector ? card.querySelector('img[src]') : null;
                    const title =
                      aria ||
                      (link.innerText || '').trim() ||
                      (text.split('\\n').find(line => line.trim().length > 3) || '');

                    results.push({
                      url: eventUrl,
                      title,
                      text,
                      image: image ? (image.currentSrc || image.src || '') : '',
                    });

                    if (results.length >= 40) break;
                  }
                  return results;
                }
                """
            )

            context.close()
            browser.close()
    except Exception as exc:
        log.warning("Facebook Events browser collector unavailable: %s", exc)
        return []

    if not raw_cards:
        log.warning(
            "No public event cards were exposed by the supplied Facebook Events page. "
            "The source remains configured and will be retried on the next run."
        )
        return []

    candidates: list[Candidate] = []
    seen_urls: set[str] = set()

    for card in raw_cards:
        event_url = canonicalise_url(card.get("url", ""))
        if not event_url or event_url in seen_urls:
            continue
        seen_urls.add(event_url)

        visible_text = strip_markdown(card.get("text", ""))
        title = clean_facebook_event_title(card.get("title", ""))
        if not title or len(title) < 4:
            lines = [normalise_ws(line) for line in str(card.get("text", "")).splitlines()]
            title = next((line for line in lines if len(line) >= 4), "")
            title = clean_facebook_event_title(title)
        if not title:
            continue

        combined = f"{title} {visible_text}"
        # The supplied location filter is Rochdale, but retaining local validation
        # prevents unrelated promoted events from being auto-published.
        if not is_local(combined, "Facebook Rochdale Events"):
            continue

        event_start = extract_future_event_date(visible_text)
        image_url = str(card.get("image") or "").strip()

        summary_parts = [visible_text]
        if event_start:
            summary_parts.append(f"Structured event start: {event_start}")
        summary = normalise_ws(" ".join(summary_parts))[:1600]

        candidates.append(Candidate(
            source_name="Facebook Events — Rochdale discovery",
            source_url=event_url,
            source_title=title,
            source_summary=summary,
            source_published_at=iso_utc(utc_now()),
            area=detect_area(combined, "rochdale"),
            category="events",
            image_candidate_url=image_url,
            source_body_excerpt=visible_text[:4000],
            event_start_at=event_start,
            event_location="Rochdale area",
            source_kind="event",
        ))

        if len(candidates) >= FACEBOOK_EVENTS_MAX:
            break

    log.info("Facebook Events discovery collected %d public event listings.", len(candidates))
    return candidates


def collect_facebook_candidates() -> list[Candidate]:
    """
    Read configured public Facebook Pages through Meta's supported Graph API.

    This does not scrape Facebook HTML, bypass login screens or read private
    groups. For pages not managed by the app owner, Meta requires Page Public
    Content Access. If the token/permission is absent, the source is skipped.
    """
    if not FACEBOOK_PAGE_ACCESS_TOKEN:
        log.info(
            "Facebook Page sources configured but inactive: add the "
            "FACEBOOK_PAGE_ACCESS_TOKEN GitHub secret after obtaining the "
            "required Meta Page Public Content Access."
        )
        return []

    candidates: list[Candidate] = []
    for page in PUBLIC_FACEBOOK_PAGES:
        handle = str(page["handle"]).strip("/")
        endpoint = f"https://graph.facebook.com/{FACEBOOK_GRAPH_VERSION}/{handle}/posts"
        params = {
            "access_token": FACEBOOK_PAGE_ACCESS_TOKEN,
            "fields": "id,message,created_time,permalink_url,full_picture,attachments{media_type,url,target}",
            "limit": "25",
        }
        try:
            response = SESSION.get(endpoint, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            log.warning("Facebook source unavailable for %s: %s", page["name"], exc)
            continue

        for post in payload.get("data", []):
            message = strip_markdown(post.get("message", ""))
            created = parse_datetime(post.get("created_time"))
            permalink = canonicalise_url(
                post.get("permalink_url")
                or f"https://www.facebook.com/{handle}/posts/{post.get('id', '')}"
            )
            if not message or not is_fresh(created):
                continue
            if should_drop(message) or not is_local(message, page["name"]):
                continue

            title = message.split(".")[0].strip()
            if len(title) < 35:
                title = message[:140].rsplit(" ", 1)[0]
            image = str(post.get("full_picture") or "")
            category = categorise(message)
            candidates.append(Candidate(
                source_name=page["name"],
                source_url=permalink,
                source_title=title[:160],
                source_summary=message[:900],
                source_published_at=iso_utc(created),
                area=detect_area(message, page.get("default_area", "rochdale")),
                category=category,
                image_candidate_url=image,
                source_body_excerpt=message[:3500],
            ))
    return candidates


def collect_environment_agency_flood_candidates() -> list[Candidate]:
    """
    Fetch active flood alerts/warnings within 25 km of central Rochdale using
    the Environment Agency real-time flood-monitoring API.
    """
    endpoint = "https://environment.data.gov.uk/flood-monitoring/id/floods"
    params = {"lat": "53.6097", "long": "-2.1561", "dist": "25"}
    try:
        response = SESSION.get(endpoint, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        log.warning("Environment Agency flood feed unavailable: %s", exc)
        return []

    candidates: list[Candidate] = []
    for item in payload.get("items", []):
        severity_level = int(item.get("severityLevel") or 4)
        if severity_level >= 4:
            continue
        changed = parse_datetime(
            item.get("timeMessageChanged")
            or item.get("timeSeverityChanged")
            or item.get("timeRaised")
        ) or utc_now()
        area_name = strip_markdown(
            item.get("eaAreaName")
            or item.get("description")
            or item.get("floodArea", {}).get("label")
            or "Rochdale flood alert"
        )
        message = strip_markdown(item.get("message") or item.get("description") or "")
        title = f"{item.get('severity', 'Flood alert')}: {area_name}"
        source_url = str(item.get("@id") or endpoint).replace("http://", "https://")
        text = f"{title} {message}"
        candidates.append(Candidate(
            source_name="Environment Agency flood-monitoring API",
            source_url=source_url,
            source_title=title[:160],
            source_summary=message[:900],
            source_published_at=iso_utc(changed),
            area=detect_area(text, "rochdale"),
            category="environment",
            source_body_excerpt=message[:3500],
        ))
    return candidates


def title_tokens(title: str) -> set[str]:
    stop = {"the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with", "from", "at", "rochdale"}
    return {word for word in re.findall(r"[a-z0-9]+", title.lower()) if len(word) > 2 and word not in stop}

def title_similarity(a: str, b: str) -> float:
    aa, bb = title_tokens(a), title_tokens(b)
    if not aa or not bb:
        return 0.0
    return len(aa & bb) / len(aa | bb)

def deduplicate_and_cross_reference(candidates: Iterable[Candidate]) -> list[Candidate]:
    ordered = sorted(candidates, key=lambda item: item.source_published_at, reverse=True)
    primaries: list[Candidate] = []
    seen_urls: set[str] = set()
    for candidate in ordered:
        url_key = canonicalise_url(candidate.source_url)
        if url_key in seen_urls:
            continue
        seen_urls.add(url_key)
        matched = None
        for primary in primaries:
            if title_similarity(candidate.source_title, primary.source_title) >= 0.38:
                matched = primary
                break
        if matched:
            matched.related_sources.append({
                "name": candidate.source_name,
                "url": candidate.source_url,
                "title": candidate.source_title,
                "summary": candidate.source_summary[:900],
                "published_at": candidate.source_published_at,
            })
        else:
            primaries.append(candidate)
    return primaries

def load_json_list(path: Path) -> list[dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def recent_existing_articles() -> list[dict[str, Any]]:
    cutoff = utc_now() - timedelta(days=RETENTION_DAYS)
    kept = []
    for article in load_json_list(OUTPUT_FILE):
        published = parse_datetime(article.get("published_at"))
        if published and published >= cutoff:
            article["title"] = strip_markdown(article.get("title"))
            article["excerpt"] = strip_markdown(article.get("excerpt"))
            kept.append(article)
    return kept

def source_image(candidate: Candidate, category: str) -> tuple[str, str]:
    fallback = CATEGORY_STOCK_IMAGES.get(category, CATEGORY_STOCK_IMAGES["news"])
    if not candidate.image_candidate_url:
        return fallback, "Rochdale Daily category image"

    source_domain = domain_of(candidate.source_url)
    if (
        candidate.source_kind == "event"
        and source_domain == "facebook.com"
        and FACEBOOK_EVENT_IMAGE_REUSE
    ):
        return candidate.image_candidate_url, f"Event image via {candidate.source_name}"

    if not USE_SOURCE_IMAGES:
        return fallback, "Rochdale Daily category image"
    if source_domain in IMAGE_REUSE_SOURCE_DOMAINS:
        return candidate.image_candidate_url, candidate.source_name
    return fallback, "Rochdale Daily category image"

POSTCODE_RE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", re.IGNORECASE)
ADDRESS_RE = re.compile(
    r"\b\d{1,4}[A-Za-z]?\s+(?:[A-Z][a-z'-]+\s+){0,4}"
    r"(?:Street|St|Road|Rd|Lane|Ln|Drive|Dr|Avenue|Ave|Close|Court|Way|Crescent|Place|Terrace|Gardens|Grove)\b",
    re.IGNORECASE,
)
PERSON_RE = re.compile(r"\b(?:Mr|Mrs|Ms|Miss|Dr)?\s*([A-Z][a-z'-]+(?:\s+[A-Z][a-z'-]+){1,2})\b")
NAME_EXCLUSIONS = {
    "Greater Manchester", "Rochdale Daily", "Rochdale Council", "Rochdale Borough Council",
    "Greater Manchester Police", "Manchester Evening News", "Rochdale Online",
    "Rochdale AFC", "Rochdale Hornets", "National Highways", "Bee Network",
    "Northern Care Alliance", "Pennine Care", "Hopwood Hall", "United Kingdom",
}

def source_person_names(text: str) -> set[str]:
    found = set()
    for match in PERSON_RE.finditer(text):
        name = normalise_ws(match.group(1))
        if name not in NAME_EXCLUSIONS and not any(place.lower() in name.lower() for place in LOCAL_TERMS):
            found.add(name)
    return found

def anonymise_output(text: str, source_text: str) -> str:
    result = POSTCODE_RE.sub("the Rochdale area", str(text or ""))
    result = ADDRESS_RE.sub("a location in the Rochdale borough", result)
    for name in sorted(source_person_names(source_text), key=len, reverse=True):
        result = re.sub(rf"\b{re.escape(name)}\b", "an individual", result, flags=re.IGNORECASE)
    result = re.sub(r"\b(?:Mr|Mrs|Ms|Miss)\s+[A-Z][a-z'-]+\b", "the individual", result)
    return strip_markdown(result)

def default_legal_disclaimer(sensitive: bool) -> str:
    if sensitive:
        return (
            "This report is based on information published by identified public sources. "
            "No finding of guilt should be inferred from an arrest, allegation or charge. "
            "Anyone accused of an offence is presumed innocent unless and until convicted. "
            "Rochdale Daily does not publish suspected offenders' names or exact residential addresses "
            "in automatically produced reports, and the article may be updated as verified information changes."
        )
    return (
        "This article was compiled from identified public sources and may be updated when further verified "
        "information becomes available."
    )

def rewrite_candidate(candidate: Candidate, client: OpenAI | None) -> dict[str, Any] | None:
    source_records = [{
        "name": candidate.source_name,
        "url": candidate.source_url,
        "title": candidate.source_title,
        "summary": candidate.source_summary,
        "body_excerpt": candidate.source_body_excerpt,
        "published_at": candidate.source_published_at,
        "source_kind": candidate.source_kind,
        "event_start_at": candidate.event_start_at,
        "event_end_at": candidate.event_end_at,
        "event_location": candidate.event_location,
    }] + candidate.related_sources[:4]

    source_text = normalise_ws(" ".join(
        f"{item.get('title','')} {item.get('summary','')} {item.get('body_excerpt','')}"
        for item in source_records
    ))[:12000]
    sensitive = is_sensitive(source_text, candidate.category)

    if client is None:
        # Conservative fallback: only publish a short source-led brief from official organisations.
        official = domain_of(candidate.source_url) in IMAGE_REUSE_SOURCE_DOMAINS
        if not official or len(candidate.source_summary) < 80:
            return None
        paragraphs = [
            strip_markdown(candidate.source_summary)[:700],
            f"Further information is available from {candidate.source_name}.",
            "Rochdale Daily will update this report if the source publishes material changes.",
        ]
        draft = {
            "publishable": True,
            "title": candidate.source_title,
            "excerpt": candidate.source_summary[:280],
            "paragraphs": paragraphs,
            "category": candidate.category,
            "area": candidate.area,
            "legal_disclaimer": default_legal_disclaimer(sensitive),
            "right_to_reply": f"Anyone directly affected may request a correction or right of reply by emailing {RIGHT_TO_REPLY_EMAIL}.",
            "reason": "Official-source fallback used because no OpenAI API key was available.",
        }
    else:
        system_message = (
            "You are the sub-editor for Rochdale Daily, an independent UK local-news publication. "
            "Write an original local article using only the supplied source records. Combine corroborating "
            "details where sources agree, but never invent facts, dates, quotations, prices, statistics, "
            "organisations, contact details or local impact. Do not claim the article is fact-checked. "
            "Do not output Markdown, HTML, hashtags or links. Use neutral UK English and short paragraphs. "
            "For crime, court, safeguarding, deaths, allegations or active investigations: omit every "
            "suspect, defendant, victim, witness and private individual's name; omit house numbers, exact "
            "residential addresses and postcodes; do not mention previous convictions; do not speculate "
            "about guilt, motive or evidence; do not identify sexual-offence complainants or anyone under 18; "
            "and use only confirmed basic facts, official public-safety advice and procedural status. "
            "A legal disclaimer is not permission to publish unsafe facts. If safe anonymisation is impossible "
            "or the source material is too thin or contradictory, set publishable to false."
        )
        user_message = json.dumps({
            "primary_source": candidate.source_name,
            "primary_url": candidate.source_url,
            "source_published_at": candidate.source_published_at,
            "detected_area": candidate.area,
            "detected_category": candidate.category,
            "sensitive_story": sensitive,
            "source_records": source_records,
            "requested_style": (
                "Headline under 150 characters; standfirst of 35-65 words; 4-7 paragraphs. "
                "Add useful background only when it is explicitly present in the supplied records. "
                "For event listings, clearly state the supplied date, time, location, ticket or access "
                "information, age suitability and booking details only when those facts appear in the "
                "source records. Never invent missing event details. Explain practical local relevance "
                "without exaggeration."
            ),
            "required_right_to_reply": (
                f"Anyone directly affected may request a correction or right of reply by emailing "
                f"{RIGHT_TO_REPLY_EMAIL}."
            ),
        }, ensure_ascii=False)
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "system", "content": system_message}, {"role": "user", "content": user_message}],
            response_format={"type": "json_schema", "json_schema": ARTICLE_SCHEMA},
            temperature=0.15,
            max_tokens=1400,
        )
        draft = json.loads(response.choices[0].message.content or "{}")

    if not bool(draft.get("publishable")):
        return None

    title = strip_markdown(draft.get("title"))[:160]
    excerpt = strip_markdown(draft.get("excerpt"))[:360]
    paragraphs = [strip_markdown(item) for item in draft.get("paragraphs", []) if strip_markdown(item)][:8]
    category = str(draft.get("category") or candidate.category)
    area = str(draft.get("area") or candidate.area)
    if category not in CATEGORY_STOCK_IMAGES:
        category = candidate.category if candidate.category in CATEGORY_STOCK_IMAGES else "news"
    if area not in AREA_KEYWORDS:
        area = candidate.area if candidate.area in AREA_KEYWORDS else "rochdale"

    if sensitive:
        title = anonymise_output(title, source_text)
        excerpt = anonymise_output(excerpt, source_text)
        paragraphs = [anonymise_output(paragraph, source_text) for paragraph in paragraphs]
        paragraphs = [p for p in paragraphs if p]

    if not title or not excerpt or len(paragraphs) < 3:
        return None

    image_url, image_credit = source_image(candidate, category)
    source_urls = [candidate.source_url] + [item["url"] for item in candidate.related_sources[:4] if item.get("url")]
    source_names = [candidate.source_name] + [item["name"] for item in candidate.related_sources[:4] if item.get("name")]

    legal_disclaimer = strip_markdown(draft.get("legal_disclaimer")) or default_legal_disclaimer(sensitive)
    right_to_reply = strip_markdown(draft.get("right_to_reply")) or (
        f"Anyone directly affected may request a correction or right of reply by emailing {RIGHT_TO_REPLY_EMAIL}."
    )

    if sensitive:
        legal_disclaimer = anonymise_output(legal_disclaimer, source_text)
        right_to_reply = anonymise_output(right_to_reply, source_text)

    return {
        "id": stable_id(candidate.source_url),
        "title": title,
        "slug": make_slug(title),
        "excerpt": excerpt,
        "content_html": "".join(f"<p>{html.escape(paragraph)}</p>" for paragraph in paragraphs),
        "area": area,
        "category": category,
        "types": [category],
        "published_at": candidate.source_published_at,
        "scraped_at": iso_utc(utc_now()),
        "image_url": image_url,
        "image_credit": image_credit,
        "source_image_candidate_url": (
            candidate.image_candidate_url if candidate.source_kind == "event" else ""
        ),
        "source_image_reuse_status": (
            "enabled-by-publisher"
            if candidate.source_kind == "event" and FACEBOOK_EVENT_IMAGE_REUSE
            else "permission-required"
            if candidate.source_kind == "event" and candidate.image_candidate_url
            else ""
        ),
        "event_start_at": candidate.event_start_at,
        "event_end_at": candidate.event_end_at,
        "event_location": candidate.event_location,
        "source_kind": candidate.source_kind,
        "source_name": candidate.source_name,
        "source_url": candidate.source_url,
        "source_names": source_names,
        "source_urls": source_urls,
        "source_count": len(source_urls),
        "sensitive_story": sensitive,
        "police_matter": category == "crime",
        "legal_disclaimer": legal_disclaimer,
        "right_to_reply": right_to_reply,
        "byline": "Rochdale Daily Newsdesk",
        "status": "published",
    }

def write_json_atomic(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)

def main() -> int:
    log.info("Starting Rochdale Daily 15-minute pipeline")
    existing = recent_existing_articles()
    existing_by_source = {
        canonicalise_url(str(item.get("source_url") or "")): item
        for item in existing if item.get("source_url")
    }

    candidates = deduplicate_and_cross_reference(
        collect_rss_candidates()
        + collect_discovery_candidates()
        + collect_facebook_event_discovery_candidates()
        + collect_facebook_candidates()
        + collect_environment_agency_flood_candidates()
    )
    log.info("Fresh local story clusters: %d", len(candidates))

    api_key = os.getenv("OPENAI_API_KEY")
    client = OpenAI(api_key=api_key) if api_key else None
    run_limit = MAX_AI_ARTICLES_INITIAL if not existing else MAX_AI_ARTICLES_PER_RUN

    new_articles: list[dict[str, Any]] = []
    ai_count = 0
    skipped = 0

    for candidate in candidates:
        if canonicalise_url(candidate.source_url) in existing_by_source:
            continue
        if ai_count >= run_limit:
            break
        try:
            article = rewrite_candidate(candidate, client)
        except Exception as exc:
            log.exception("Rewrite failed for %s: %s", candidate.source_url, exc)
            skipped += 1
            continue
        ai_count += 1
        if article:
            new_articles.append(article)
        else:
            skipped += 1

    merged: dict[str, dict[str, Any]] = {}
    for article in new_articles + existing:
        key = canonicalise_url(str(article.get("source_url") or article.get("id") or ""))
        if key and key not in merged:
            merged[key] = article

    published = sorted(
        merged.values(),
        key=lambda article: parse_datetime(article.get("published_at")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )[:MAX_PUBLISHED_ARTICLES]

    write_json_atomic(OUTPUT_FILE, published)
    log.info(
        "Complete: %d live articles, %d new, %d AI/fallback attempts, %d skipped",
        len(published), len(new_articles), ai_count, skipped,
    )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
