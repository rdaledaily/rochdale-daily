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
    # Council, democracy, consultations and events
    {"name": "Rochdale Borough Council News", "url": "https://www.rochdale.gov.uk/news", "default_area": "rochdale", "link_pattern": r"/news/article/"},
    {"name": "Rochdale Council Service Updates", "url": "https://www.rochdale.gov.uk/serviceupdates", "default_area": "rochdale", "link_pattern": r"/"},
    {"name": "Rochdale Council Events", "url": "https://www.rochdale.gov.uk/events", "default_area": "rochdale", "link_pattern": r"/events/event/"},
    {"name": "Rochdale Council Consultations", "url": "https://consultations.rochdale.gov.uk/consultation_finder/?advanced=1", "default_area": "rochdale", "link_pattern": r"/"},
    {"name": "Rochdale Council Committees", "url": "https://democracy.rochdale.gov.uk/mgCalendarMonthView.aspx?GL=1&bcr=1", "default_area": "rochdale", "link_pattern": r"mgMeetingAttendance|ieListDocuments|mgCommitteeDetails"},
    {"name": "Rochdale Development Agency", "url": "https://investinrochdale.co.uk/news", "default_area": "rochdale", "link_pattern": r"/news/"},
    {"name": "Visit Rochdale", "url": "https://www.visitrochdale.com/whats-on", "default_area": "rochdale", "link_pattern": r"/whats-on/"},
    # Emergency and public services
    {"name": "Greater Manchester Police", "url": "https://www.gmp.police.uk/news/", "default_area": "rochdale", "link_pattern": r"/news/"},
    {"name": "Greater Manchester Fire and Rescue Service", "url": "https://www.manchesterfire.gov.uk/news-events/news/", "default_area": "rochdale", "link_pattern": r"/news"},
    {"name": "TfGM Newsroom", "url": "https://news.tfgm.com/", "default_area": "rochdale", "link_pattern": r"/press-releases/"},
    {"name": "TfGM Travel Alerts", "url": "https://tfgm.com/travel-updates/travel-alerts", "default_area": "rochdale", "link_pattern": r"/travel-updates/"},
    {"name": "National Highways North West", "url": "https://nationalhighways.co.uk/our-roads/north-west/north-west-maintenance-schemes/", "default_area": "rochdale", "link_pattern": r"/"},
    {"name": "GMCA News", "url": "https://www.greatermanchester-ca.gov.uk/news/", "default_area": "rochdale", "link_pattern": r"/news/"},
    # Local and regional news publishers
    {"name": "Rochdale Online", "url": "https://www.rochdaleonline.co.uk/news-features/2/news", "default_area": "rochdale", "link_pattern": r"/news-features/2/news-headlines/"},
    {"name": "Rochdale Times", "url": "https://www.rochdaletimes.co.uk/category/bn-news/", "default_area": "rochdale", "link_pattern": r"/"},
    {"name": "Roch Valley Radio", "url": "https://www.rochvalleyradio.com/news/local-news/", "default_area": "rochdale", "link_pattern": r"/news/local-news/"},
    {"name": "Manchester Evening News", "url": "https://www.manchestereveningnews.co.uk/all-about/rochdale", "default_area": "rochdale", "link_pattern": r"/news/"},
    {"name": "BBC Manchester", "url": "https://www.bbc.co.uk/news/england/manchester", "default_area": "rochdale", "link_pattern": r"/news/"},
    {"name": "About Manchester", "url": "https://aboutmanchester.co.uk/?s=Rochdale", "default_area": "rochdale", "link_pattern": r"/"},
    # Health and education
    {"name": "Northern Care Alliance Rochdale", "url": "https://www.northerncarealliance.nhs.uk/news/rochdale-news", "default_area": "rochdale", "link_pattern": r"/news/"},
    {"name": "Pennine Care NHS", "url": "https://www.penninecare.nhs.uk/about-us/latest-news", "default_area": "rochdale", "link_pattern": r"/latest-news/|/news/"},
    {"name": "Hopwood Hall College", "url": "https://www.hopwood.ac.uk/news-and-events/latest-news/", "default_area": "rochdale", "link_pattern": r"/news-and-events/"},
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
    'Rochdale traffic OR M62 OR roadworks OR Bee Network',
    'Rochdale council OR planning OR consultation OR ward',
    'Rochdale sport OR Rochdale AFC OR Rochdale Hornets',
    'Rochdale community OR events OR school OR NHS',
]

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
    if not USE_SOURCE_IMAGES or not candidate.image_candidate_url:
        return fallback, "Rochdale Daily category image"
    source_domain = domain_of(candidate.source_url)
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
                "Explain practical local relevance without exaggeration."
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
        collect_rss_candidates() + collect_discovery_candidates()
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
